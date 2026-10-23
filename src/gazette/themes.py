"""Regroupement des articles en thèmes, nommage et traçage du run (TD 5).

Chaîne BERTopic, avec les vecteurs calculés (et mis en cache) par ``gazette.embeddings`` :
UMAP (réduction) -> HDBSCAN (regroupement, nombre de thèmes libre, bruit mis à part)
-> c-TF-IDF (mots les plus discriminants de chaque thème = son nom).

Un run :
1. lit les articles propres de la fenêtre (24 h) et calcule l'empreinte de l'entrée ;
2. ouvre une ligne dans ``runs_themes`` (statut en_cours) et un run MLflow ;
3. vectorise (cache), regroupe, nomme, calcule les métriques ;
4. écrit ``themes`` et ``articles_themes`` puis ferme le run (ok, ou echec avec l'erreur).

Tous les paramètres viennent de ``config/clustering.yaml``. Lançable sans Prefect :
``python -m gazette.themes`` (respecte l'intervalle) ou ``python -m gazette.themes --forcer``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import statistics
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Sequence

import numpy as np
import yaml

from gazette.embeddings import (
    Article,
    Encodeur,
    EncodeurSentenceTransformers,
    lire_articles,
    texte_article,
    vectoriser,
)
from gazette.migrations import appliquer_migrations
from gazette.suivi_runs import SuiviNul, suivi_depuis_environnement

logger = logging.getLogger("gazette.themes")

CHEMIN_CONFIG_DEFAUT = Path(__file__).resolve().parents[2] / "config" / "clustering.yaml"
VERROU = 4_208_005  # deux runs de thèmes ne tournent jamais en même temps
BRUIT = -1

# Mots vides du français (et quelques mots de presse sans valeur de thème).
# Ils sont retirés AVANT le calcul des mots-clés, pas avant la vectorisation.
MOTS_VIDES = sorted(set("""
a à afin ai aie aient ainsi alors après as au aucun aucune aujourd auprès aussi autre
autres aux avaient avait avant avec avez avoir avons ayant c ça car ce ceci cela celle
celles celui cent ces cet cette ceux chaque chez ci comme comment contre d dans de des
deux devant doit donc dont du durant e elle elles en encore entre es est et été être eu
eux fait faire fois font hors i il ils j je jusqu l la là le les leur leurs lors lui m
ma mais me même mêmes mes moi moins mon n ne ni non nos notre nous on ont ou où par
parce pas peu peut plus plusieurs pour pourquoi qu quand que quel quelle quelles quels
qui quoi s sa sans se selon ses si sien sont sous sur t ta te tes toi ton tous tout
toute toutes très tu un une va vers via vos votre vous y
an ans année années jour jours mois semaine heure heures hier demain
selon après cette entre dont depuis lundi mardi mercredi jeudi vendredi samedi dimanche
article lire aussi vidéo photos direct info infos actualité
""".split()))


# --- Configuration ------------------------------------------------------------

def chemin_config() -> Path:
    return Path(os.environ.get("GAZETTE_CONFIG_CLUSTERING", CHEMIN_CONFIG_DEFAUT))


def charger_config(chemin: Path | None = None) -> dict:
    """Lit config/clustering.yaml et vérifie que les sections attendues sont là."""
    chemin = Path(chemin or chemin_config())
    config = yaml.safe_load(chemin.read_text(encoding="utf-8"))
    attendues = {"donnees", "embeddings", "reduction", "regroupement", "nommage", "graine"}
    manquantes = attendues - set(config)
    if manquantes:
        raise ValueError(f"{chemin} : sections manquantes {sorted(manquantes)}")
    return config


def empreinte_config(config: dict) -> str:
    texte = json.dumps(config, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


# --- Fonctions pures -------------------------------------------------------------

def empreinte_entree(articles: Sequence[Article], modele: str, version: str) -> str:
    """SHA-256 de ce qui entre dans le modèle : mêmes articles + même modèle = même empreinte."""
    h = hashlib.sha256(f"{modele}@{version}\n".encode("utf-8"))
    for a in sorted(articles, key=lambda x: x.item_id):
        h.update(f"{a.item_id}\t{texte_article(a.titre, a.extrait)}\n".encode("utf-8"))
    return h.hexdigest()


def nommer(mots_cles: Sequence[str], nombre: int = 3) -> str:
    """Nom lisible d'un thème : ses premiers mots-clés, sans répéter un mot déjà inclus."""
    retenus: list[str] = []
    for mot in mots_cles:
        if not mot or any(mot in r or r in mot for r in retenus):
            continue
        retenus.append(mot)
        if len(retenus) == nombre:
            break
    return " · ".join(retenus) if retenus else "(sans nom)"


