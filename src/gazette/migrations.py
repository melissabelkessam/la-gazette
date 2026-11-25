"""Migrations SQL versionnées : chaque fichier migrations/NNN_nom.sql est appliqué une fois.

Les versions appliquées sont notées dans la table schema_migrations. Relancer ne refait rien.
Usage : python -m gazette.migrations
"""

from __future__ import annotations

import os
from importlib import resources

import psycopg

VERROU = 4_208_001  # verrou consultatif : deux conteneurs ne migrent pas en même temps


def fichiers_migration() -> list[tuple[str, str]]:
    """[(version, sql)] triés : '001_sources', '002_collectes'..."""
    dossier = resources.files("gazette") / "migrations"
    fichiers = sorted(f for f in dossier.iterdir() if f.name.endswith(".sql"))
    return [(f.name.removesuffix(".sql"), f.read_text(encoding="utf-8")) for f in fichiers]


def appliquer_migrations(conn: psycopg.Connection) -> list[str]:
    """Applique les migrations manquantes, en une transaction. Renvoie les nouvelles."""
    nouvelles = []
    with conn.transaction():
        conn.execute("SELECT pg_advisory_xact_lock(%s)", (VERROU,))
        conn.execute(
            """CREATE TABLE IF NOT EXISTS schema_migrations (
                   version TEXT PRIMARY KEY,
                   appliquee_le TIMESTAMPTZ NOT NULL DEFAULT now())"""
        )
        deja = {ligne[0] for ligne in conn.execute("SELECT version FROM schema_migrations")}
        for version, sql in fichiers_migration():
            if version in deja:
                continue
            conn.execute(sql)
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
            nouvelles.append(version)
    return nouvelles


def main() -> int:
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        nouvelles = appliquer_migrations(conn)
    print(f"Migrations appliquées : {', '.join(nouvelles) or 'aucune, base à jour'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())