"""Normalisation des articles bruts (TD 4).

Fonctions pures, une par transformation, bibliothèque standard seulement.
Le brut n'est jamais modifié : on produit un nouvel article propre.
Le champ ``payload`` du brut n'est lu que pour retrouver une valeur manquante,
jamais recopié (il peut contenir des champs interdits par le bornage).
"""

from __future__ import annotations

import html
import re
import unicodedata
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

EXTRAIT_MAX = 300

_COMMENTAIRE = re.compile(r"<!--.*?-->", re.DOTALL)
_BLOC_INUTILE = re.compile(r"<(script|style)\b.*?</\1\s*>", re.IGNORECASE | re.DOTALL)
_BALISE = re.compile(r"</?[A-Za-z][^<>]*>")
_ESPACES = re.compile(r"\s+")
_INVISIBLES = dict.fromkeys(map(ord, "\u200b\u200c\u200d\u2060\ufeff"), None)

# Séquence typique d'un texte UTF-8 relu en cp1252 (ex. « Ã© » au lieu de « é »).
_SEQUENCE_MOJIBAKE = re.compile(
    "[\u00c2-\u00f4]"
    "[\u0080-\u00bf\u0152\u0153\u0160\u0161\u0178\u017d\u017e\u0192\u02c6\u02dc"
    "\u2013-\u203a\u20ac\u2122]+"
)
_MOJIBAKE_RESIDU = re.compile("\u00c3[\u0080-\u00bf]|\u00e2\u20ac|\ufffd")

_PARAMS_SUIVI_PREFIXES = ("utm_", "at_")
_PARAMS_SUIVI = frozenset({"fbclid", "gclid", "xtor", "mc_cid", "mc_eid"})


def retirer_html(texte: str | None) -> str:
    """Retire balises, commentaires, scripts et styles (le texte des balises reste)."""
    if not texte:
        return ""
    texte = _COMMENTAIRE.sub(" ", texte)
    texte = _BLOC_INUTILE.sub(" ", texte)
    return _BALISE.sub(" ", texte)


def decoder_entites(texte: str | None) -> str:
    """Remplace les entités HTML (&amp;, &#39;, &eacute;...) par leurs caractères."""
    if not texte:
        return ""
    return html.unescape(texte)


def normaliser_espaces(texte: str | None) -> str:
    """Espaces multiples, insécables, retours à la ligne et caractères invisibles."""
    if not texte:
        return ""
    texte = texte.translate(_INVISIBLES)
    return _ESPACES.sub(" ", texte).strip()


def _reparer_sequence(correspondance: re.Match[str]) -> str:
    sequence = correspondance.group(0)
    for fin in range(len(sequence), 1, -1):
        try:
            repare = sequence[:fin].encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            continue
        return repare + sequence[fin:]
    return sequence


def reparer_encodage(texte: str | None) -> str:
    """Répare le texte UTF-8 mal décodé (« CafÃ© » -> « Café »).

    Un texte déjà correct n'est pas modifié : une séquence n'est remplacée que si
    elle forme de l'UTF-8 valide.
    """
    if not texte:
        return ""
    return _SEQUENCE_MOJIBAKE.sub(_reparer_sequence, texte)


def est_encodage_casse(texte: str | None) -> bool:
    """Vrai s'il reste des caractères illisibles (après tentative de réparation)."""
    if not texte:
        return False
    return bool(_MOJIBAKE_RESIDU.search(texte))


def nettoyer_texte(valeur: object) -> str:
    """Chaîne complète : encodage, HTML, entités, HTML (double encodage), espaces."""
    if valeur is None:
        return ""
    if isinstance(valeur, (list, tuple)):
        valeur = ", ".join(str(v) for v in valeur)
    texte = reparer_encodage(str(valeur))
    texte = retirer_html(texte)
    texte = decoder_entites(texte)
    texte = retirer_html(texte)
    return normaliser_espaces(texte)


