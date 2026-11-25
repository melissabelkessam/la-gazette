"""Tests de la vectorisation et de son cache (TD 5). Données inventées, modèle factice.

Le vrai modèle (sentence-transformers) n'est jamais téléchargé ici : un encodeur factice,
déterministe, le remplace. Les tests marqués ``base`` demandent une base PostgreSQL
jetable (``GAZETTE_TEST_DATABASE_URL``, elle est vidée !) et tournent dans la CI.
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

from gazette.embeddings import Article, lire_articles, texte_article, vectoriser
from gazette.migrations import appliquer_migrations

URL_TEST = os.environ.get("GAZETTE_TEST_DATABASE_URL")
base = pytest.mark.skipif(not URL_TEST, reason="GAZETTE_TEST_DATABASE_URL absente")
MAINTENANT = datetime(2026, 10, 23, 6, 0, tzinfo=timezone.utc)


class EncodeurFactice:
    """Vecteurs déterministes tirés du texte ; compte les textes réellement encodés."""

    def __init__(self, nom="factice/test", version="v1", dimension=16):
        self.nom, self.version, self.dimension = nom, version, dimension
        self.encodes: list[str] = []

    def encoder(self, textes):
        self.encodes.extend(textes)
        lignes = []
        for texte in textes:
            graine = int(hashlib.sha256(texte.encode()).hexdigest()[:8], 16)
            v = np.random.default_rng(graine).normal(size=self.dimension)
            lignes.append(v / np.linalg.norm(v))
        return np.asarray(lignes, dtype=np.float32)


def test_texte_article_titre_puis_extrait():
    assert texte_article("Titre", "Un extrait.") == "Titre. Un extrait."
    assert texte_article("Titre", None) == "Titre"
    assert texte_article("Titre", "Titre") == "Titre"  # extrait qui répète le titre
    assert texte_article("  Titre ", "  ") == "Titre"


@pytest.fixture
def conn():
    psycopg = pytest.importorskip("psycopg")
    with psycopg.connect(URL_TEST, autocommit=True) as connexion:
        connexion.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        appliquer_migrations(connexion)
        yield connexion


def inserer_articles(conn, n, debut=MAINTENANT - timedelta(hours=1)):
    articles = []
    for i in range(n):
        a = Article(f"id{i:03d}", "Journal Test", f"Titre inventé numéro {i}",
                    f"Extrait inventé {i}", debut - timedelta(minutes=i))
        conn.execute(
            "INSERT INTO articles_propres (item_id, source, titre, extrait, lien, publie_le) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (a.item_id, a.source, a.titre, a.extrait, f"https://exemple.test/{i}", a.publie_le),
        )
        articles.append(a)
    return articles


@base
def test_dix_articles_vectorises_une_seule_fois(conn):
    inserer_articles(conn, 10)
    articles = lire_articles(conn, MAINTENANT, 24)
    assert len(articles) == 10
    encodeur = EncodeurFactice()

    premiers, bilan1 = vectoriser(conn, articles, encodeur)
    assert premiers.shape == (10, 16)
    assert bilan1["calcules"] == 10 and bilan1["en_cache"] == 0

    seconds, bilan2 = vectoriser(conn, articles, encodeur)
    assert bilan2["calcules"] == 0 and bilan2["en_cache"] == 10
    assert len(encodeur.encodes) == 10  # le second passage n'a rien recalculé
    np.testing.assert_allclose(premiers, seconds, rtol=1e-6)


@base
def test_seuls_les_nouveaux_articles_sont_calcules(conn):
    inserer_articles(conn, 10)
    encodeur = EncodeurFactice()
    vectoriser(conn, lire_articles(conn, MAINTENANT, 24)[:4], encodeur)
    _, bilan = vectoriser(conn, lire_articles(conn, MAINTENANT, 24), encodeur)
    assert (bilan["en_cache"], bilan["calcules"]) == (4, 6)


@base
def test_une_autre_version_du_modele_ne_reutilise_pas_le_cache(conn):
    inserer_articles(conn, 10)
    articles = lire_articles(conn, MAINTENANT, 24)
    vectoriser(conn, articles, EncodeurFactice(version="v1"))
    _, bilan = vectoriser(conn, articles, EncodeurFactice(version="v2"))
    assert bilan["calcules"] == 10


@base
def test_la_fenetre_ne_garde_que_les_dernieres_24_h(conn):
    inserer_articles(conn, 3)
    conn.execute(
        "INSERT INTO articles_propres (item_id, source, titre, lien, publie_le) "
        "VALUES ('vieux', 'Journal Test', 'Vieil article', 'https://exemple.test/v', %s)",
        (MAINTENANT - timedelta(hours=30),),
    )
    ids = [a.item_id for a in lire_articles(conn, MAINTENANT, 24)]
    assert "vieux" not in ids and len(ids) == 3
