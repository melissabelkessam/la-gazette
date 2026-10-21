"""Tests du parseur RSS, sur un flux d'exemple enregistré (aucun accès réseau)."""

import json
from pathlib import Path

from gazette.collecte import calculer_item_id, normaliser_lien, parser_flux

FIXTURE = Path(__file__).parent / "fixtures" / "sudouest_exemple.xml"
CHAMPS_AUTORISES = {
    "item_id",
    "source",
    "titre",
    "extrait",
    "lien",
    "date_publication",
    "rubrique",
}


def lire_articles() -> list[dict]:
    return parser_flux(FIXTURE.read_bytes(), "Sud Ouest")


def test_lit_les_trois_articles():
    assert len(lire_articles()) == 4


def test_article_normal():
    article = lire_articles()[0]
    assert article["titre"] == "Bordeaux : un nouveau pont ouvre à la circulation"
    assert article["extrait"].startswith("La métropole inaugure")
    assert article["rubrique"] == "Gironde"
    assert article["source"] == "Sud Ouest"


def test_dates_converties_en_utc():
    articles = lire_articles()
    # 13:58:29 à Paris (+0200) = 11:58:29 en UTC
    assert articles[0]["date_publication"] == "2026-10-20T11:58:29+00:00"
    # 21:10:00 à Paris (+0200) = 19:10:00 en UTC
    assert articles[1]["date_publication"] == "2026-10-19T19:10:00+00:00"
    # déjà en GMT : inchangé
    assert articles[2]["date_publication"] == "2026-10-20T05:19:00+00:00"


def test_parametres_utm_retires_du_lien():
    article = lire_articles()[1]
    assert "utm_" not in article["lien"]
    assert article["lien"] == (
        "https://www.sudouest.fr/sport/rugby/qualification-finale-456.php"
    )


def test_seuls_les_champs_autorises_sont_gardes():
    for article in lire_articles():
        assert set(article) == CHAMPS_AUTORISES


def test_ni_auteur_ni_texte_integral_ni_image():
    """Bornage : aucune donnée personnelle, jamais l'article entier, jamais d'image."""
    tout = json.dumps(lire_articles(), ensure_ascii=False)
    assert "Jeanne Dupont" not in tout
    assert "j.dupont@exemple.fr" not in tout
    assert "Texte intégral" not in tout
    assert ".jpg" not in tout


def test_article_sans_extrait():
    article = lire_articles()[2]
    assert article["extrait"] is None
    assert article["titre"] == "Météo : un week-end ensoleillé sur la côte"


def test_item_id_identique_avec_ou_sans_utm():
    """Le même article, avec ou sans suivi publicitaire, a le même identifiant."""
    avec_utm = normaliser_lien("https://exemple.fr/a.php?utm_source=rss&page=2")
    sans_utm = normaliser_lien("https://exemple.fr/a.php?page=2")
    assert avec_utm == sans_utm == "https://exemple.fr/a.php?page=2"
    assert calculer_item_id(avec_utm) == calculer_item_id(sans_utm)