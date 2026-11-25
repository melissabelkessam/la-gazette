"""Lecture d'un flux RSS ou Atom : ne garde que ce que le bornage autorise.

Outil manuel pour tester une source : python -m gazette.collecte --source "Sud Ouest"
La collecte planifiée de toutes les sources est dans gazette.collecteur.
"""

from __future__ import annotations

import argparse
import calendar
import csv
import hashlib
import html
import json
import re
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import feedparser
import httpx

# Notre robot se présente honnêtement (cf. robots.txt des journaux)
USER_AGENT = "LaGazette-Efrei/0.1 (projet etudiant M2 Efrei)"
DOSSIER_SORTIE = Path("data/brut")
BALISE_HTML = re.compile(r"<[^>]+>")


def normaliser_lien(lien: str) -> str:
    """Retire les paramètres de suivi (utm_*) et l'ancre (#...) d'un lien."""
    morceaux = urlsplit(lien.strip())
    parametres = [
        (cle, valeur)
        for cle, valeur in parse_qsl(morceaux.query, keep_blank_values=True)
        if not cle.lower().startswith("utm_")
    ]
    return urlunsplit(
        (morceaux.scheme, morceaux.netloc, morceaux.path, urlencode(parametres), "")
    )


def calculer_item_id(lien_normalise: str) -> str:
    """Identifiant stable d'un article : empreinte SHA-256 de son lien normalisé."""
    return hashlib.sha256(lien_normalise.encode("utf-8")).hexdigest()


def nettoyer_texte(texte: str | None) -> str | None:
    """Enlève les balises HTML, les entités (&amp;...) et les espaces en trop."""
    if not texte:
        return None
    sans_balises = BALISE_HTML.sub(" ", texte)
    propre = " ".join(html.unescape(sans_balises).split())
    return propre or None


def date_en_utc(entree: dict) -> str | None:
    """Date de publication convertie en UTC, au format ISO (ex. 2026-10-20T11:58:29+00:00)."""
    date = entree.get("published_parsed") or entree.get("updated_parsed")
    if date is None:
        return None
    return datetime.fromtimestamp(calendar.timegm(date), tz=timezone.utc).isoformat()


def extrait_autorise(entree: dict) -> str | None:
    """L'extrait vient de <description>, jamais de <content:encoded> (texte intégral)."""
    resume = entree.get("summary")
    textes_integraux = [c.get("value") for c in entree.get("content", [])]
    if resume in textes_integraux:
        # feedparser a recopié le texte intégral faute de description : on le refuse
        return None
    return nettoyer_texte(resume)


# Champs bruts gardés dans le payload, tels que reçus (RSS 2.0 ou Atom).
# Liste blanche : auteur, texte intégral (content) et images n'y sont jamais.
CHAMPS_PAYLOAD = ("title", "link", "id", "summary", "published", "updated")


def payload_autorise(entree: dict) -> dict:
    """L'item tel que reçu, réduit aux seuls champs autorisés par le bornage."""
    # dict.get : lit le champ tel quel, sans les correspondances automatiques de feedparser
    payload = {cle: dict.get(entree, cle) for cle in CHAMPS_PAYLOAD if dict.get(entree, cle)}
    if payload.get("summary") and extrait_autorise(entree) is None:
        # le résumé n'est en fait que le texte intégral : on ne le garde pas
        del payload["summary"]
    rubriques = [t.get("term") for t in entree.get("tags", []) if t.get("term")]
    if rubriques:
        payload["tags"] = rubriques
    return payload


def lire_entrees(contenu: bytes, source: str) -> tuple[list[tuple[dict, dict]], bool]:
    """Lit un flux et renvoie ([(article, payload), ...], flux_illisible).

    flux_illisible est vrai quand feedparser n'a rien pu lire de valable :
    réponse qui n'est pas du XML, flux cassé, page d'erreur HTML...
    """
    flux = feedparser.parse(contenu)
    resultats = []
    for entree in flux.entries:
        article = article_autorise(entree, source)
        if article is not None:
            resultats.append((article, payload_autorise(entree)))
    illisible = not flux.entries and (bool(flux.bozo) or not flux.get("version"))
    return resultats, illisible


def parser_flux(contenu: bytes, source: str) -> list[dict]:
    """Lit un flux RSS et ne garde QUE les champs autorisés par le bornage.

    Tout le reste (auteur, texte intégral, images...) est ignoré par construction.
    """
    articles, _ = lire_entrees(contenu, source)
    return [article for article, _ in articles]


def article_autorise(entree: dict, source: str) -> dict | None:
    """Un article normalisé, ou None s'il n'a ni lien ni identifiant."""
    lien_brut = entree.get("link") or entree.get("id")
    if not lien_brut:
        return None
    lien = normaliser_lien(lien_brut)
    rubriques = [t.get("term") for t in entree.get("tags", []) if t.get("term")]
    return {
        "item_id": calculer_item_id(lien),
        "source": source,
        "titre": nettoyer_texte(entree.get("title")),
        "extrait": extrait_autorise(entree),
        "lien": lien,
        "date_publication": date_en_utc(entree),
        "rubrique": rubriques[0] if rubriques else None,
    }


def telecharger(url: str) -> bytes:
    """Télécharge un flux en se présentant honnêtement."""
    reponse = httpx.get(
        url, headers={"User-Agent": USER_AGENT}, timeout=20, follow_redirects=True
    )
    reponse.raise_for_status()
    return reponse.content


def lire_source(nom: str, chemin_sources: Path = Path("sources.csv")) -> dict:
    """Cherche une source par son nom dans sources.csv."""
    with chemin_sources.open(encoding="utf-8-sig", newline="") as fichier:
        for ligne in csv.DictReader(fichier):
            if ligne["nom"] == nom:
                return ligne
    raise ValueError(f"Source inconnue dans {chemin_sources} : {nom}")


def en_nom_de_fichier(nom: str) -> str:
    """'Les Échos' -> 'les-echos'."""
    sans_accents = (
        unicodedata.normalize("NFKD", nom).encode("ascii", "ignore").decode("ascii")
    )
    return re.sub(r"[^a-z0-9]+", "-", sans_accents.lower()).strip("-")


def main(argv: list[str] | None = None) -> int:
    parseur = argparse.ArgumentParser(description="Collecte une source de sources.csv")
    parseur.add_argument("--source", default="Sud Ouest", help="nom dans sources.csv")
    args = parseur.parse_args(argv)

    source = lire_source(args.source)
    articles = parser_flux(telecharger(source["acces"]), source["nom"])

    horodatage = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    chemin = DOSSIER_SORTIE / f"{en_nom_de_fichier(source['nom'])}_{horodatage}.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(
        json.dumps(articles, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"{len(articles)} articles écrits dans {chemin}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())