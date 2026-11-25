"""Tests des règles d'exclusion (TD 4). Titres inventés."""

from datetime import datetime, timedelta, timezone

import pytest

from gazette.normalisation import normaliser_titre
from gazette.regles import appliquer_regles

MAINTENANT = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)


def faire(titre="Le conseil municipal vote le budget", **champs):
    article = {
        "titre": titre,
        "titre_normalise": normaliser_titre(titre),
        "extrait": None,
        "rubrique": None,
        "publie_le": MAINTENANT - timedelta(hours=1),
        "date_estimee": False,
        "encodage_casse": False,
    }
    article.update(champs)
    return article


def regle(article):
    return appliquer_regles(article, MAINTENANT)[0]


def test_article_normal_est_garde():
    assert appliquer_regles(faire(), MAINTENANT) == (None, None)


@pytest.mark.parametrize("titre", ["", "  ", "?!", "ab"])
def test_r05_titre_vide(titre):
    assert regle(faire(titre)) == "R05_titre_vide"


def test_r05_titre_court_mais_valide_est_garde():
    assert regle(faire("Mort de l'abbé Pierre")) is None


def test_r06_date_future():
    assert regle(faire(publie_le=MAINTENANT + timedelta(days=2))) == "R06_date_future"


def test_r06_tolerance_de_fuseau():
    assert regle(faire(publie_le=MAINTENANT + timedelta(hours=2))) is None


def test_r06_date_estimee_jamais_future():
    article = faire(publie_le=MAINTENANT + timedelta(days=2), date_estimee=True)
    assert regle(article) is None


def test_r07_encodage_casse():
    assert regle(faire(encodage_casse=True)) == "R07_encodage_casse"


@pytest.mark.parametrize("champs", [
    {"titre": "Contenu partenaire : les meilleures offres de la rentrée"},
    {"titre": "Publi-reportage : un nouveau canapé"},
    {"extrait": "Contenu sponsorisé par la marque Exemple"},
    {"rubrique": "Publi-reportage"},
    {"titre": "Code promo : 20 % sur tout le site"},
])
def test_r01_publi(champs):
    assert regle(faire(**champs)) == "R01_publi"


def test_r01_faux_positif_evite():
    assert regle(faire("Le partenaire de la mairie présente le projet")) is None


@pytest.mark.parametrize("champs", [
    {"titre": "Horoscope du jeudi : journée chargée pour le Bélier"},
    {"titre": "Voyance et tarot : ce que disent les cartes"},
    {"rubrique": "Horoscope"},
])
def test_r02_horoscope(champs):
    assert regle(faire(**champs)) == "R02_horoscope"


@pytest.mark.parametrize("titre", [
    "Programme TV du soir : que regarder ce soir à la télé",
    "Sur quelle chaîne voir le match ?",
])
def test_r03_tv(titre):
    assert regle(faire(titre)) == "R03_tv"


def test_r03_faux_positif_evite():
    assert regle(faire("Le patron de la télévision publique démissionne")) is None


@pytest.mark.parametrize("titre", [
    "Jeu concours : tentez de gagner un week-end",
    "Mots fléchés du jour",
    "Résultats du Loto : les numéros gagnants",
    "Euromillions : la cagnotte grimpe",
])
def test_r04_jeux(titre):
    assert regle(faire(titre)) == "R04_jeux"


def test_r04_faux_positif_evite():
    assert regle(faire("Le concours de la fonction publique ouvre ses inscriptions")) is None


@pytest.mark.parametrize("titre", [
    "DIRECT. Les dernières informations sur la tempête",
    "En direct : le conseil municipal",
    "Diaporama : les plus belles photos du marché",
])
def test_r10_direct_diaporama(titre):
    assert regle(faire(titre)) == "R10_direct_diaporama"


def test_r10_faux_positif_evite():
    assert regle(faire("Le directeur de l'hôpital en direct de la rue")) is None


def test_le_detail_explique_le_rejet():
    _, detail = appliquer_regles(faire("Horoscope du jour"), MAINTENANT)
    assert "horoscope" in detail


def test_ordre_la_premiere_regle_gagne():
    # titre vide (R05) passe avant tout le reste
    article = faire("", publie_le=MAINTENANT + timedelta(days=5))
    assert regle(article) == "R05_titre_vide"
