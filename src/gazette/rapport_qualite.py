"""Rapport de qualité quotidien (TD 4).

``rapports/qualite-AAAA-MM-JJ.md``, recalculé à chaque passage à partir de la base
pour la journée UTC en cours. Doit permettre de repérer une règle trop gourmande.
Lançable sans Prefect : ``python -m gazette.rapport_qualite``.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from gazette.connexion import ouvrir_connexion
from gazette.regles_config import DESCRIPTIONS

logger = logging.getLogger("gazette.rapport_qualite")

SEUIL_REGLE_GOURMANDE = 0.8  # part d'une source rejetée par UNE règle
MIN_ENTRES_REGLE_GOURMANDE = 10
NB_TOP = 5
NB_EXEMPLES = 2


def bornes_jour(jour: date) -> tuple[datetime, datetime]:
    debut = datetime(jour.year, jour.month, jour.day, tzinfo=timezone.utc)
    return debut, debut + timedelta(days=1)


def dossier_rapports() -> Path:
    return Path(os.environ.get("GAZETTE_RAPPORTS_DIR", "rapports"))


def collecter_stats(conn, jour: date, maintenant: datetime | None = None) -> dict:
    """Chiffres du jour (UTC) lus dans articles_propres et rejets."""
    debut, fin = bornes_jour(jour)
    par_source: dict[str, dict[str, int]] = {}
    par_regle: dict[str, int] = {}
    par_source_regle: dict[tuple[str, str], int] = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT source, count(*) FROM articles_propres "
            "WHERE nettoye_le >= %s AND nettoye_le < %s GROUP BY source",
            (debut, fin),
        )
        for source, n in cur.fetchall():
            par_source.setdefault(source, {"gardes": 0, "rejetes": 0})["gardes"] = int(n)
        cur.execute(
            "SELECT source, regle, count(*) FROM rejets "
            "WHERE rejete_le >= %s AND rejete_le < %s GROUP BY source, regle",
            (debut, fin),
        )
        for source, regle, n in cur.fetchall():
            n = int(n)
            ligne = par_source.setdefault(source, {"gardes": 0, "rejetes": 0})
            ligne["rejetes"] += n
            par_regle[regle] = par_regle.get(regle, 0) + n
            par_source_regle[(source, regle)] = n

        top = sorted(par_regle.items(), key=lambda kv: (-kv[1], kv[0]))[:NB_TOP]
        top_rejets = []
        for regle, nombre in top:
            cur.execute(
                "SELECT source, titre FROM rejets WHERE regle = %s "
                "AND rejete_le >= %s AND rejete_le < %s "
                "ORDER BY rejete_le DESC, item_id LIMIT %s",
                (regle, debut, fin, NB_EXEMPLES),
            )
            exemples = [{"source": s, "titre": t or ""} for s, t in cur.fetchall()]
            top_rejets.append({"regle": regle, "nombre": nombre, "exemples": exemples})

    gourmandes = []
    for (source, regle), n in sorted(par_source_regle.items()):
        ligne = par_source[source]
        entres = ligne["gardes"] + ligne["rejetes"]
        if entres >= MIN_ENTRES_REGLE_GOURMANDE and n / entres >= SEUIL_REGLE_GOURMANDE:
            gourmandes.append(
                {"source": source, "regle": regle, "nombre": n, "entres": entres,
                 "taux": n / entres}
            )

    gardes = sum(v["gardes"] for v in par_source.values())
    rejetes = sum(v["rejetes"] for v in par_source.values())
    return {
        "jour": jour,
        "genere_le": maintenant or datetime.now(timezone.utc),
        "entres": gardes + rejetes,
        "gardes": gardes,
        "rejetes": rejetes,
        "par_regle": par_regle,
        "par_source": par_source,
        "top_rejets": top_rejets,
        "regles_gourmandes": gourmandes,
    }


def _cellule(texte: object, limite: int = 90) -> str:
    texte = str(texte).replace("|", "/").replace("\n", " ").strip()
    return texte if len(texte) <= limite else texte[: limite - 1] + "\u2026"


def _pourcent(partie: int, total: int) -> str:
    return f"{100 * partie / total:.0f} %" if total else "-"


def rendre_markdown(stats: dict) -> str:
    """Met en forme le rapport (fonction pure : testable sans base)."""
    s = stats
    lignes = [
        f"# Rapport de qualité - {s['jour'].isoformat()}",
        "",
        (
            f"Journée UTC du {s['jour'].isoformat()}, recalculé le "
            f"{s['genere_le'].strftime('%Y-%m-%d %H:%M')} UTC à chaque passage."
        ),
        "",
        "## Résumé",
        "",
        "| Entrés | Gardés | Rejetés | Taux de rejet |",
        "|---:|---:|---:|---:|",
        (
            f"| {s['entres']} | {s['gardes']} | {s['rejetes']} | "
            f"{_pourcent(s['rejetes'], s['entres'])} |"
        ),
        "",
        "## Rejets par règle",
        "",
    ]
    if s["par_regle"]:
        lignes.append("| Règle | Rejetés | Ce qu'elle écarte |")
        lignes.append("|---|---:|---|")
        for regle, n in sorted(s["par_regle"].items(), key=lambda kv: (-kv[1], kv[0])):
            lignes.append(f"| {regle} | {n} | {_cellule(DESCRIPTIONS.get(regle, ''), 100)} |")
    else:
        lignes.append("Aucun rejet sur la période.")

    lignes += ["", "## Par source", ""]
    if s["par_source"]:
        lignes.append("| Source | Entrés | Gardés | Rejetés | Taux de rejet |")
        lignes.append("|---|---:|---:|---:|---:|")
        for source, v in sorted(s["par_source"].items()):
            entres = v["gardes"] + v["rejetes"]
            lignes.append(
                f"| {_cellule(source, 40)} | {entres} | {v['gardes']} | {v['rejetes']} | "
                f"{_pourcent(v['rejetes'], entres)} |"
            )
    else:
        lignes.append("Aucun article traité sur la période.")

    lignes += ["", f"## Les {NB_TOP} rejets les plus fréquents", ""]
    if s["top_rejets"]:
        for position, rejet in enumerate(s["top_rejets"], start=1):
            lignes.append(f"{position}. **{rejet['regle']}** : {rejet['nombre']} rejetés")
            for exemple in rejet["exemples"]:
                lignes.append(
                    f"   - {_cellule(exemple['source'], 30)} : {_cellule(exemple['titre'])}"
                )
    else:
        lignes.append("Rien à signaler.")

    lignes += ["", "## Règles qui semblent trop gourmandes", ""]
    if s["regles_gourmandes"]:
        lignes.append(
            f"Une règle écarte au moins {int(SEUIL_REGLE_GOURMANDE * 100)} % des articles "
            "d'une source : vérifier les exemples ci-dessus et le motif dans "
            "`regles_config.py`."
        )
        lignes.append("")
        for g in s["regles_gourmandes"]:
            lignes.append(
                f"- {g['regle']} sur {_cellule(g['source'], 40)} : {g['nombre']} sur "
                f"{g['entres']} ({_pourcent(g['nombre'], g['entres'])})"
            )
    else:
        lignes.append("Aucune.")
    lignes.append("")
    return "\n".join(lignes)


def ecrire_rapport(
    conn,
    jour: date | None = None,
    dossier: Path | None = None,
    maintenant: datetime | None = None,
) -> Path:
    maintenant = maintenant or datetime.now(timezone.utc)
    jour = jour or maintenant.date()
    stats = collecter_stats(conn, jour, maintenant)
    dossier = Path(dossier or dossier_rapports())
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / f"qualite-{jour.isoformat()}.md"
    chemin.write_text(rendre_markdown(stats), encoding="utf-8")
    logger.info(
        json.dumps(
            {"evenement": "rapport_qualite", "fichier": str(chemin), "entres": stats["entres"],
             "gardes": stats["gardes"], "rejetes": stats["rejetes"]},
            ensure_ascii=False,
        )
    )
    return chemin


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    conn = ouvrir_connexion()
    try:
        chemin = ecrire_rapport(conn)
    finally:
        conn.close()
    print(chemin)


if __name__ == "__main__":
    main()
