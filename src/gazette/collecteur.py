"""Le collecteur : passe sur toutes les sources actives et dues, et dit ce qu'il a fait.

- Politesse : User-Agent honnête, ETag / Last-Modified, timeout, une source après l'autre.
- Reprise : une erreur transitoire (503, timeout...) est réessayée avec attente croissante.
- Sommeil : 3 échecs de suite mettent la source en sommeil (actif = false), avec un
  message d'alerte dans les journaux.
- Journaux : une ligne JSON par source (reçus, écrits, ignorés, durée), plus un bilan.

Lancer un passage à la main, sans Prefect : python -m gazette.collecteur
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

import httpx

from gazette.brut import DOSSIER_BRUT, construire_item, ecrire_si_nouveau
from gazette.collecte import USER_AGENT, lire_entrees
from gazette.registre import Bilan, Registre, Source

SEUIL_SOMMEIL = 3  # échecs consécutifs avant la mise en sommeil
ESSAIS = 3  # tentatives HTTP par passage pour une erreur transitoire
ATTENTE_BASE = 2.0  # secondes : 2 s, puis 4 s (backoff exponentiel)
TIMEOUT = httpx.Timeout(20.0, connect=10.0)
STATUTS_TRANSITOIRES = {408, 425, 429, 500, 502, 503, 504}

journal = logging.getLogger("gazette.collecteur")


class ErreurCollecte(Exception):
    def __init__(self, message: str, essais: int, http_statut: int | None = None):
        super().__init__(message)
        self.essais = essais
        self.http_statut = http_statut


@dataclass(frozen=True)
class Reponse:
    http_statut: int
    contenu: bytes
    etag: str | None
    last_modified: str | None
    essais: int


def telecharger(
    client: httpx.Client,
    source: Source,
    essais: int = ESSAIS,
    attente_base: float = ATTENTE_BASE,
    dormir: Callable[[float], None] = time.sleep,
) -> Reponse:
    """GET conditionnel avec reprise. Lève ErreurCollecte si la source a échoué."""
    entetes = {}
    if source.etag:
        entetes["If-None-Match"] = source.etag
    if source.last_modified:
        entetes["If-Modified-Since"] = source.last_modified

    for essai in range(1, essais + 1):
        try:
            r = client.get(source.url_flux, headers=entetes)
        except (httpx.TimeoutException, httpx.TransportError) as exc:
            cause, statut = f"réseau : {type(exc).__name__}", None
        else:
            if r.status_code in (200, 304):
                return Reponse(
                    r.status_code, r.content, r.headers.get("ETag"),
                    r.headers.get("Last-Modified"), essai,
                )
            if r.status_code not in STATUTS_TRANSITOIRES:
                # 404, 410, 403... : réessayer tout de suite ne changera rien
                raise ErreurCollecte(f"HTTP {r.status_code} (permanente)", essai, r.status_code)
            cause, statut = f"HTTP {r.status_code}", r.status_code
        if essai < essais:
            dormir(attente_base * 2 ** (essai - 1))
    raise ErreurCollecte(f"{cause} après {essais} essais (transitoire)", essais, statut)


def collecter_source(
    client: httpx.Client,
    registre: Registre,
    source: Source,
    dossier: Path,
    lance_le: datetime,
    **options,
) -> Bilan:
    """Collecte une source. Une réussite est notée tout de suite ; un échec est décidé
    par executer_passage, qui sait si c'est la source ou notre propre réseau qui est tombé."""
    debut = time.monotonic()
    registre.noter_tentative(source.nom, lance_le)

    def duree() -> int:
        return round((time.monotonic() - debut) * 1000)

    try:
        reponse = telecharger(client, source, **options)
        if reponse.http_statut == 304:
            bilan = Bilan(source.nom, "non_modifie", reponse.essais, duree(), 304)
        else:
            entrees, illisible = lire_entrees(reponse.contenu, source.nom)
            if illisible:
                raise ErreurCollecte("flux illisible (ni RSS ni Atom)", reponse.essais, 200)
            recupere_le = datetime.now(timezone.utc).isoformat()
            ecrits = sum(
                ecrire_si_nouveau(dossier, construire_item(article, payload, recupere_le))
                for article, payload in entrees
            )
            bilan = Bilan(
                source.nom, "ok", reponse.essais, duree(), 200,
                recus=len(entrees), ecrits=ecrits, ignores=len(entrees) - ecrits,
            )
        registre.noter_reussite(source.nom, lance_le, reponse.etag, reponse.last_modified)
        return bilan
    except Exception as exc:  # une source qui plante ne doit jamais arrêter les autres
        if not isinstance(exc, ErreurCollecte):
            exc = ErreurCollecte(f"erreur inattendue : {type(exc).__name__}: {exc}", 1)
        return Bilan(source.nom, "echec", exc.essais, duree(), exc.http_statut, erreur=str(exc))


