"""Test du rendu du rapport de qualité (fonction pure, sans base)."""

from datetime import date, datetime, timezone

from gazette.rapport_qualite import rendre_markdown


def _stats():
    return {
        "jour": date(2026, 10, 22),
        "genere_le": datetime(2026, 10, 22, 7, 5, tzinfo=timezone.utc),
        "entres": 100,
        "gardes": 70,
        "rejetes": 30,
        "par_regle": {"R02_horoscope": 20, "R08_doublon_exact": 10},
        "par_source": {
            "Journal A": {"gardes": 40, "rejetes": 10},
            "Journal B": {"gardes": 30, "rejetes": 20},
        },
        "top_rejets": [
            {"regle": "R02_horoscope", "nombre": 20,
             "exemples": [{"source": "Journal B", "titre": "Horoscope | du jour"}]},
        ],
        "regles_gourmandes": [
            {"source": "Journal B", "regle": "R02_horoscope", "nombre": 20,
             "entres": 25, "taux": 0.8},
        ],
    }


def test_le_rapport_dit_combien_par_regle_et_par_source():
    texte = rendre_markdown(_stats())
    assert "# Rapport de qualité - 2026-10-22" in texte
    assert "| 100 | 70 | 30 | 30 % |" in texte
    assert "R02_horoscope | 20" in texte
    assert "Journal B | 50 | 30 | 20 | 40 %" in texte


def test_le_rapport_donne_des_exemples_de_rejets():
    texte = rendre_markdown(_stats())
    assert "Horoscope / du jour" in texte  # le "|" est neutralisé dans le markdown


def test_le_rapport_signale_une_regle_gourmande():
    texte = rendre_markdown(_stats())
    assert "trop gourmandes" in texte
    assert "R02_horoscope sur Journal B : 20 sur 25 (80 %)" in texte


def test_rapport_sans_donnees():
    vide = {"jour": date(2026, 10, 22), "genere_le": datetime(2026, 10, 22, tzinfo=timezone.utc),
            "entres": 0, "gardes": 0, "rejetes": 0, "par_regle": {}, "par_source": {},
            "top_rejets": [], "regles_gourmandes": []}
    texte = rendre_markdown(vide)
    assert "Aucun rejet" in texte
    assert "Aucune." in texte
