"""Évaluation automatique d'un run de regroupement (TD 6).

On juge un regroupement sans vérité terrain, à partir de ses métriques :

- des SEUILS durs (``config/evaluation.yaml``) : un run qui en franchit un est
  « recalé » — ses thèmes ne sont PAS publiés en base ;
- une règle de DÉRIVE : si un seuil « mou » est franchi plusieurs runs OK de suite,
  le run est publié mais marqué « revue » (l'équipe doit regarder) ;
- une RELECTURE humaine d'un échantillon, enregistrée à part (table ``relectures``).

Le cœur du module est PUR : il reçoit des métriques, il rend un verdict, il ne touche
pas à la base. ``themes.py`` l'appelle entre le regroupement et l'écriture des thèmes.
La lecture des runs précédents (pour la dérive) et la relecture passent par de petites
fonctions à part, clairement marquées « base ».
"""

from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path
from typing import Sequence

import yaml

CHEMIN_CONFIG_DEFAUT = Path(__file__).resolve().parents[2] / "config" / "evaluation.yaml"

VERDICT_OK = "ok"
VERDICT_REVUE = "revue"
VERDICT_RECALE = "recale"


# --- Configuration ------------------------------------------------------------

def chemin_config() -> Path:
    return Path(os.environ.get("GAZETTE_CONFIG_EVALUATION", CHEMIN_CONFIG_DEFAUT))


def charger_config(chemin: Path | None = None) -> dict:
    """Lit config/evaluation.yaml et vérifie que les sections attendues sont là."""
    chemin = Path(chemin or chemin_config())
    config = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    for section in ("seuils", "echantillon", "derive"):
        if section not in config:
            raise ValueError(f"{chemin} : section manquante '{section}'")
    return config


# --- Fonctions pures : les seuils durs ----------------------------------------

def part_theme_geant(metriques: dict) -> float:
    """Part des articles dans le plus gros thème (0 à 1). 0 si aucun article."""
    n = metriques.get("nb_articles") or 0
    return (metriques.get("taille_max", 0) / n) if n else 0.0


def appliquer_seuils(metriques: dict, seuils: dict) -> tuple[str, list[dict]]:
    """Compare les métriques aux garde-fous durs.

    Renvoie (verdict, franchissements) : verdict vaut 'recale' dès qu'un seuil est
    franchi, sinon 'ok'. Chaque franchissement dit le seuil, l'attendu et l'obtenu.
    """
    francs: list[dict] = []

    nb_themes = metriques.get("nb_themes", 0)
    if nb_themes < seuils["nb_themes_min"]:
        francs.append({"seuil": "nb_themes_min", "sens": ">=",
                       "attendu": seuils["nb_themes_min"], "obtenu": nb_themes})

    part_bruit = metriques.get("part_bruit", 0.0)
    if part_bruit > seuils["part_bruit_max"]:
        francs.append({"seuil": "part_bruit_max", "sens": "<=",
                       "attendu": seuils["part_bruit_max"], "obtenu": part_bruit})

    geant = part_theme_geant(metriques)
    if geant > seuils["theme_geant_max"]:
        francs.append({"seuil": "theme_geant_max", "sens": "<=",
                       "attendu": seuils["theme_geant_max"], "obtenu": round(geant, 4)})

    silhouette = metriques.get("silhouette")
    if silhouette is not None and silhouette < seuils["silhouette_min"]:
        francs.append({"seuil": "silhouette_min", "sens": ">=",
                       "attendu": seuils["silhouette_min"], "obtenu": silhouette})

    return (VERDICT_RECALE if francs else VERDICT_OK), francs


# --- Fonctions pures : la dérive ----------------------------------------------

def detecter_derive(metriques_actuel: dict, historique: Sequence[dict],
                    derive: dict) -> tuple[bool, list[dict]]:
    """Dérive si un seuil « mou » est franchi sur ``fenetre_runs`` runs OK de suite.

    ``historique`` = métriques des runs OK précédents, du plus récent au plus ancien.
    La fenêtre = [run actuel] + historique, tronquée à ``fenetre_runs``. S'il n'y a
    pas encore assez de runs, pas de dérive. Renvoie (derive?, raisons).
    """
    fenetre = int(derive["fenetre_runs"])
    serie = ([metriques_actuel] + list(historique))[:fenetre]
    if len(serie) < fenetre:
        return False, []

    raisons: list[dict] = []
    seuil_bruit = derive["part_bruit_surveillee"]
    if all((m.get("part_bruit", 0.0) > seuil_bruit) for m in serie):
        raisons.append({"regle": "part_bruit_surveillee", "seuil": seuil_bruit,
                        "runs_consecutifs": fenetre})

    seuil_silh = derive["silhouette_surveillee"]
    silhs = [m.get("silhouette") for m in serie]
    if all(s is not None and s < seuil_silh for s in silhs):
        raisons.append({"regle": "silhouette_surveillee", "seuil": seuil_silh,
                        "runs_consecutifs": fenetre})

    return bool(raisons), raisons


def verdict_final(verdict_seuils: str, derive_detectee: bool) -> str:
    """Un recalage l'emporte sur tout ; sinon une dérive donne 'revue' ; sinon 'ok'."""
    if verdict_seuils == VERDICT_RECALE:
        return VERDICT_RECALE
    if derive_detectee:
        return VERDICT_REVUE
    return VERDICT_OK


