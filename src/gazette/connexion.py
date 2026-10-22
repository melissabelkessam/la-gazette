"""Ouverture d'une connexion PostgreSQL pour les modules du TD 4.

SI ``registre.py`` (TD 3) a déjà une fonction de connexion, remplacer le corps de
``ouvrir_connexion`` par un appel à celle-ci : ne pas avoir deux façons de se
connecter. Les requêtes du TD 4 n'utilisent que l'API standard (curseur, ``%s``),
elles marchent avec psycopg 3 comme avec psycopg2.
"""

from __future__ import annotations

import os


def url_base() -> str:
    url = os.environ.get("GAZETTE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError(
            "Variable GAZETTE_DATABASE_URL absente : impossible de joindre PostgreSQL."
        )
    return url


def ouvrir_connexion(url: str | None = None):
    """Connexion PostgreSQL (psycopg 3 de préférence, sinon psycopg2)."""
    url = url or url_base()
    try:
        import psycopg

        return psycopg.connect(url)
    except ImportError:
        import psycopg2

        return psycopg2.connect(url)
