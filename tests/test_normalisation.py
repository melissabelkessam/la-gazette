"""Tests de la normalisation (TD 4). Données inventées, aucun contenu de presse."""

from datetime import datetime, timezone

from gazette.normalisation import (
    borner_extrait,
    decoder_entites,
    est_encodage_casse,
    jaccard,
    mots_significatifs,
    nettoyer_lien,
    normaliser_article,
    normaliser_espaces,
    normaliser_titre,
    reparer_encodage,
    retirer_html,
    vers_utc,
)


def _mojibake(texte: str) -> str:
    """Simule un texte UTF-8 relu en cp1252 (la panne à réparer)."""
    return texte.encode("utf-8").decode("cp1252")


def test_retirer_html_balises_et_blocs():
    assert retirer_html("<p>Bonjour <b>le</b> monde</p>").split() == ["Bonjour", "le", "monde"]
    assert "alert" not in retirer_html("avant<script>alert(1)</script>après")
    assert "secret" not in retirer_html("a<!-- secret -->b")


def test_retirer_html_garde_les_comparaisons():
    assert retirer_html("si a < b et c > d") == "si a < b et c > d"


def test_retirer_html_vide():
    assert retirer_html(None) == ""
    assert retirer_html("") == ""


def test_decoder_entites():
    assert decoder_entites("Tom &amp; Jerry &#39;ok&#39; caf&eacute;") == "Tom & Jerry 'ok' café"
    assert decoder_entites(None) == ""


def test_normaliser_espaces():
    assert normaliser_espaces("  un \n\n deux\u00a0\u00a0trois\t") == "un deux trois"
    assert normaliser_espaces("a\u200bb") == "ab"
    assert normaliser_espaces("") == ""


def test_reparer_encodage_repare_le_texte_casse():
    assert reparer_encodage(_mojibake("Café à Paris")) == "Café à Paris"
    assert reparer_encodage(_mojibake("l’été dernier")) == "l’été dernier"


def test_reparer_encodage_ne_touche_pas_un_texte_correct():
    for texte in ("Café à Paris", "ÂGE de raison", "Ça va", "plain ascii"):
        assert reparer_encodage(texte) == texte


def test_reparer_encodage_vide():
    assert reparer_encodage(None) == ""


def test_est_encodage_casse():
    assert est_encodage_casse("titre avec \ufffd illisible")
    assert est_encodage_casse("Ã\u00a9 reste cassé")
    assert not est_encodage_casse("Café très propre")
    assert not est_encodage_casse(None)


def test_vers_utc_formats_rss_et_iso():
    attendu = datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)
    assert vers_utc("Thu, 22 Oct 2026 08:00:00 GMT") == attendu
    assert vers_utc("Thu, 22 Oct 2026 08:00:00 +0000") == attendu
    assert vers_utc("Thu, 22 Oct 2026 10:00:00 +0200") == attendu
    assert vers_utc("2026-10-22T08:00:00Z") == attendu
    assert vers_utc("2026-10-22T10:00:00+02:00") == attendu
    assert vers_utc("2026-10-22 08:00:00") == attendu  # sans fuseau : UTC


def test_vers_utc_illisible():
    assert vers_utc(None) is None
    assert vers_utc("") is None
    assert vers_utc("pas une date") is None


def test_borner_extrait():
    assert borner_extrait("court") == "court"
    long = "mot " * 200
    borne = borner_extrait(long, 50)
    assert len(borne) <= 50
    assert borne.endswith("\u2026")
    assert not borne[:-1].endswith(" ")
    assert borner_extrait(None) == ""


def test_normaliser_titre():
    assert normaliser_titre("  L’Été, déjà CHAUD !  ") == "l ete deja chaud"
    assert normaliser_titre("Cœur") == "coeur"
    assert normaliser_titre(None) == ""


def test_mots_significatifs_et_jaccard():
    a = mots_significatifs("le chat dort dans la maison")
    b = mots_significatifs("le chat dort dans le jardin")
    assert "le" not in a  # mots de moins de 3 lettres ignorés
    assert jaccard(a, a) == 1.0
    assert 0 < jaccard(a, b) < 1
    assert jaccard(frozenset(), frozenset()) == 0.0


def test_nettoyer_lien_retire_le_suivi():
    lien = "https://exemple.test/a/b?id=7&utm_source=x&utm_medium=y&fbclid=z"
    assert nettoyer_lien(lien) == "https://exemple.test/a/b?id=7"
    assert nettoyer_lien("https://exemple.test/a") == "https://exemple.test/a"
    assert nettoyer_lien(None) == ""


def test_normaliser_article_mappe_les_champs_du_brut():
    brut = {
        "id": "abc123",
        "source": "Journal Test",
        "lien": "https://exemple.test/x?utm_source=rss",
        "titre": "<b>Un  titre</b> &amp; plus",
        "resume": "<p>Un résumé</p>",
        "publie_le": "Thu, 22 Oct 2026 10:00:00 +0200",
        "recupere_le": "2026-10-22T08:30:00+00:00",
        "rubrique": "Société",
        "payload": {"author": "Nom Prénom", "dc:creator": "x@exemple.test"},
    }
    article = normaliser_article(brut, item_id="abc123")
    assert article["item_id"] == "abc123"
    assert article["titre"] == "Un titre & plus"
    assert article["extrait"] == "Un résumé"
    assert article["lien"] == "https://exemple.test/x"
    assert article["rubrique"] == "Société"
    assert article["publie_le"] == datetime(2026, 10, 22, 8, 0, tzinfo=timezone.utc)
    assert article["collecte_le"] == datetime(2026, 10, 22, 8, 30, tzinfo=timezone.utc)
    assert article["date_estimee"] is False
    assert article["titre_normalise"] == "un titre plus"


def test_normaliser_article_ne_recopie_ni_payload_ni_auteur():
    brut = {"id": "a", "source": "S", "lien": "l", "titre": "t", "payload": {"author": "Nom"}}
    article = normaliser_article(brut, item_id="a")
    assert "payload" not in article
    assert "Nom" not in repr(article)


def test_normaliser_article_date_absente_est_estimee():
    maintenant = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
    brut = {"id": "a", "source": "S", "lien": "l", "titre": "t",
            "recupere_le": "2026-10-22T09:00:00+00:00"}
    article = normaliser_article(brut, item_id="a", maintenant=maintenant)
    assert article["date_estimee"] is True
    assert article["publie_le"] == datetime(2026, 10, 22, 9, 0, tzinfo=timezone.utc)


def test_normaliser_article_secours_sur_le_payload():
    brut = {"id": "a", "source": "S", "payload": {"title": "Titre secours",
            "link": "https://exemple.test/p", "summary": "Résumé secours",
            "published": "Thu, 22 Oct 2026 08:00:00 GMT"}}
    article = normaliser_article(brut, item_id="a")
    assert article["titre"] == "Titre secours"
    assert article["lien"] == "https://exemple.test/p"
    assert article["extrait"] == "Résumé secours"
    assert article["date_estimee"] is False


def test_normaliser_article_repare_un_titre_casse():
    brut = {"id": "a", "source": "S", "lien": "l", "titre": _mojibake("Une très belle journée")}
    assert normaliser_article(brut, item_id="a")["titre"] == "Une très belle journée"
