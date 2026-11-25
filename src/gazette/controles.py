"""Contrôles de qualité sur les vraies données, avec alerte Discord (TD 4).

Ce ne sont pas des tests de code (ceux-là sont dans la CI) : ce sont des faits
vérifiés sur les données après chaque passage. Chaque résultat est écrit dans
``controles_qualite`` (le TD 8 viendra les lire). Un contrôle en échec envoie une
alerte, au plus une fois par ``FENETRE_ANTISPAM`` pour le même contrôle.
Lançable sans Prefect : ``python -m gazette.controles``.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from gazette.alerte import envoyer_alerte
from gazette.connexion import ouvrir_connexion
from gazette.rapport_qualite import bornes_jour
from gazette.regles_config import TOLERANCE_DATE_FUTURE

logger = logging.getLogger("gazette.controles")

SEUIL_TAUX_REJET = 0.80
MIN_ENTRES_TAUX = 10  # on ne juge pas le taux d'une source avec moins d'articles
SEUIL_FRAICHEUR_H = 24
FENETRE_ANTISPAM = timedelta(hours=6)


@dataclass
class Resultat:
    nom: str
    portee: str
    valeur: float
    seuil: float
    ok: bool
    detail: str = ""
    alerte: bool = True  # False : on enregistre, mais on n'alerte pas


def verifier(conn, maintenant: datetime | None = None) -> list[Resultat]:
    """Exécute tous les contrôles et renvoie leurs résultats."""
    maintenant = maintenant or datetime.now(timezone.utc)
    resultats: list[Resultat] = []
    with conn.cursor() as cur:
        # 1. Aucune date future (au-delà de la tolérance de fuseau)
        limite = maintenant + TOLERANCE_DATE_FUTURE
        cur.execute("SELECT count(*) FROM articles_propres WHERE publie_le > %s", (limite,))
        nombre = int(cur.fetchone()[0])
        exemples = ""
        if nombre:
            cur.execute(
                "SELECT item_id, source, publie_le FROM articles_propres "
                "WHERE publie_le > %s ORDER BY publie_le DESC LIMIT 3",
                (limite,),
            )
            exemples = "; ".join(f"{s} {i[:10]} {p.isoformat()}" for i, s, p in cur.fetchall())
        resultats.append(Resultat("date_future", "global", nombre, 0, nombre == 0, exemples))

        # 2. Aucun titre vide
        cur.execute(
            "SELECT count(*) FROM articles_propres WHERE titre IS NULL OR btrim(titre) = ''"
        )
        nombre = int(cur.fetchone()[0])
        resultats.append(Resultat("titre_vide", "global", nombre, 0, nombre == 0))

        # 3. Taux de rejet par source (journée UTC en cours)
        debut, fin = bornes_jour(maintenant.date())
        cur.execute(
            "SELECT source, sum(g), sum(r) FROM ("
            " SELECT source, 1 AS g, 0 AS r FROM articles_propres"
            "  WHERE nettoye_le >= %s AND nettoye_le < %s"
            " UNION ALL"
            " SELECT source, 0, 1 FROM rejets WHERE rejete_le >= %s AND rejete_le < %s"
            ") t GROUP BY source ORDER BY source",
            (debut, fin, debut, fin),
        )
        for source, gardes, rejetes in cur.fetchall():
            entres = int(gardes) + int(rejetes)
            if entres < MIN_ENTRES_TAUX:
                continue
            taux = int(rejetes) / entres
            resultats.append(
                Resultat(
                    "taux_rejet_source", source, round(taux, 3), SEUIL_TAUX_REJET,
                    taux <= SEUIL_TAUX_REJET, f"{int(rejetes)} rejetés sur {entres}",
                )
            )

        # 4. Fraîcheur par source (enregistrée, sans alerte : signalement)
        cur.execute(
            "SELECT source, max(publie_le) FROM articles_propres "
            "WHERE publie_le >= %s AND publie_le <= %s GROUP BY source ORDER BY source",
            (maintenant - timedelta(days=7), limite),
        )
        for source, dernier in cur.fetchall():
            age_h = (maintenant - dernier).total_seconds() / 3600
            resultats.append(
                Resultat(
                    "fraicheur_source", source, round(age_h, 1), SEUIL_FRAICHEUR_H,
                    age_h <= SEUIL_FRAICHEUR_H, "âge du dernier article gardé (heures)",
                    alerte=False,
                )
            )
    return resultats


def _deja_alerte(cur, resultat: Resultat, maintenant: datetime) -> bool:
    cur.execute(
        "SELECT 1 FROM controles_qualite WHERE nom = %s AND portee = %s "
        "AND NOT ok AND alerte_envoyee AND horodatage > %s LIMIT 1",
        (resultat.nom, resultat.portee, maintenant - FENETRE_ANTISPAM),
    )
    return cur.fetchone() is not None


def formater_message(resultats: list[Resultat]) -> str:
    lignes = ["**ALERTE qualité - La gazette**"]
    for r in resultats:
        valeur = int(r.valeur) if float(r.valeur).is_integer() else r.valeur
        ligne = f"- `{r.nom}` ({r.portee}) : {valeur} (seuil {r.seuil:g})"
        lignes.append(f"{ligne} - {r.detail}" if r.detail else ligne)
    return "\n".join(lignes)


def executer_controles(conn, maintenant: datetime | None = None, envoyer=envoyer_alerte) -> dict:
    """Vérifie, alerte si besoin (anti-spam), enregistre les résultats."""
    maintenant = maintenant or datetime.now(timezone.utc)
    resultats = verifier(conn, maintenant)
    echecs = [r for r in resultats if not r.ok and r.alerte]

    with conn.cursor() as cur:
        a_envoyer = [r for r in echecs if not _deja_alerte(cur, r, maintenant)]
        envoyee = bool(a_envoyer) and bool(envoyer(formater_message(a_envoyer)))
        notifies = {id(r) for r in a_envoyer} if envoyee else set()
        cur.executemany(
            "INSERT INTO controles_qualite "
            "(horodatage, nom, portee, valeur, seuil, ok, alerte_envoyee, detail) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
            [
                (maintenant, r.nom, r.portee, r.valeur, r.seuil, r.ok,
                 id(r) in notifies, r.detail or None)
                for r in resultats
            ],
        )
    conn.commit()

    bilan = {
        "evenement": "bilan_controles",
        "controles": len(resultats),
        "echecs": [f"{r.nom}:{r.portee}" for r in resultats if not r.ok],
        "alerte_envoyee": envoyee,
    }
    logger.info(json.dumps(bilan, ensure_ascii=False))
    return bilan


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    conn = ouvrir_connexion()
    try:
        bilan = executer_controles(conn)
    finally:
        conn.close()
    print(json.dumps(bilan, ensure_ascii=False))
    sys.exit(1 if any(not e.startswith("fraicheur_source") for e in bilan["echecs"]) else 0)


if __name__ == "__main__":
    main()
