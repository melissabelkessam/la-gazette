"""Tests des doublons exacts (R08) et approximatifs (R09). Titres inventés."""

from gazette.doublons import IndexDoublons
from gazette.normalisation import normaliser_titre

TITRE = "La municipalité annonce la rénovation complète de la gare du centre ville"
# Titre long : changer un seul mot reste au-dessus du seuil de 0,8 (12 mots communs sur 14).
TITRE_LONG = (
    "La municipalité annonce la rénovation complète de la gare principale du centre "
    "historique après plusieurs années de travaux reportés"
)


def _ajouter(index, item_id, titre, lien=None):
    index.ajouter(item_id, normaliser_titre(titre), lien)


def _chercher(index, titre, lien=None):
    return index.chercher(normaliser_titre(titre), lien)


def test_pas_de_doublon_sur_index_vide():
    assert _chercher(IndexDoublons(), TITRE) is None


def test_doublon_exact_meme_titre():
    index = IndexDoublons()
    _ajouter(index, "a", TITRE)
    regle, garde, detail = _chercher(index, TITRE.upper())
    assert (regle, garde) == ("R08_doublon_exact", "a")
    assert detail == "même titre"


def test_doublon_exact_meme_lien():
    index = IndexDoublons()
    _ajouter(index, "a", "Un premier titre assez long pour compter", "https://exemple.test/x")
    regle, garde, _ = _chercher(index, "Un tout autre titre sans rapport ici", "https://exemple.test/x")
    assert (regle, garde) == ("R08_doublon_exact", "a")


def test_doublon_approximatif():
    index = IndexDoublons()
    _ajouter(index, "a", TITRE_LONG)
    proche = TITRE_LONG.replace("complète", "totale")
    regle, garde, detail = _chercher(index, proche)
    assert (regle, garde) == ("R09_doublon_approx", "a")
    assert detail.startswith("jaccard=")


def test_titres_differents_ne_sont_pas_des_doublons():
    index = IndexDoublons()
    _ajouter(index, "a", TITRE)
    assert _chercher(index, "Le club de football remporte le derby face au voisin") is None


def test_titre_trop_court_n_est_pas_compare():
    index = IndexDoublons()
    _ajouter(index, "a", "Édito du jour")
    assert _chercher(index, "Édito du jour") is None


def test_seuil_reglable():
    index = IndexDoublons(seuil=0.99)
    _ajouter(index, "a", TITRE_LONG)
    assert _chercher(index, TITRE_LONG.replace("complète", "totale")) is None


def test_le_premier_article_ajoute_est_celui_conserve():
    index = IndexDoublons()
    _ajouter(index, "ancien", TITRE)
    _ajouter(index, "recent", TITRE)
    assert _chercher(index, TITRE)[1] == "ancien"
