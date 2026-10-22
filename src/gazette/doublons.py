"""Doublons exacts (R08) et approximatifs (R09) (TD 4).

On compare chaque nouvel article à ceux déjà gardés dans la fenêtre de
``FENETRE_DOUBLONS_H`` heures. Les articles sont traités du plus ancien au plus
récent : l'article conservé est donc le plus ancien, et le rejeté garde
``doublon_de`` (l'item_id de l'article conservé).

Les dépêches d'agence reprises par plusieurs titres sont traitées ici (R09) :
décision à confirmer dans docs/qualite.md.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from gazette.normalisation import jaccard, mots_significatifs, normaliser_titre
from gazette.regles_config import FENETRE_DOUBLONS_H, MIN_MOTS_DOUBLON, SEUIL_JACCARD

Doublon = tuple[str, str, str]  # (règle, item_id conservé, détail)


class IndexDoublons:
    """Mémoire des articles gardés, pour détecter les doublons."""

    def __init__(
        self, seuil: float = SEUIL_JACCARD, min_mots: int = MIN_MOTS_DOUBLON
    ) -> None:
        self.seuil = seuil
        self.min_mots = min_mots
        self._par_lien: dict[str, str] = {}
        self._par_titre: dict[str, str] = {}
        self._mots: list[tuple[str, frozenset[str]]] = []

    def __len__(self) -> int:
        return len(self._mots)

    def ajouter(self, item_id: str, titre_normalise: str, lien: str | None) -> None:
        if lien:
            self._par_lien.setdefault(lien, item_id)
        mots = mots_significatifs(titre_normalise)
        if len(mots) >= self.min_mots:
            self._par_titre.setdefault(titre_normalise, item_id)
            self._mots.append((item_id, mots))

    def chercher(self, titre_normalise: str, lien: str | None) -> Doublon | None:
        if lien and lien in self._par_lien:
            return "R08_doublon_exact", self._par_lien[lien], "même lien"
        mots = mots_significatifs(titre_normalise)
        if len(mots) < self.min_mots:
            return None
        if titre_normalise in self._par_titre:
            return "R08_doublon_exact", self._par_titre[titre_normalise], "même titre"
        taille = len(mots)
        for autre_id, autres in self._mots:
            petit, grand = sorted((taille, len(autres)))
            if petit / grand < self.seuil:  # Jaccard ne peut pas atteindre le seuil
                continue
            similarite = jaccard(mots, autres)
            if similarite >= self.seuil:
                return "R09_doublon_approx", autre_id, f"jaccard={similarite:.2f}"
        return None


def charger_index(
    cur, depuis: datetime | None = None, maintenant: datetime | None = None
) -> IndexDoublons:
    """Construit l'index à partir des articles propres récents (curseur ouvert)."""
    if depuis is None:
        maintenant = maintenant or datetime.now(timezone.utc)
        depuis = maintenant - timedelta(hours=FENETRE_DOUBLONS_H)
    index = IndexDoublons()
    cur.execute(
        "SELECT item_id, titre, lien FROM articles_propres "
        "WHERE nettoye_le >= %s ORDER BY publie_le, item_id",
        (depuis,),
    )
    for item_id, titre, lien in cur.fetchall():
        index.ajouter(item_id, normaliser_titre(titre), lien)
    return index
