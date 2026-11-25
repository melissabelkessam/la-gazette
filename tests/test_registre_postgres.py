"""Tests sur une vraie base PostgreSQL : migrations, table sources, journal des collectes.

Lancés par la CI (service postgres). En local, ils sont ignorés sauf si
GAZETTE_TEST_DATABASE_URL pointe vers une base jetable (elle est vidée !).
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest

from gazette.collecteur import executer_passage
from gazette.migrations import appliquer_migrations, fichiers_migration
from gazette.registre import RegistrePostgres, Source, lire_sources_csv

URL = os.environ.get("GAZETTE_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="GAZETTE_TEST_DATABASE_URL non défini")
FIXTURE = (Path(__file__).parent / "fixtures" / "sudouest_exemple.xml").read_bytes()
T0 = datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def conn():
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(URL, autocommit=True) as connexion:
        connexion.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        yield connexion


def test_migrations_rejouables(conn):
    toutes = [version for version, _ in fichiers_migration()]
    assert toutes[:2] == ["001_sources", "002_collectes"]
    assert appliquer_migrations(conn) == toutes
    assert appliquer_migrations(conn) == []  # relancer ne refait rien


def test_synchronisation_de_sources_csv(conn):
    appliquer_migrations(conn)
    registre = RegistrePostgres(conn)
    sources = lire_sources_csv(Path("sources.csv"))
    registre.synchroniser(sources)
    registre.synchroniser(sources)  # deux fois : pas de doublon
    assert conn.execute("SELECT count(*) FROM sources").fetchone()[0] == len(sources)
    frequence = conn.execute(
        "SELECT frequence_min FROM sources WHERE nom = 'Ouest-France'"
    ).fetchone()[0]
    assert frequence == 10


def passer(registre, dossier, quand):
    with httpx.Client(timeout=5) as client:
        return executer_passage(registre, dossier, client=client, maintenant=quand,
                                dormir=lambda _: None)


def test_etat_et_journal_en_base(conn, editeur, tmp_path):
    appliquer_migrations(conn)
    saine = editeur((200, FIXTURE, {"ETag": '"v1"'}))
    panne = editeur((503, b"", {}))
    registre = RegistrePostgres(conn)
    registre.synchroniser([
        Source(nom="Sud Ouest", type="PQR", url_flux=saine.url),
        Source(nom="En panne", type="PQN", url_flux=panne.url),
    ])

    for heure in range(3):
        passer(registre, tmp_path, T0 + timedelta(hours=heure))

    etat = dict(
        (nom, (actif, echecs, etag, reussite is not None))
        for nom, actif, echecs, etag, reussite in conn.execute(
            "SELECT nom, actif, echecs_consecutifs, etag, derniere_reussite FROM sources"
        )
    )
    assert etat["Sud Ouest"] == (True, 0, '"v1"', True)
    assert etat["En panne"] == (False, 3, None, False)  # en sommeil après 3 échecs

    par_source = dict(conn.execute(
        "SELECT source, sum(ecrits) FROM collectes GROUP BY source"
    ).fetchall())
    assert par_source == {"Sud Ouest": 3, "En panne": 0}  # deux passages, zéro doublon