def vers_utc(valeur: object) -> datetime | None:
    """Convertit une date RSS (GMT, +0200) ou ISO en datetime UTC ; None si illisible."""
    if valeur is None:
        return None
    if isinstance(valeur, datetime):
        date = valeur
    else:
        texte = str(valeur).strip()
        if not texte:
            return None
        try:
            date = datetime.fromisoformat(re.sub(r"Z$", "+00:00", texte))
        except ValueError:
            try:
                date = parsedate_to_datetime(texte)
            except (TypeError, ValueError, IndexError):
                return None
    if date.tzinfo is None:
        date = date.replace(tzinfo=timezone.utc)
    return date.astimezone(timezone.utc)


def borner_extrait(texte: str | None, max_car: int = EXTRAIT_MAX) -> str:
    """Coupe l'extrait à ``max_car`` caractères au plus, à la fin d'un mot."""
    if not texte:
        return ""
    if len(texte) <= max_car:
        return texte
    coupe = texte[: max_car - 1]
    dernier_espace = coupe.rfind(" ")
    if dernier_espace >= max_car * 0.6:
        coupe = coupe[:dernier_espace]
    return coupe.rstrip(" ,;:.-") + "\u2026"


def normaliser_titre(texte: str | None) -> str:
    """Minuscules, sans accents ni ponctuation : sert à comparer et à détecter."""
    if not texte:
        return ""
    texte = texte.lower().replace("\u0153", "oe").replace("\u00e6", "ae")
    decompose = unicodedata.normalize("NFKD", texte)
    sans_accents = "".join(c for c in decompose if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", sans_accents).strip()


def mots_significatifs(titre_normalise: str) -> frozenset[str]:
    """Mots de 3 lettres ou plus : sert à la similarité de Jaccard."""
    return frozenset(m for m in titre_normalise.split() if len(m) >= 3)


def jaccard(a: frozenset[str] | set[str], b: frozenset[str] | set[str]) -> float:
    """Similarité de Jaccard entre deux ensembles de mots (0 à 1)."""
    union = len(a | b)
    if union == 0:
        return 0.0
    return len(a & b) / union


def nettoyer_lien(lien: str | None) -> str:
    """Retire les paramètres de suivi (utm_*, fbclid...) d'un lien."""
    if not lien:
        return ""
    lien = lien.strip()
    try:
        morceaux = urlsplit(lien)
    except ValueError:
        return lien
    gardes = [
        (cle, valeur)
        for cle, valeur in parse_qsl(morceaux.query, keep_blank_values=True)
        if not cle.lower().startswith(_PARAMS_SUIVI_PREFIXES)
        and cle.lower() not in _PARAMS_SUIVI
    ]
    return urlunsplit(morceaux._replace(query=urlencode(gardes)))


def _premier(*valeurs: object) -> object:
    for valeur in valeurs:
        if valeur not in (None, "", [], ()):
            return valeur
    return None


def normaliser_article(
    brut: dict,
    item_id: str | None = None,
    maintenant: datetime | None = None,
) -> dict:
    """Transforme un JSON brut en article propre.

    Champs du brut utilisés : id, source, lien, titre, resume, publie_le,
    recupere_le, rubrique (et payload, seulement en secours). Aucun autre champ
    n'est recopié.
    """
    maintenant = maintenant or datetime.now(timezone.utc)
    payload = brut.get("payload")
    if not isinstance(payload, dict):
        payload = {}

    titre = nettoyer_texte(_premier(brut.get("titre"), payload.get("title")))
    extrait = borner_extrait(
        nettoyer_texte(_premier(brut.get("resume"), payload.get("summary")))
    )
    lien = nettoyer_lien(str(_premier(brut.get("lien"), payload.get("link")) or ""))
    rubrique = nettoyer_texte(brut.get("rubrique")) or None

    collecte_le = vers_utc(brut.get("recupere_le"))
    publie_le = vers_utc(brut.get("publie_le")) or vers_utc(payload.get("published"))
    date_estimee = publie_le is None
    if publie_le is None:
        publie_le = collecte_le or maintenant

    return {
        "item_id": item_id or str(brut.get("id") or ""),
        "source": nettoyer_texte(brut.get("source")),
        "titre": titre,
        "extrait": extrait or None,
        "lien": lien,
        "rubrique": rubrique,
        "publie_le": publie_le,
        "date_estimee": date_estimee,
        "collecte_le": collecte_le,
        "titre_normalise": normaliser_titre(titre),
        "encodage_casse": est_encodage_casse(titre),
    }