def calculer_metriques(etiquettes: Sequence[int], vecteurs: np.ndarray) -> dict:
    """Nombre de thèmes, taille médiane, part de bruit, silhouette (hors bruit, cosinus)."""
    etiquettes = np.asarray(etiquettes)
    n = len(etiquettes)
    themes = [t for t in set(etiquettes.tolist()) if t != BRUIT]
    tailles = [int((etiquettes == t).sum()) for t in themes]
    garde = etiquettes != BRUIT
    silhouette = None
    if len(themes) >= 2 and garde.sum() > len(themes):
        from sklearn.metrics import silhouette_score

        silhouette = round(
            float(silhouette_score(vecteurs[garde], etiquettes[garde], metric="cosine")), 4
        )
    return {
        "nb_articles": n,
        "nb_themes": len(themes),
        "taille_mediane": float(statistics.median(tailles)) if tailles else 0.0,
        "taille_max": max(tailles) if tailles else 0,
        "part_bruit": round(float((~garde).sum()) / n, 4) if n else 0.0,
        "silhouette": silhouette,
    }


# --- Regroupement ----------------------------------------------------------------

def regrouper(textes: Sequence[str], vecteurs: np.ndarray, config: dict):
    """BERTopic sur des vecteurs déjà calculés. Renvoie (étiquettes, thèmes)."""
    from bertopic import BERTopic
    from hdbscan import HDBSCAN
    from sklearn.feature_extraction.text import CountVectorizer
    from umap import UMAP

    graine = int(config["graine"])
    np.random.seed(graine)
    red, reg, nom = config["reduction"], config["regroupement"], config["nommage"]

    n = len(textes)
    umap = UMAP(
        n_neighbors=min(int(red["n_neighbors"]), n - 1),
        n_components=int(red["n_components"]),
        min_dist=float(red["min_dist"]),
        metric=red["metric"],
        random_state=graine,
    )
    hdbscan = HDBSCAN(
        min_cluster_size=int(reg["min_cluster_size"]),
        min_samples=int(reg["min_samples"]),
        metric=reg["metric"],
        cluster_selection_method=reg["cluster_selection_method"],
        prediction_data=True,
    )
    vectoriseur = CountVectorizer(
        stop_words=MOTS_VIDES,
        ngram_range=(int(nom["ngram_min"]), int(nom["ngram_max"])),
        min_df=int(nom["min_df"]),
        token_pattern=r"(?u)\b[^\W\d_]{2,}\b",  # mots d'au moins 2 lettres, sans chiffres
    )
    modele = BERTopic(
        # Pas "english" : BERTopic retirerait alors tous les accents avant le nommage
        # (« mêlée » deviendrait « mle »). Les vecteurs sont fournis, la langue ne sert qu'ici.
        language="french",
        embedding_model=None,
        umap_model=umap,
        hdbscan_model=hdbscan,
        vectorizer_model=vectoriseur,
        top_n_words=int(nom["mots_par_theme"]),
        calculate_probabilities=False,
        verbose=False,
    )
    etiquettes, _ = modele.fit_transform(list(textes), embeddings=vecteurs)

    themes = []
    for numero in sorted(set(etiquettes) - {BRUIT}):
        mots = [mot for mot, _ in (modele.get_topic(numero) or []) if mot]
        themes.append({
            "theme": int(numero),
            "nom": nommer(mots, int(nom["mots_dans_le_nom"])),
            "mots_cles": mots,
            "taille": int(sum(1 for e in etiquettes if e == numero)),
        })
    return [int(e) for e in etiquettes], themes


# --- Le run ---------------------------------------------------------------------

def dernier_run_ok(conn) -> datetime | None:
    ligne = conn.execute(
        "SELECT max(fin) FROM runs_themes WHERE statut IN ('ok', 'trop_peu_articles')"
    ).fetchone()
    return ligne[0] if ligne else None


def doit_tourner(conn, maintenant: datetime, intervalle_min: int) -> bool:
    dernier = dernier_run_ok(conn)
    return dernier is None or maintenant - dernier >= timedelta(minutes=intervalle_min)


def _journaliser(evenement: dict, niveau: int = logging.INFO) -> None:
    logger.log(niveau, json.dumps(evenement, ensure_ascii=False, default=str))


