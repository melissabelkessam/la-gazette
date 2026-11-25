"""Nettoyage : du brut vers articles_propres et rejets (TD 4).

Lecture incrémentale : seuls les fichiers bruts jamais traités sont lus, donc le
nettoyage est rejouable sans doublon (clé unique ``item_id`` + ON CONFLICT).
Lançable sans Prefect : ``python -m gazette.nettoyage``.
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from gazette.connexion import ouvrir_connexion
from gazette.doublons import IndexDoublons, charger_index
from gazette.normalisation import normaliser_article
from gazette.regles import appliquer_regles
from gazette.regles_config import FENETRE_DOUBLONS_H

logger = logging.getLogger("gazette.nettoyage")

SQL_PROPRE = (
    "INSERT INTO articles_propres "
    "(item_id, source, titre, extrait, lien, rubrique, publie_le, date_estimee, "
    "collecte_le) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) "
    "ON CONFLICT (item_id) DO NOTHING"
)
SQL_REJET = (
    "INSERT INTO rejets (item_id, source, titre, lien, regle, detail, doublon_de) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s) ON CONFLICT (item_id) DO NOTHING"
)


def dossier_brut() -> Path:
    """Dossier des articles bruts.

    ``GAZETTE_DOSSIER_BRUT`` (la même variable que le collecteur, définie dans
    docker-compose.yml) ; à défaut ``GAZETTE_DATA_DIR``/articles_bruts, puis data/.
    """
    explicite = os.environ.get("GAZETTE_DOSSIER_BRUT")
    if explicite:
        return Path(explicite)
    return Path(os.environ.get("GAZETTE_DATA_DIR", "data")) / "articles_bruts"


def journaliser(evenement: dict, niveau: int = logging.INFO) -> None:
    logger.log(niveau, json.dumps(evenement, ensure_ascii=False, default=str))


def lire_bruts(dossier: Path, deja_traites: set[str]) -> tuple[list[tuple[str, dict]], int]:
    """Lit les JSON bruts pas encore traités. Renvoie (liste, nombre d'illisibles)."""
    bruts: list[tuple[str, dict]] = []
    illisibles = 0
    for chemin in sorted(Path(dossier).glob("*/*.json")):
        if chemin.stem in deja_traites:
            continue
        try:
            brut = json.loads(chemin.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            brut = None
        if not isinstance(brut, dict):
            illisibles += 1
            journaliser({"evenement": "brut_illisible", "fichier": str(chemin)}, logging.WARNING)
            continue
        bruts.append((chemin.stem, brut))
    return bruts, illisibles


def traiter(
    bruts: list[tuple[str, dict]],
    index: IndexDoublons,
    maintenant: datetime | None = None,
) -> tuple[list[dict], list[dict]]:
    """Normalise, applique les règles puis les doublons. Renvoie (propres, rejets)."""
    maintenant = maintenant or datetime.now(timezone.utc)
    articles = [
        normaliser_article(brut, item_id=item_id, maintenant=maintenant)
        for item_id, brut in bruts
    ]
    # Du plus ancien au plus récent : on garde le plus ancien en cas de doublon.
    articles.sort(key=lambda a: (a["publie_le"], a["item_id"]))

    propres: list[dict] = []
    rejets: list[dict] = []
    for article in articles:
        regle, detail = appliquer_regles(article, maintenant)
        doublon_de = None
        if regle is None:
            doublon = index.chercher(article["titre_normalise"], article["lien"])
            if doublon is not None:
                regle, doublon_de, detail = doublon
        if regle is None:
            index.ajouter(article["item_id"], article["titre_normalise"], article["lien"])
            propres.append(article)
        else:
            rejets.append(
                {
                    "item_id": article["item_id"],
                    "source": article["source"],
                    "titre": article["titre"],
                    "lien": article["lien"],
                    "regle": regle,
                    "detail": detail,
                    "doublon_de": doublon_de,
                }
            )
    return propres, rejets


def identifiants_deja_traites(cur) -> set[str]:
    cur.execute("SELECT item_id FROM articles_propres UNION SELECT item_id FROM rejets")
    return {ligne[0] for ligne in cur.fetchall()}


def nettoyer(conn, dossier: Path | None = None, maintenant: datetime | None = None) -> dict:
    """Un passage de nettoyage. Renvoie le bilan (aussi écrit dans les logs)."""
    maintenant = maintenant or datetime.now(timezone.utc)
    debut = time.monotonic()
    with conn.cursor() as cur:
        deja = identifiants_deja_traites(cur)
        bruts, illisibles = lire_bruts(dossier or dossier_brut(), deja)
        index = charger_index(cur, maintenant - timedelta(hours=FENETRE_DOUBLONS_H))
        propres, rejets = traiter(bruts, index, maintenant)
        if propres:
            cur.executemany(
                SQL_PROPRE,
                [
                    (
                        a["item_id"], a["source"], a["titre"], a["extrait"], a["lien"],
                        a["rubrique"], a["publie_le"], a["date_estimee"], a["collecte_le"],
                    )
                    for a in propres
                ],
            )
        if rejets:
            cur.executemany(
                SQL_REJET,
                [
                    (
                        r["item_id"], r["source"], r["titre"], r["lien"], r["regle"],
                        r["detail"], r["doublon_de"],
                    )
                    for r in rejets
                ],
            )
    conn.commit()

    par_regle: dict[str, int] = {}
    for rejet in rejets:
        par_regle[rejet["regle"]] = par_regle.get(rejet["regle"], 0) + 1
    bilan = {
        "evenement": "bilan_nettoyage",
        "entres": len(bruts),
        "gardes": len(propres),
        "rejetes": len(rejets),
        "par_regle": par_regle,
        "illisibles": illisibles,
        "duree_ms": int((time.monotonic() - debut) * 1000),
    }
    journaliser(bilan)
    return bilan


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    conn = ouvrir_connexion()
    try:
        bilan = nettoyer(conn)
    finally:
        conn.close()
    print(json.dumps(bilan, ensure_ascii=False))


if __name__ == "__main__":
    main()