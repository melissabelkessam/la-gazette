"""Tests de l'évaluation automatique (TD 6) : seuils, dérive, verdict, échantillon.

Tout est pur : on passe des métriques, on vérifie le verdict. Pas de base ici.
Les seuils de référence des tests sont fixés dans le fichier, indépendants du YAML.
"""

from __future__ import annotations

from pathlib import Path

from gazette.evaluation import (
    VERDICT_OK,
    VERDICT_RECALE,
    VERDICT_REVUE,
    appliquer_seuils,
    charger_config,
    detecter_derive,
    evaluer,
    part_theme_geant,
    tirer_echantillon,
    verdict_final,
)

SEUILS = {"nb_themes_min": 3, "part_bruit_max": 0.80,
          "theme_geant_max": 0.50, "silhouette_min": 0.05}
DERIVE = {"fenetre_runs": 2, "part_bruit_surveillee": 0.50, "silhouette_surveillee": 0.07}

# Un run « sain », proche de votre premier run réel.
SAIN = {"nb_articles": 313, "nb_themes": 18, "taille_max": 40,
        "part_bruit": 0.21, "silhouette": 0.10}


def test_part_theme_geant():
    assert part_theme_geant({"nb_articles": 100, "taille_max": 50}) == 0.5
    assert part_theme_geant({"nb_articles": 0, "taille_max": 0}) == 0.0


def test_run_sain_passe():
    verdict, francs = appliquer_seuils(SAIN, SEUILS)
    assert verdict == VERDICT_OK
    assert francs == []


def test_trop_peu_de_themes_recale():
    verdict, francs = appliquer_seuils({**SAIN, "nb_themes": 2}, SEUILS)
    assert verdict == VERDICT_RECALE
    assert francs[0]["seuil"] == "nb_themes_min"


def test_trop_de_bruit_recale():
    verdict, francs = appliquer_seuils({**SAIN, "part_bruit": 0.85}, SEUILS)
    assert verdict == VERDICT_RECALE
    assert any(f["seuil"] == "part_bruit_max" for f in francs)


def test_theme_geant_recale():
    # un thème qui mange 60 % des articles
    verdict, francs = appliquer_seuils({**SAIN, "taille_max": 188}, SEUILS)
    assert verdict == VERDICT_RECALE
    assert any(f["seuil"] == "theme_geant_max" for f in francs)


def test_silhouette_trop_basse_recale():
    verdict, francs = appliquer_seuils({**SAIN, "silhouette": 0.02}, SEUILS)
    assert verdict == VERDICT_RECALE
    assert any(f["seuil"] == "silhouette_min" for f in francs)


def test_silhouette_absente_ignoree():
    # silhouette None (moins de 2 thèmes mesurables) : on ne recale pas sur ce critère seul
    verdict, francs = appliquer_seuils({**SAIN, "silhouette": None}, SEUILS)
    assert verdict == VERDICT_OK


def test_plusieurs_franchissements():
    verdict, francs = appliquer_seuils(
        {"nb_articles": 100, "nb_themes": 1, "taille_max": 90,
         "part_bruit": 0.9, "silhouette": 0.01}, SEUILS)
    assert verdict == VERDICT_RECALE
    assert len(francs) == 4


def test_pas_de_derive_sans_historique():
    derive, raisons = detecter_derive(SAIN, [], DERIVE)
    assert derive is False
    assert raisons == []


def test_derive_bruit_deux_runs():
    actuel = {**SAIN, "part_bruit": 0.55}
    historique = [{**SAIN, "part_bruit": 0.60}]
    derive, raisons = detecter_derive(actuel, historique, DERIVE)
    assert derive is True
    assert raisons[0]["regle"] == "part_bruit_surveillee"


def test_pas_de_derive_si_un_seul_run_mauvais():
    # bruit haut une seule fois (le run précédent était bon) : pas de dérive
    actuel = {**SAIN, "part_bruit": 0.55}
    historique = [{**SAIN, "part_bruit": 0.21}]
    derive, raisons = detecter_derive(actuel, historique, DERIVE)
    assert derive is False


def test_derive_silhouette_deux_runs():
    actuel = {**SAIN, "silhouette": 0.05}
    historique = [{**SAIN, "silhouette": 0.06}]
    derive, raisons = detecter_derive(actuel, historique, DERIVE)
    assert derive is True
    assert raisons[0]["regle"] == "silhouette_surveillee"


def test_verdict_final_recale_l_emporte():
    assert verdict_final(VERDICT_RECALE, True) == VERDICT_RECALE
    assert verdict_final(VERDICT_OK, True) == VERDICT_REVUE
    assert verdict_final(VERDICT_OK, False) == VERDICT_OK


def test_evaluer_sain_publie():
    res = evaluer(SAIN, [], {"seuils": SEUILS, "derive": DERIVE})
    assert res["verdict"] == VERDICT_OK
    assert res["publie"] is True


def test_evaluer_recale_ne_publie_pas():
    res = evaluer({**SAIN, "part_bruit": 0.95}, [], {"seuils": SEUILS, "derive": DERIVE})
    assert res["verdict"] == VERDICT_RECALE
    assert res["publie"] is False


def test_evaluer_revue_publie_quand_meme():
    actuel = {**SAIN, "part_bruit": 0.55}
    historique = [{**SAIN, "part_bruit": 0.60}]
    res = evaluer(actuel, historique, {"seuils": SEUILS, "derive": DERIVE})
    assert res["verdict"] == VERDICT_REVUE
    assert res["publie"] is True


def test_tirer_echantillon_reproductible():
    affectations = [{"item_id": f"a{i}", "theme": i % 4} for i in range(50)]
    affectations.append({"item_id": "bruit", "theme": -1})
    e1 = tirer_echantillon(affectations, 10, graine=42)
    e2 = tirer_echantillon(affectations, 10, graine=42)
    assert [a["item_id"] for a in e1] == [a["item_id"] for a in e2]
    assert len(e1) == 10
    assert all(a["theme"] != -1 for a in e1)  # jamais le bruit


def test_config_reelle_se_charge():
    chemin = Path(__file__).resolve().parents[1] / "config" / "evaluation.yaml"
    config = charger_config(chemin)
    assert set(config) >= {"seuils", "echantillon", "derive"}
    # le run sain de référence passe avec les VRAIS seuils du projet
    verdict, _ = appliquer_seuils(SAIN, config["seuils"])
    assert verdict == VERDICT_OK