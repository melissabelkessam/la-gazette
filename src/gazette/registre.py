"""L'état des sources et le journal des collectes, dans PostgreSQL (tables sources, collectes).

RegistreMemoire fait la même chose en mémoire : il sert aux tests, sans base de données.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Protocol

import psycopg
from psycopg.rows import dict_row

# On collecte une source un peu avant sa fréquence pour ne pas glisser d'un passage
# (passage toutes les 10 min, source à 60 min : collectée au passage de la 60e minute).
TOLERANCE = timedelta(minutes=2)


@dataclass(frozen=True)
class Source:
    nom: str
    type: str
    url_flux: str
    actif: bool = True
    echecs_consecutifs: int = 0
    etag: str | None = None
    last_modified: str | None = None
    frequence_min: int = 60
    derniere_tentative: datetime | None = None
    derniere_reussite: datetime | None = None

    def est_due(self, maintenant: datetime) -> bool:
        if not self.actif:
            return False
        if self.derniere_tentative is None:
            return True
        return maintenant - self.derniere_tentative >= (
            timedelta(minutes=self.frequence_min) - TOLERANCE
        )


@dataclass(frozen=True)
class Bilan:
    """Ce qu'une collecte a fait pour une source : une ligne de journal."""

    source: str
    statut: str  # ok | non_modifie | echec | mise_en_sommeil | reseau_indisponible
    essais: int
    duree_ms: int
    http_statut: int | None = None
    recus: int = 0
    ecrits: int = 0
    ignores: int = 0
    erreur: str | None = None


class Registre(Protocol):
    def sources_dues(self, maintenant: datetime) -> list[Source]: ...
    def noter_tentative(self, nom: str, quand: datetime) -> None: ...
    def noter_reussite(
        self, nom: str, quand: datetime, etag: str | None, last_modified: str | None
    ) -> None: ...
    def noter_echec(self, nom: str, quand: datetime, erreur: str, sommeil: bool) -> None: ...
    def journaliser(self, passage: str, lance_le: datetime, bilan: Bilan) -> None: ...


def lire_sources_csv(chemin: Path) -> list[Source]:
    with chemin.open(encoding="utf-8-sig", newline="") as fichier:
        return [
            Source(
                nom=ligne["nom"],
                type=ligne["type"],
                url_flux=ligne["acces"],
                frequence_min=int(ligne.get("frequence_min") or 60),
            )
            for ligne in csv.DictReader(fichier)
        ]


class RegistrePostgres:
    def __init__(self, conn: psycopg.Connection):
        self.conn = conn

    def synchroniser(self, sources: list[Source]) -> None:
        """sources.csv -> table sources. Ajoute les nouvelles, met à jour adresse et fréquence.

        Ne touche jamais à l'état (actif, échecs, ETag) : une source endormie le reste
        jusqu'à ce qu'une personne la réveille (voir docs/donnees.md).
        """
        with self.conn.transaction():
            for s in sources:
                self.conn.execute(
                    """INSERT INTO sources (nom, type, url_flux, frequence_min)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (nom) DO UPDATE
                       SET type = EXCLUDED.type, url_flux = EXCLUDED.url_flux,
                           frequence_min = EXCLUDED.frequence_min""",
                    (s.nom, s.type, s.url_flux, s.frequence_min),
                )

    def sources_dues(self, maintenant: datetime) -> list[Source]:
        with self.conn.cursor(row_factory=dict_row) as cur:
            lignes = cur.execute(
                """SELECT nom, type, url_flux, actif, echecs_consecutifs, etag, last_modified,
                          frequence_min, derniere_tentative, derniere_reussite
                   FROM sources WHERE actif ORDER BY nom"""
            ).fetchall()
        return [s for s in (Source(**ligne) for ligne in lignes) if s.est_due(maintenant)]

    def noter_tentative(self, nom: str, quand: datetime) -> None:
        self.conn.execute(
            "UPDATE sources SET derniere_tentative = %s WHERE nom = %s", (quand, nom)
        )

    def noter_reussite(self, nom, quand, etag, last_modified) -> None:
        self.conn.execute(
            """UPDATE sources SET derniere_reussite = %s, echecs_consecutifs = 0,
                      derniere_erreur = NULL,
                      etag = COALESCE(%s, etag), last_modified = COALESCE(%s, last_modified)
               WHERE nom = %s""",
            (quand, etag, last_modified, nom),
        )

    def noter_echec(self, nom, quand, erreur, sommeil) -> None:
        self.conn.execute(
            """UPDATE sources SET echecs_consecutifs = echecs_consecutifs + 1,
                      derniere_erreur = %s,
                      actif = actif AND NOT %s,
                      endormie_le = CASE WHEN %s THEN %s ELSE endormie_le END
               WHERE nom = %s""",
            (erreur, sommeil, sommeil, quand, nom),
        )

    def journaliser(self, passage, lance_le, bilan: Bilan) -> None:
        self.conn.execute(
            """INSERT INTO collectes (passage, source, lance_le, statut, http_statut, essais,
                                      recus, ecrits, ignores, duree_ms, erreur)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)""",
            (passage, bilan.source, lance_le, bilan.statut, bilan.http_statut, bilan.essais,
             bilan.recus, bilan.ecrits, bilan.ignores, bilan.duree_ms, bilan.erreur),
        )


class RegistreMemoire:
    """Même comportement que RegistrePostgres, sans base : pour les tests."""

    def __init__(self, sources: list[Source]):
        self.sources = {s.nom: s for s in sources}
        self.journal: list[Bilan] = []

    def sources_dues(self, maintenant):
        return [s for s in self.sources.values() if s.est_due(maintenant)]

    def noter_tentative(self, nom, quand):
        self.sources[nom] = replace(self.sources[nom], derniere_tentative=quand)

    def noter_reussite(self, nom, quand, etag, last_modified):
        s = self.sources[nom]
        self.sources[nom] = replace(
            s, derniere_reussite=quand, echecs_consecutifs=0,
            etag=etag or s.etag, last_modified=last_modified or s.last_modified,
        )

    def noter_echec(self, nom, quand, erreur, sommeil):
        s = self.sources[nom]
        self.sources[nom] = replace(
            s, echecs_consecutifs=s.echecs_consecutifs + 1, actif=s.actif and not sommeil
        )

    def journaliser(self, passage, lance_le, bilan):
        self.journal.append(bilan)