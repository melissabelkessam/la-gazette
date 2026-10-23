"""Vectorisation des articles propres, avec cache (TD 5).

Titre + extrait -> un vecteur (modèle multilingue léger, sur CPU). Chaque vecteur est
rangé dans la table ``embeddings`` avec le nom ET la version du modèle : un article
n'est calculé qu'une fois, et changer de modèle ne mélange jamais deux espaces.

Lançable sans Prefect : ``python -m gazette.embeddings`` (vectorise les dernières 24 h).
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Protocol, Sequence

import numpy as np

logger = logging.getLogger("gazette.embeddings")


@dataclass(frozen=True)
class Article:
    item_id: str
    source: str
    titre: str
    extrait: str | None
    publie_le: datetime


class Encodeur(Protocol):
    """Ce dont le pipeline a besoin d'un modèle : un nom, une version, des vecteurs."""

    nom: str
    version: str

    def encoder(self, textes: Sequence[str]) -> np.ndarray: ...


def texte_article(titre: str, extrait: str | None) -> str:
    """Le texte vectorisé : le titre, puis l'extrait s'il apporte quelque chose."""
    titre = (titre or "").strip()
    extrait = (extrait or "").strip()
    if not extrait or extrait == titre:
        return titre
    return f"{titre}. {extrait}"


class EncodeurSentenceTransformers:
    """Modèle sentence-transformers, chargé à la première utilisation.

    La version notée est le commit Hugging Face réellement chargé (dossier
    ``snapshots/<commit>`` du cache) : deux runs avec la même version utilisent
    exactement les mêmes poids, même si ``revision: main`` a bougé entre-temps.
    """

    def __init__(self, nom: str, revision: str = "main", taille_lot: int = 64):
        self.nom = nom
        self.revision = revision
        self.taille_lot = taille_lot
        self._modele = None
        self._version: str | None = None

    def _charger(self):
        if self._modele is None:
            from huggingface_hub import snapshot_download
            from sentence_transformers import SentenceTransformer

                        # Seuls les poids PyTorch et les fichiers du tokenizer : pas les variantes
            # ONNX, OpenVINO ni TensorFlow du dépôt (plusieurs Go inutiles).
            chemin = snapshot_download(
                self.nom,
                revision=self.revision,
                ignore_patterns=["onnx/*", "openvino/*", "*.h5", "*.msgpack", "*.ot",
                                 "pytorch_model.bin"],
            )
            self._version = Path(chemin).name
            self._modele = SentenceTransformer(chemin, device="cpu")
        return self._modele

    @property
    def version(self) -> str:
        self._charger()
        return self._version or self.revision

    def encoder(self, textes: Sequence[str]) -> np.ndarray:
        modele = self._charger()
        vecteurs = modele.encode(
            list(textes),
            batch_size=self.taille_lot,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return np.asarray(vecteurs, dtype=np.float32)


def lire_articles(
    conn, fin: datetime, heures: int = 24
) -> list[Article]:
    """Articles propres publiés dans la fenêtre ]fin - heures, fin], triés (ordre stable)."""
    debut = fin - timedelta(hours=heures)
    lignes = conn.execute(
        "SELECT item_id, source, titre, extrait, publie_le FROM articles_propres "
        "WHERE publie_le > %s AND publie_le <= %s ORDER BY item_id",
        (debut, fin),
    ).fetchall()
    return [Article(*ligne) for ligne in lignes]


def vectoriser(conn, articles: Sequence[Article], encodeur: Encodeur) -> tuple[np.ndarray, dict]:
    """Vecteurs des articles, dans le même ordre. Ne calcule que ceux absents du cache.

    Renvoie (matrice n x d, bilan {en_cache, calcules, duree_s}).
    """
    debut = time.monotonic()
    if not articles:
        return np.zeros((0, 0), dtype=np.float32), {"en_cache": 0, "calcules": 0, "duree_s": 0.0}

    ids = [a.item_id for a in articles]
    version = encodeur.version
    cache = {
        item_id: np.asarray(vecteur, dtype=np.float32)
        for item_id, vecteur in conn.execute(
            "SELECT item_id, vecteur FROM embeddings "
            "WHERE modele = %s AND modele_version = %s AND item_id = ANY(%s)",
            (encodeur.nom, version, ids),
        ).fetchall()
    }

    manquants = [a for a in articles if a.item_id not in cache]
    if manquants:
        nouveaux = encodeur.encoder([texte_article(a.titre, a.extrait) for a in manquants])
        with conn.transaction():
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO embeddings (item_id, modele, modele_version, vecteur) "
                    "VALUES (%s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    [
                        (a.item_id, encodeur.nom, version, v.tolist())
                        for a, v in zip(manquants, nouveaux)
                    ],
                )
        for a, v in zip(manquants, nouveaux):
            cache[a.item_id] = np.asarray(v, dtype=np.float32)

    matrice = np.vstack([cache[i] for i in ids])
    bilan = {
        "en_cache": len(articles) - len(manquants),
        "calcules": len(manquants),
        "duree_s": round(time.monotonic() - debut, 2),
    }
    return matrice, bilan


def main() -> int:
    from gazette.connexion import ouvrir_connexion
    from gazette.themes import charger_config

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    config = charger_config()
    encodeur = EncodeurSentenceTransformers(
        config["embeddings"]["modele"],
        config["embeddings"]["revision"],
        config["embeddings"]["taille_lot"],
    )
    conn = ouvrir_connexion()
    conn.autocommit = True
    try:
        articles = lire_articles(
            conn, datetime.now(timezone.utc), config["donnees"]["fenetre_heures"]
        )
        _, bilan = vectoriser(conn, articles, encodeur)
    finally:
        conn.close()
    logger.info(json.dumps({"evenement": "vectorisation", "articles": len(articles), **bilan}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
