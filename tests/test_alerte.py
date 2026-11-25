"""Tests de l'alerte Discord, sans aucun accès réseau."""

import json
import logging
import urllib.error

from gazette.alerte import USER_AGENT, envoyer_alerte

URL = "https://discord.test/api/webhooks/123/SECRET-TOKEN"


class FausseReponse:
    def __init__(self, status=204):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def test_envoi_reussi_poste_le_message_en_json():
    vues = []

    def faux_ouvrir(requete, timeout):
        vues.append(requete)
        return FausseReponse(204)

    assert envoyer_alerte("Bonjour", url=URL, ouvrir=faux_ouvrir) is True
    requete = vues[0]
    assert requete.full_url == URL
    assert requete.get_method() == "POST"
    assert json.loads(requete.data)["content"] == "Bonjour"
    assert requete.get_header("User-agent") == USER_AGENT


def test_message_trop_long_est_coupe():
    vues = []
    envoyer_alerte("x" * 5000, url=URL, ouvrir=lambda r, timeout: vues.append(r) or FausseReponse())
    assert len(json.loads(vues[0].data)["content"]) <= 1900


def test_sans_webhook_pas_de_plantage(monkeypatch):
    monkeypatch.delenv("DISCORD_WEBHOOK_URL", raising=False)
    assert envoyer_alerte("x") is False


def test_lit_le_webhook_dans_l_environnement(monkeypatch):
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", URL)
    assert envoyer_alerte("x", ouvrir=lambda r, timeout: FausseReponse(204)) is True


def test_erreur_http_renvoie_false_sans_lever():
    def echec(requete, timeout):
        raise urllib.error.HTTPError(URL, 403, "interdit", {}, None)

    assert envoyer_alerte("x", url=URL, ouvrir=echec) is False


def test_erreur_reseau_renvoie_false_sans_lever():
    def echec(requete, timeout):
        raise urllib.error.URLError("réseau coupé")

    assert envoyer_alerte("x", url=URL, ouvrir=echec) is False


def test_l_url_du_webhook_n_apparait_jamais_dans_les_logs(caplog):
    def echec(requete, timeout):
        raise urllib.error.HTTPError(URL, 500, "erreur", {}, None)

    with caplog.at_level(logging.DEBUG):
        envoyer_alerte("x", url=URL, ouvrir=echec)
        envoyer_alerte("x", url=URL, ouvrir=lambda r, timeout: FausseReponse())
    assert "SECRET-TOKEN" not in caplog.text
    assert URL not in caplog.text
