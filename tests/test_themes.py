"""Tests du regroupement, du nommage et du traçage des runs (TD 5).

Articles inventés en cinq sujets ; un encodeur factice place chaque sujet dans sa propre
zone de l'espace, comme le ferait un vrai modèle. Les tests ``base`` demandent une base
PostgreSQL jetable (``GAZETTE_TEST_DATABASE_URL``, elle est vidée !).
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pytest

from gazette.embeddings import Article
from gazette.migrations import appliquer_migrations
from gazette.suivi_runs import SuiviMLflow, SuiviNul, SuiviTolerant, aplatir
from gazette.themes import (
    calculer_metriques,
    charger_config,
    doit_tourner,
    empreinte_entree,
    executer_run,
    nommer,
    regrouper,
)

URL_TEST = os.environ.get("GAZETTE_TEST_DATABASE_URL")
base = pytest.mark.skipif(not URL_TEST, reason="GAZETTE_TEST_DATABASE_URL absente")
MAINTENANT = datetime(2026, 10, 23, 6, 0, tzinfo=timezone.utc)
CONFIG = Path(__file__).resolve().parents[1] / "config" / "clustering.yaml"

SUJETS = {
    "rugby": ["rugby", "essai", "mêlée", "stade", "championnat"],
    "budget": ["budget", "assemblée", "députés", "impôts", "déficit"],
    "climat": ["climat", "inondations", "pluies", "vigilance", "crues"],
    "ukraine": ["ukraine", "kiev", "missiles", "front", "russie"],
    "cinema": ["cinéma", "film", "festival", "réalisatrice", "affiche"],
}


def corpus(par_sujet=12):
    """Titres inventés : chaque sujet a son vocabulaire propre."""
    textes, sujets = [], []
    for sujet, mots in SUJETS.items():
        for i in range(par_sujet):
            m = [mots[(i + k) % len(mots)] for k in range(3)]
            textes.append(f"{m[0].capitalize()} {m[1]} et {m[2]} numéro {i}")
            sujets.append(sujet)
    return textes, sujets


class EncodeurParSujet:
    """Un centre par sujet + un petit bruit déterministe : 5 groupes nets."""

    nom, version = "factice/sujets", "v1"

    def __init__(self):
        rng = np.random.default_rng(0)
        self.centres = {s: rng.normal(size=24) * 3 for s in SUJETS}

    def encoder(self, textes):
        lignes = []
        for texte in textes:
            sujet = next(s for s, mots in SUJETS.items() if any(m in texte.lower() for m in mots))
            graine = int(hashlib.sha256(texte.encode()).hexdigest()[:8], 16)
            v = self.centres[sujet] + np.random.default_rng(graine).normal(size=24) * 0.3
            lignes.append(v / np.linalg.norm(v))
        return np.asarray(lignes, dtype=np.float32)


# --- Sans base --------------------------------------------------------------------

def test_le_fichier_de_config_du_depot_est_valide():
    config = charger_config(CONFIG)
    assert config["donnees"]["fenetre_heures"] == 24
    assert config["regroupement"]["min_cluster_size"] >= 2


def test_nommer_garde_les_premiers_mots_sans_repetition():
    assert nommer(["budget", "budget état", "députés", "assemblée"]) == (
        "budget · députés · assemblée")
    assert nommer([]) == "(sans nom)"


def test_metriques():
    etiquettes = [0, 0, 0, 1, 1, 1, -1, -1]
    vecteurs = np.array([[1, 0]] * 3 + [[0, 1]] * 3 + [[1, 1]] * 2, dtype=float)
    m = calculer_metriques(etiquettes, vecteurs)
    assert m["nb_themes"] == 2
    assert m["taille_mediane"] == 3
    assert m["part_bruit"] == 0.25
    assert m["silhouette"] == pytest.approx(1.0)


def test_metriques_sans_theme_pas_de_silhouette():
    m = calculer_metriques([-1, -1, -1], np.eye(3))
    assert m["nb_themes"] == 0 and m["silhouette"] is None and m["part_bruit"] == 1.0


def test_empreinte_entree_stable_et_sensible():
    a = Article("x1", "S", "Titre", "Extrait", MAINTENANT)
    b = Article("x2", "S", "Autre", None, MAINTENANT)
    assert empreinte_entree([a, b], "m", "v1") == empreinte_entree([b, a], "m", "v1")
    assert empreinte_entree([a, b], "m", "v1") != empreinte_entree([a], "m", "v1")
    assert empreinte_entree([a, b], "m", "v1") != empreinte_entree([a, b], "m", "v2")


def test_regrouper_retrouve_les_sujets_et_les_nomme():
    textes, sujets = corpus()
    vecteurs = EncodeurParSujet().encoder(textes)
    etiquettes, themes = regrouper(textes, vecteurs, charger_config(CONFIG))

    assert len(themes) == 5
    for theme in themes:  # chaque thème ne contient qu'un sujet
        membres = {s for s, e in zip(sujets, etiquettes) if e == theme["theme"]}
        assert len(membres) == 1
        sujet = membres.pop()
        assert any(mot in theme["nom"] for mot in SUJETS[sujet])
        assert theme["taille"] == sum(1 for e in etiquettes if e == theme["theme"])


def test_regrouper_est_reproductible():
    textes, _ = corpus()
    vecteurs = EncodeurParSujet().encoder(textes)
    config = charger_config(CONFIG)
    assert regrouper(textes, vecteurs, config) == regrouper(textes, vecteurs, config)


def test_aplatir_les_parametres():
    assert aplatir({"a": {"b": 1, "c": {"d": 2}}, "e": 3}) == {"a.b": 1, "a.c.d": 2, "e": 3}


def test_une_panne_du_suivi_ne_casse_pas_le_run():
    class SuiviEnPanne(SuiviNul):
        actif = True

        def metriques(self, metriques):
            raise ConnectionError("serveur MLflow injoignable")

    suivi = SuiviTolerant(SuiviEnPanne())
    suivi.metriques({"x": 1})  # ne lève pas
    assert suivi.actif is False


# --- Avec base ----------------------------------------------------------------------

@pytest.fixture
def conn():
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(URL_TEST, autocommit=True) as connexion:
        connexion.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        appliquer_migrations(connexion)
        yield connexion


def inserer_corpus(conn, par_sujet=12):
    textes, _ = corpus(par_sujet)
    for i, titre in enumerate(textes):
        conn.execute(
            "INSERT INTO articles_propres (item_id, source, titre, lien, publie_le) "
            "VALUES (%s, 'Journal Test', %s, %s, %s)",
            (f"id{i:03d}", titre, f"https://exemple.test/{i}",
             MAINTENANT - timedelta(minutes=10 + i)),
        )
    return len(textes)


@base
def test_un_run_complet_ecrit_les_themes_et_se_trace(conn):
    n = inserer_corpus(conn)
    resume = executer_run(conn, MAINTENANT, EncodeurParSujet(), charger_config(CONFIG), SuiviNul())

    assert resume["statut"] == "ok" and resume["nb_themes"] == 5
    run = conn.execute(
        "SELECT statut, nb_articles, hash_entree, modele, modele_version, parametres, metriques "
        "FROM runs_themes WHERE run_id = %s", (resume["run_id"],)
    ).fetchone()
    assert run[0] == "ok" and run[1] == n and len(run[2]) == 64
    assert (run[3], run[4]) == ("factice/sujets", "v1")
    assert run[5]["regroupement"]["min_cluster_size"] == 5
    assert set(run[6]) >= {"nb_themes", "taille_mediane", "part_bruit", "silhouette"}

    du_jour = conn.execute("SELECT run_id, nom, taille FROM themes_du_jour").fetchall()
    assert len(du_jour) == 5 and {r[0] for r in du_jour} == {resume["run_id"]}
    rattaches = conn.execute(
        "SELECT count(*) FROM articles_themes WHERE run_id = %s", (resume["run_id"],)
    ).fetchone()[0]
    assert rattaches == sum(r[2] for r in du_jour)


@base
def test_deux_runs_sur_les_memes_donnees_donnent_les_memes_themes(conn):
    inserer_corpus(conn)
    config, encodeur = charger_config(CONFIG), EncodeurParSujet()
    r1 = executer_run(conn, MAINTENANT, encodeur, config, SuiviNul())
    r2 = executer_run(conn, MAINTENANT, encodeur, config, SuiviNul())
    assert r1["hash_entree"] == r2["hash_entree"]
    noms = [
        conn.execute("SELECT array_agg(nom ORDER BY nom) FROM themes WHERE run_id = %s",
                     (r,)).fetchone()[0]
        for r in (r1["run_id"], r2["run_id"])
    ]
    assert noms[0] == noms[1]
    assert r2["vecteurs_calcules"] == 0  # le second run lit tout dans le cache


@base
def test_trop_peu_articles(conn):
    inserer_corpus(conn, par_sujet=2)  # 10 articles < min_articles
    resume = executer_run(conn, MAINTENANT, EncodeurParSujet(), charger_config(CONFIG), SuiviNul())
    assert resume["statut"] == "trop_peu_articles"
    assert conn.execute("SELECT count(*) FROM themes").fetchone()[0] == 0


@base
def test_un_echec_est_trace(conn):
    inserer_corpus(conn)

    class EncodeurCasse(EncodeurParSujet):
        def encoder(self, textes):
            raise RuntimeError("modèle introuvable")

    with pytest.raises(RuntimeError):
        executer_run(conn, MAINTENANT, EncodeurCasse(), charger_config(CONFIG), SuiviNul())
    statut, erreur = conn.execute("SELECT statut, erreur FROM runs_themes").fetchone()
    assert statut == "echec" and "modèle introuvable" in erreur


@base
def test_intervalle_entre_deux_runs(conn):
    assert doit_tourner(conn, MAINTENANT, 60)
    inserer_corpus(conn)
    executer_run(conn, MAINTENANT, EncodeurParSujet(), charger_config(CONFIG), SuiviNul())
    fin = conn.execute("SELECT fin FROM runs_themes").fetchone()[0]
    assert not doit_tourner(conn, fin + timedelta(minutes=30), 60)
    assert doit_tourner(conn, fin + timedelta(minutes=61), 60)


@base
def test_le_run_est_trace_dans_mlflow(conn, tmp_path, monkeypatch):
    pytest.importorskip("mlflow")
    monkeypatch.setenv("MLFLOW_ALLOW_FILE_STORE", "true")  # en production : serveur MLflow
    import mlflow

    inserer_corpus(conn)
    uri = (tmp_path / "mlruns").as_uri()  # magasin fichier : pas de serveur dans les tests
    suivi = SuiviTolerant(SuiviMLflow(uri, experience="test"))
    resume = executer_run(conn, MAINTENANT, EncodeurParSujet(), charger_config(CONFIG), suivi)

    assert resume["mlflow_run_id"]
    run = mlflow.MlflowClient(uri).get_run(resume["mlflow_run_id"])
    assert run.data.params["regroupement.min_cluster_size"] == "5"
    assert run.data.metrics["nb_themes"] == 5
    assert run.data.tags["hash_entree"] == resume["hash_entree"]
    artefacts = {a.path for a in mlflow.MlflowClient(uri).list_artifacts(run.info.run_id)}
    assert {"config_clustering.yaml", "themes.json", "affectations.json"} <= artefacts
    lien = conn.execute("SELECT mlflow_run_id FROM runs_themes").fetchone()[0]
    assert lien == resume["mlflow_run_id"]