def executer_passage(
    registre: Registre,
    dossier: Path = DOSSIER_BRUT,
    client: httpx.Client | None = None,
    maintenant: datetime | None = None,
    **options,
) -> dict:
    """Un passage : toutes les sources actives et dues, l'une après l'autre (jamais en
    parallèle sur un éditeur), puis une ligne de journal par source et un bilan."""
    lance_le = maintenant or datetime.now(timezone.utc)
    passage = str(uuid.uuid4())
    sources = registre.sources_dues(lance_le)
    proprio = client is None
    client = client or httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, follow_redirects=True
    )
    try:
        bilans = [
            collecter_source(client, registre, s, dossier, lance_le, **options) for s in sources
        ]
    finally:
        if proprio:
            client.close()

    # Toutes les sources injoignables, sans aucune réponse HTTP : c'est notre machine qui
    # n'a plus Internet (Wi-Fi coupé, PC en veille...), pas les éditeurs. On ne compte pas
    # ces échecs, sinon une nuit sans réseau endormirait toutes les sources.
    panne_locale = len(bilans) >= 2 and all(
        b.statut == "echec" and b.http_statut is None for b in bilans
    )

    for rang, (source, bilan) in enumerate(zip(sources, bilans)):
        if bilan.statut == "echec":
            if panne_locale:
                bilan = replace(bilan, statut="reseau_indisponible")
            else:
                sommeil = source.echecs_consecutifs + 1 >= SEUIL_SOMMEIL
                registre.noter_echec(source.nom, lance_le, bilan.erreur, sommeil)
                if sommeil:
                    bilan = replace(bilan, statut="mise_en_sommeil")
        registre.journaliser(passage, lance_le, bilan)
        journaliser_ligne(passage, source, bilan)
        bilans[rang] = bilan

    compteurs = {
        "evenement": "bilan_passage",
        "passage": passage,
        "sources": len(bilans),
        "ok": sum(b.statut in ("ok", "non_modifie") for b in bilans),
        "echecs": sum(b.statut == "echec" for b in bilans),
        "mises_en_sommeil": sum(b.statut == "mise_en_sommeil" for b in bilans),
        "reseau_indisponible": panne_locale,
        "recus": sum(b.recus for b in bilans),
        "ecrits": sum(b.ecrits for b in bilans),
        "ignores": sum(b.ignores for b in bilans),
    }
    journal.log(
        logging.ERROR if panne_locale else logging.INFO,
        json.dumps(compteurs, ensure_ascii=False),
    )
    return compteurs


def journaliser_ligne(passage: str, source: Source, bilan: Bilan) -> None:
    """Une ligne JSON par source ; une alerte en plus quand une source s'endort."""
    niveau = {"ok": logging.INFO, "non_modifie": logging.INFO}.get(bilan.statut, logging.WARNING)
    journal.log(niveau, json.dumps(
        {"evenement": "collecte_source", "passage": passage, **asdict(bilan)},
        ensure_ascii=False,
    ))
    if bilan.statut == "mise_en_sommeil":
        journal.error(json.dumps({
            "evenement": "ALERTE_source_en_sommeil",
            "source": source.nom,
            "echecs_consecutifs": source.echecs_consecutifs + 1,
            "erreur": bilan.erreur,
            "reveil": "UPDATE sources SET actif = true, echecs_consecutifs = 0 "
                      f"WHERE nom = '{source.nom}';",
        }, ensure_ascii=False))


def passage_complet(chemin_sources: Path = Path("sources.csv")) -> dict:
    """Ce que lance l'orchestrateur : migrations, sources.csv -> table, puis un passage."""
    import psycopg

    from gazette.migrations import appliquer_migrations
    from gazette.registre import RegistrePostgres, lire_sources_csv

    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        appliquer_migrations(conn)
        registre = RegistrePostgres(conn)
        registre.synchroniser(lire_sources_csv(chemin_sources))
        return executer_passage(registre)


def configurer_journaux() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)


if __name__ == "__main__":
    configurer_journaux()
    passage_complet()