def evaluer(metriques: dict, historique: Sequence[dict], config: dict) -> dict:
    """Évaluation complète d'un run, à partir de ses métriques et de l'historique.

    Renvoie un dict prêt à enregistrer : verdict, publie (bool), et le détail
    (franchissements de seuils, dérive et ses raisons).
    """
    verdict_s, francs = appliquer_seuils(metriques, config["seuils"])
    derive_ok, raisons = detecter_derive(metriques, historique, config["derive"])
    verdict = verdict_final(verdict_s, derive_ok)
    return {
        "verdict": verdict,
        "publie": verdict != VERDICT_RECALE,
        "derive": derive_ok,
        "seuils": config["seuils"],
        "details": {"franchissements": francs, "raisons_derive": raisons},
    }


# --- Relecture : tirer l'échantillon (pur) ------------------------------------

def tirer_echantillon(affectations: Sequence[dict], taille: int,
                      graine: int = 0) -> list[dict]:
    """Tire au hasard ``taille`` articles parmi ceux rattachés à un thème (hors bruit).

    ``affectations`` = [{'item_id', 'theme', ...}]. Tirage reproductible (graine).
    """
    candidats = [a for a in affectations if a.get("theme", -1) != -1]
    rng = random.Random(graine)
    rng.shuffle(candidats)
    return candidats[:taille]


# --- Base : historique des runs et enregistrement -----------------------------

def metriques_runs_ok_precedents(conn, avant_fin, limite: int) -> list[dict]:
    """Métriques des derniers runs publiés (statut 'ok') avant ``avant_fin``, récent -> ancien."""
    lignes = conn.execute(
        "SELECT metriques FROM runs_themes "
        "WHERE statut = 'ok' AND fin IS NOT NULL AND fin < %s "
        "ORDER BY fin DESC LIMIT %s",
        (avant_fin, limite),
    ).fetchall()
    return [ligne[0] for ligne in lignes if ligne[0]]


def enregistrer_evaluation(conn, run_id: str, resultat: dict) -> None:
    """Écrit le verdict dans evaluations_themes (une ligne par run)."""
    conn.execute(
        "INSERT INTO evaluations_themes (run_id, verdict, publie, derive, seuils, details) "
        "VALUES (%s, %s, %s, %s, %s, %s) "
        "ON CONFLICT (run_id) DO UPDATE SET verdict = EXCLUDED.verdict, "
        "publie = EXCLUDED.publie, derive = EXCLUDED.derive, seuils = EXCLUDED.seuils, "
        "details = EXCLUDED.details, evalue_le = now()",
        (run_id, resultat["verdict"], resultat["publie"], resultat["derive"],
         json.dumps(resultat["seuils"]), json.dumps(resultat["details"], ensure_ascii=False)),
    )


def enregistrer_relecture(conn, run_id: str, notes: Sequence[dict], par_qui: str) -> dict:
    """Écrit les notes de relecture et renvoie le bilan (part correcte)."""
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO relectures (run_id, item_id, theme, correct, par_qui) "
            "VALUES (%s, %s, %s, %s, %s)",
            [(run_id, n["item_id"], n["theme"], bool(n["correct"]), par_qui) for n in notes],
        )
    corrects = sum(1 for n in notes if n["correct"])
    total = len(notes)
    return {"corrects": corrects, "total": total,
            "part_correcte": round(corrects / total, 3) if total else 0.0}


# --- Relecture en ligne de commande -------------------------------------------

def _relire_interactif(run_id: str, par_qui: str) -> int:
    """python -m gazette.evaluation --relire <run_id> : relecture à la main d'un échantillon."""
    from gazette.connexion import ouvrir_connexion

    config = charger_config()
    conn = ouvrir_connexion()
    conn.autocommit = True
    try:
        affectations = conn.execute(
            "SELECT at.item_id, at.theme, ap.titre, t.nom "
            "FROM articles_themes at "
            "JOIN articles_propres ap ON ap.item_id = at.item_id "
            "JOIN themes t ON t.run_id = at.run_id AND t.theme = at.theme "
            "WHERE at.run_id = %s",
            (run_id,),
        ).fetchall()
        if not affectations:
            print(f"Aucun article rattaché pour le run {run_id}.")
            return 1
        echantillon = tirer_echantillon(
            [{"item_id": i, "theme": t, "titre": ti, "nom": n} for i, t, ti, n in affectations],
            int(config["echantillon"]["taille"]), graine=hash(run_id) & 0xFFFF,
        )
        print(f"\nRelecture de {len(echantillon)} articles du run {run_id}.")
        print("Pour chacun : l'article est-il bien dans ce thème ? (o = oui, n = non)\n")
        notes = []
        for i, a in enumerate(echantillon, 1):
            print(f"[{i}/{len(echantillon)}] Thème « {a['nom']} »\n    {a['titre']}")
            rep = input("    bien placé ? [o/n] ").strip().lower()
            notes.append({"item_id": a["item_id"], "theme": a["theme"],
                          "correct": rep.startswith("o")})
        bilan = enregistrer_relecture(conn, run_id, notes, par_qui)
        seuil = float(config["echantillon"]["part_correcte_min"])
        verdict = "OK" if bilan["part_correcte"] >= seuil else "SOUS LE SEUIL"
        print(f"\nRésultat : {bilan['corrects']}/{bilan['total']} bien placés "
              f"({bilan['part_correcte']:.0%}) — {verdict} (seuil {seuil:.0%}).")
        return 0
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Évaluation et relecture d'un run (TD 6)")
    parser.add_argument("--relire", metavar="RUN_ID", help="relecture humaine d'un échantillon")
    parser.add_argument("--par", default=os.environ.get("USER", "inconnu"),
                        help="qui relit (pour la trace)")
    args = parser.parse_args()
    if args.relire:
        return _relire_interactif(args.relire, args.par)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())