def executer_run(
    conn,
    maintenant: datetime | None = None,
    encodeur: Encodeur | None = None,
    config: dict | None = None,
    suivi: SuiviNul | None = None,
) -> dict:
    """Un run complet. ``conn`` doit être en autocommit. Renvoie le résumé du run."""
    maintenant = maintenant or datetime.now(timezone.utc)
    config = config or charger_config()
    emb = config["embeddings"]
    encodeur = encodeur or EncodeurSentenceTransformers(
        emb["modele"], emb["revision"], int(emb["taille_lot"])
    )
    suivi = suivi or suivi_depuis_environnement()
    debut_chrono = time.monotonic()

    heures = int(config["donnees"]["fenetre_heures"])
    articles = lire_articles(conn, maintenant, heures)
    version = encodeur.version
    run_id = f"{maintenant:%Y%m%dT%H%M%SZ}-{os.urandom(3).hex()}"
    hash_entree = empreinte_entree(articles, encodeur.nom, version)
    hash_config = empreinte_config(config)

    conn.execute(
        "INSERT INTO runs_themes (run_id, statut, fenetre_debut, fenetre_fin, nb_articles, "
        "hash_entree, modele, modele_version, hash_config, parametres) "
        "VALUES (%s, 'en_cours', %s, %s, %s, %s, %s, %s, %s, %s)",
        (run_id, maintenant - timedelta(hours=heures), maintenant, len(articles), hash_entree,
         encodeur.nom, version, hash_config, json.dumps(config, ensure_ascii=False)),
    )
    suivi.demarrer(run_id, {
        "run_id": run_id, "hash_entree": hash_entree, "hash_config": hash_config,
        "modele": encodeur.nom, "modele_version": version,
        "code_version": os.environ.get("GAZETTE_VERSION", "dev"),
    })
    suivi.parametres({
        **config,
        "fenetre": {"debut": (maintenant - timedelta(hours=heures)).isoformat(),
                    "fin": maintenant.isoformat()},
        "modele_version": version,
    })
    suivi.artefact_texte(yaml.safe_dump(config, allow_unicode=True, sort_keys=False),
                         "config_clustering.yaml")

    resume = {"run_id": run_id, "nb_articles": len(articles), "hash_entree": hash_entree}
    try:
        if len(articles) < int(config["donnees"]["min_articles"]):
            statut, metriques, themes, etiquettes = "trop_peu_articles", {
                "nb_articles": len(articles)}, [], []
        else:
            vecteurs, bilan_cache = vectoriser(conn, articles, encodeur)
            textes = [texte_article(a.titre, a.extrait) for a in articles]
            etiquettes, themes = regrouper(textes, vecteurs, config)
            metriques = {**calculer_metriques(etiquettes, vecteurs),
                         "vecteurs_en_cache": bilan_cache["en_cache"],
                         "vecteurs_calcules": bilan_cache["calcules"]}
            statut = "ok"

        metriques["duree_s"] = round(time.monotonic() - debut_chrono, 2)
        affectations = [
            {"item_id": a.item_id, "source": a.source, "theme": e}
            for a, e in zip(articles, etiquettes)
        ]
        with conn.transaction():
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO themes (run_id, theme, nom, mots_cles, taille) "
                    "VALUES (%s, %s, %s, %s, %s)",
                    [(run_id, t["theme"], t["nom"], t["mots_cles"], t["taille"])
                     for t in themes],
                )
                cur.executemany(
                    "INSERT INTO articles_themes (run_id, theme, item_id) VALUES (%s, %s, %s)",
                    [(run_id, x["theme"], x["item_id"]) for x in affectations
                     if x["theme"] != BRUIT],
                )
                cur.execute(
                    "UPDATE runs_themes SET statut = %s, fin = now(), metriques = %s, "
                    "mlflow_run_id = %s WHERE run_id = %s",
                    (statut, json.dumps(metriques), suivi.mlflow_run_id, run_id),
                )
        suivi.metriques(metriques)
        suivi.artefact_json(themes, "themes.json")
        suivi.artefact_json(affectations, "affectations.json")
        suivi.terminer(statut)
        resume.update(statut=statut, mlflow_run_id=suivi.mlflow_run_id, **metriques)
        _journaliser({"evenement": "run_themes", **resume})
        return resume
    except Exception as erreur:
        message = f"{type(erreur).__name__}: {erreur}"[:1000]
        conn.execute(
            "UPDATE runs_themes SET statut = 'echec', fin = now(), erreur = %s, "
            "mlflow_run_id = %s WHERE run_id = %s",
            (message, suivi.mlflow_run_id, run_id),
        )
        suivi.terminer("echec")
        _journaliser({"evenement": "run_themes", **resume, "statut": "echec",
                      "erreur": message}, logging.ERROR)
        raise


def etape_themes(forcer: bool = False, maintenant: datetime | None = None) -> dict:
    """Point d'entrée du pipeline : un run si le dernier date de plus de l'intervalle."""
    from gazette.connexion import ouvrir_connexion

    maintenant = maintenant or datetime.now(timezone.utc)
    config = charger_config()
    intervalle = int(config.get("planification", {}).get("intervalle_min", 60))
    conn = ouvrir_connexion()
    conn.autocommit = True
    appliquer_migrations(conn)  # base neuve : crée les tables avant de les lire
    try:
        conn.execute("SELECT pg_advisory_lock(%s)", (VERROU,))
        try:
            if not forcer and not doit_tourner(conn, maintenant, intervalle):
                return {"statut": "pas_encore", "intervalle_min": intervalle}
            return executer_run(conn, maintenant, config=config)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (VERROU,))
    finally:
        conn.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="Thèmes des dernières 24 h (TD 5)")
    parser.add_argument("--forcer", action="store_true",
                        help="lancer un run même si l'intervalle n'est pas écoulé")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    resume = etape_themes(forcer=args.forcer)
    print(json.dumps(resume, ensure_ascii=False, default=str, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
