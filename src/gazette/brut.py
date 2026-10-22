"""Stockage brut : un fichier JSON par article, sous articles_bruts/<source>/<id>.json.

La clé naturelle d'un article est (source, lien normalisé). Son id en est l'empreinte :
un article déjà écrit a déjà son fichier, il n'est jamais réécrit (idempotence).
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from gazette.collecte import en_nom_de_fichier

DOSSIER_BRUT = Path(os.environ.get("GAZETTE_DOSSIER_BRUT", "data/articles_bruts"))


def calculer_id(source: str, lien_normalise: str) -> str:
    """Empreinte SHA-256 de la clé naturelle (source, lien)."""
    return hashlib.sha256(f"{source}\n{lien_normalise}".encode("utf-8")).hexdigest()


def construire_item(article: dict, payload: dict, recupere_le: str) -> dict:
    """L'enregistrement brut, avec les champs décrits dans docs/donnees.md."""
    return {
        "id": calculer_id(article["source"], article["lien"]),
        "source": article["source"],
        "lien": article["lien"],
        "titre": article["titre"],
        "resume": article["extrait"],
        "publie_le": article["date_publication"],
        "recupere_le": recupere_le,
        "rubrique": article["rubrique"],
        "payload": payload,
    }


def chemin_item(dossier: Path, item: dict) -> Path:
    return dossier / en_nom_de_fichier(item["source"]) / f"{item['id']}.json"


def ecrire_si_nouveau(dossier: Path, item: dict) -> bool:
    """Écrit l'item s'il n'existe pas encore. Renvoie True s'il a été écrit.

    Écriture atomique (fichier temporaire puis renommage) : une collecte coupée
    en plein milieu ne laisse jamais un fichier JSON à moitié écrit.
    """
    chemin = chemin_item(dossier, item)
    if chemin.exists():
        return False
    chemin.parent.mkdir(parents=True, exist_ok=True)
    temporaire = chemin.with_suffix(".json.tmp")
    temporaire.write_text(json.dumps(item, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporaire, chemin)
    return True