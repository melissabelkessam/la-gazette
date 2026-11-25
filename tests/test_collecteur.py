"""Tests du collecteur contre un vrai serveur HTTP local (aucun accès à Internet).

- « deux passages, zéro doublon »
- « source en panne » : le serveur renvoie 503, on réessaie, puis la source s'endort
"""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

from gazette.collecteur import SEUIL_SOMMEIL, executer_passage
from gazette.registre import RegistreMemoire, Source

FIXTURE = (Path(__file__).parent / "fixtures" / "sudouest_exemple.xml").read_bytes()
T0 = datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)


def source(url: str, nom: str = "Sud Ouest") -> Source:
    return Source(nom=nom, type="PQR", url_flux=url, frequence_min=60)


def passer(registre, dossier, quand, attentes=None):
    """Un passage, sans vraie attente : les pauses du backoff sont seulement notées."""
    attentes = [] if attentes is None else attentes
    with httpx.Client(timeout=5) as client:
        return executer_passage(
            registre, dossier, client=client, maintenant=quand, dormir=attentes.append
        )


def fichiers(dossier: Path) -> list[Path]:
    return sorted(dossier.rglob("*.json"))


# --- deux passages, zéro doublon -------------------------------------------------------


def test_deux_passages_zero_doublon(editeur, tmp_path):
    serveur = editeur((200, FIXTURE, {"Content-Type": "application/rss+xml"}))
    registre = RegistreMemoire([source(serveur.url)])

    premier = passer(registre, tmp_path, T0)
    apres_premier = fichiers(tmp_path)
    second = passer(registre, tmp_path, T0 + timedelta(hours=1))

    assert len(apres_premier) == 3
    assert fichiers(tmp_path) == apres_premier  # le nombre d'articles ne bouge pas
    assert (premier["recus"], premier["ecrits"], premier["ignores"]) == (3, 3, 0)
    assert (second["recus"], second["ecrits"], second["ignores"]) == (3, 0, 3)


def test_fichier_brut_contient_les_champs_du_dictionnaire(editeur, tmp_path):
    serveur = editeur((200, FIXTURE, {}))
    passer(RegistreMemoire([source(serveur.url)]), tmp_path, T0)

    item = json.loads(fichiers(tmp_path)[0].read_text(encoding="utf-8"))
    assert set(item) == {
        "id", "source", "lien", "titre", "resume",
        "publie_le", "recupere_le", "rubrique", "payload",
    }
    # le payload garde l'item tel que reçu, mais jamais l'auteur ni le texte intégral
    tout = json.dumps([json.loads(f.read_text("utf-8")) for f in fichiers(tmp_path)])
    for interdit in ("Jeanne Dupont", "j.dupont@exemple.fr", "Texte intégral", ".jpg"):
        assert interdit not in tout


def test_etag_renvoye_et_304_respecte(editeur, tmp_path):
    serveur = editeur(
        (200, FIXTURE, {"ETag": '"v1"', "Last-Modified": "Thu, 22 Oct 2026 07:00:00 GMT"}),
        (304, b"", {}),
    )
    registre = RegistreMemoire([source(serveur.url)])

    passer(registre, tmp_path, T0)
    second = passer(registre, tmp_path, T0 + timedelta(hours=1))

    assert serveur.requetes[1]["If-None-Match"] == '"v1"'
    assert serveur.requetes[1]["If-Modified-Since"] == "Thu, 22 Oct 2026 07:00:00 GMT"
    assert registre.journal[-1].statut == "non_modifie"
    assert second["recus"] == 0


# --- source en panne ------------------------------------------------------------------


def test_source_en_panne_503_reessaie_avec_attente_croissante(editeur, tmp_path):
    serveur = editeur((503, b"Service Unavailable", {}))
    registre = RegistreMemoire([source(serveur.url)])
    attentes = []

    bilan = passer(registre, tmp_path, T0, attentes)

    assert len(serveur.requetes) == 3  # 3 essais
    assert attentes == [2.0, 4.0]  # backoff : 2 s puis 4 s
    assert bilan["echecs"] == 1
    etat = registre.sources["Sud Ouest"]
    assert etat.echecs_consecutifs == 1 and etat.actif
    assert fichiers(tmp_path) == []


def test_source_en_panne_trois_fois_mise_en_sommeil(editeur, tmp_path):
    serveur = editeur((503, b"", {}))
    registre = RegistreMemoire([source(serveur.url)])

    for heure in range(SEUIL_SOMMEIL):
        passer(registre, tmp_path, T0 + timedelta(hours=heure))

    assert [b.statut for b in registre.journal] == ["echec", "echec", "mise_en_sommeil"]
    assert not registre.sources["Sud Ouest"].actif
    # une source endormie n'est plus appelée
    requetes = len(serveur.requetes)
    passer(registre, tmp_path, T0 + timedelta(hours=5))
    assert len(serveur.requetes) == requetes


def test_404_permanente_pas_de_nouvel_essai(editeur, tmp_path):
    serveur = editeur((404, b"Not Found", {}))
    registre = RegistreMemoire([source(serveur.url)])

    passer(registre, tmp_path, T0)

    assert len(serveur.requetes) == 1
    assert registre.journal[0].http_statut == 404


def test_reprise_apres_erreur_transitoire_remet_le_compteur_a_zero(editeur, tmp_path):
    serveur = editeur((503, b"", {}), (200, FIXTURE, {}))
    registre = RegistreMemoire([replace(source(serveur.url), echecs_consecutifs=2)])

    bilan = passer(registre, tmp_path, T0)

    assert bilan["ecrits"] == 3
    assert registre.sources["Sud Ouest"].echecs_consecutifs == 0
    assert registre.journal[0].essais == 2


def test_flux_casse_compte_comme_un_echec(editeur, tmp_path):
    serveur = editeur((200, b"<html>Erreur interne</html>", {"Content-Type": "text/html"}))
    registre = RegistreMemoire([source(serveur.url)])

    passer(registre, tmp_path, T0)

    assert registre.journal[0].statut == "echec"
    assert "illisible" in registre.journal[0].erreur


def test_une_source_en_panne_n_empeche_pas_les_autres(editeur, tmp_path):
    panne = editeur((503, b"", {}))
    saine = editeur((200, FIXTURE, {}))
    registre = RegistreMemoire([source(panne.url, "En panne"), source(saine.url, "Sud Ouest")])

    bilan = passer(registre, tmp_path, T0)

    assert (bilan["ok"], bilan["echecs"], bilan["ecrits"]) == (1, 1, 3)


def test_frequence_respectee(editeur, tmp_path):
    serveur = editeur((200, FIXTURE, {}))
    registre = RegistreMemoire([source(serveur.url)])  # toutes les 60 min

    passer(registre, tmp_path, T0)
    passer(registre, tmp_path, T0 + timedelta(minutes=10))  # trop tôt : pas d'appel

    assert len(serveur.requetes) == 1


def test_plus_de_reseau_chez_nous_ne_endort_pas_les_sources(tmp_path):
    """PC sans Internet : aucune source ne répond. Ce n'est pas leur faute, on ne compte pas."""
    injoignable = "http://127.0.0.1:9/rss.xml"  # port 9 : rien n'y écoute
    registre = RegistreMemoire([
        replace(source(injoignable, "A"), echecs_consecutifs=2),
        source(injoignable, "B"),
    ])

    bilan = passer(registre, tmp_path, T0)

    assert bilan["reseau_indisponible"] is True
    assert {b.statut for b in registre.journal} == {"reseau_indisponible"}
    assert registre.sources["A"].actif and registre.sources["A"].echecs_consecutifs == 2