"""Règles d'exclusion unitaires (TD 4).

``appliquer_regles`` renvoie ``(identifiant, détail)`` de la première règle qui
s'applique, ou ``(None, None)`` si l'article est conservé. Les doublons (R08, R09)
demandent de comparer plusieurs articles : voir ``doublons.py``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from gazette.normalisation import normaliser_titre
from gazette.regles_config import (
    MIN_LONGUEUR_TITRE,
    REGLES_MOTIF,
    TOLERANCE_DATE_FUTURE,
)

Verdict = tuple[str | None, str | None]


def appliquer_regles(article: dict, maintenant: datetime | None = None) -> Verdict:
    """Première règle qui s'applique à l'article, dans l'ordre de ORDRE_REGLES."""
    maintenant = maintenant or datetime.now(timezone.utc)

    titre_normalise = article.get("titre_normalise")
    if titre_normalise is None:
        titre_normalise = normaliser_titre(article.get("titre"))

    # R05 : titre vide ou trop court
    if len(titre_normalise.replace(" ", "")) < MIN_LONGUEUR_TITRE:
        return "R05_titre_vide", "titre vide ou trop court"

    # R06 : date dans le futur (une date estimée n'est jamais dans le futur)
    publie_le = article.get("publie_le")
    if (
        publie_le is not None
        and not article.get("date_estimee")
        and publie_le > maintenant + TOLERANCE_DATE_FUTURE
    ):
        return "R06_date_future", f"publie_le={publie_le.isoformat()}"

    # R07 : encodage cassé (après réparation)
    if article.get("encodage_casse"):
        return "R07_encodage_casse", "caractères illisibles après réparation"

    # R01 à R04 et R10 : motifs et rubriques
    textes = {
        champ: normaliser_titre(article.get(champ) or "")
        for champ in ("titre", "extrait", "rubrique")
    }
    for regle in REGLES_MOTIF:
        rubrique = textes["rubrique"]
        if rubrique and rubrique in regle["rubriques"]:
            return regle["id"], f"rubrique: {rubrique}"
        texte = " ".join(textes[champ] for champ in regle["champs"])
        trouve = regle["motif"].search(texte)
        if trouve:
            return regle["id"], f"motif: {trouve.group(0)}"

    return None, None
