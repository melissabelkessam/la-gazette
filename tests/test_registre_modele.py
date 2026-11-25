"""Tests du registre de versions du modèle (TD 6).

Demandent une base PostgreSQL jetable (``GAZETTE_TEST_DATABASE_URL``, elle est vidée !),
comme les autres tests « base ». Ils tournent dans la CI.
"""

from __future__ import annotations

import os

import psycopg
import pytest

from gazette import registre_modele as R
from gazette.migrations import appliquer_migrations

URL_TEST = os.environ.get("GAZETTE_TEST_DATABASE_URL")
base = pytest.mark.skipif(not URL_TEST, reason="GAZETTE_TEST_DATABASE_URL absente")

CFG_V1 = {"regroupement": {"min_cluster_size": 5}, "graine": 42}
CFG_V2 = {"regroupement": {"min_cluster_size": 8}, "graine": 42}


@pytest.fixture
def conn():
    with psycopg.connect(URL_TEST, autocommit=True) as connexion:
        connexion.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        appliquer_migrations(connexion)
        yield connexion


def inserer_run(conn, run_id="run-1"):
    conn.execute(
        "INSERT INTO runs_themes (run_id, statut, fenetre_debut, fenetre_fin, nb_articles, "
        "hash_entree, modele, modele_version, hash_config, parametres) "
        "VALUES (%s, 'ok', now(), now(), 40, 'h', 'm', 'v1', 'hc', '{}')",
        (run_id,),
    )
    return run_id


@base
def test_bootstrap_cree_v1_production(conn):
    p = R.config_en_service(conn, CFG_V1, par_qui="amelia")
    assert p == CFG_V1
    service = R.version_en_service(conn)
    assert service["version"] == "v1" and service["par_qui"] == "amelia"


@base
def test_config_en_service_ne_recree_pas(conn):
    R.config_en_service(conn, CFG_V1)
    R.config_en_service(conn, CFG_V1)
    assert conn.execute("SELECT count(*) FROM versions_modele").fetchone()[0] == 1


@base
def test_enregistrer_sans_doublon(conn):
    R.config_en_service(conn, CFG_V1)
    inserer_run(conn, "run-xyz")
    v = R.enregistrer_version(conn, CFG_V2, run_id="run-xyz", par_qui="amelia")
    assert v == "v2"
    assert R.enregistrer_version(conn, CFG_V2) == "v2"  # même empreinte -> pas de doublon
    assert conn.execute("SELECT count(*) FROM versions_modele").fetchone()[0] == 2


@base
def test_promotion_bascule_la_production(conn):
    R.config_en_service(conn, CFG_V1)
    R.enregistrer_version(conn, CFG_V2)
    R.promouvoir(conn, "v2", "jason")
    assert R.version_en_service(conn)["version"] == "v2"
    assert R.config_en_service(conn, CFG_V1) == CFG_V2  # le pipeline prendrait v2
    assert conn.execute(
        "SELECT count(*) FROM versions_modele WHERE statut='production'").fetchone()[0] == 1


@base
def test_retour_arriere(conn):
    R.config_en_service(conn, CFG_V1)
    R.enregistrer_version(conn, CFG_V2)
    R.promouvoir(conn, "v2", "jason")
    r = R.retour_arriere(conn, "amelia")
    assert r == {"ancienne": "v2", "nouvelle": "v1"}
    assert R.version_en_service(conn)["version"] == "v1"
    assert R.config_en_service(conn, CFG_V2) == CFG_V1


@base
def test_promouvoir_version_inconnue(conn):
    R.config_en_service(conn, CFG_V1)
    with pytest.raises(ValueError):
        R.promouvoir(conn, "v99", "amelia")