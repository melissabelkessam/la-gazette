"""Envoi d'une alerte vers un webhook Discord (TD 4).

L'URL du webhook vient de la variable d'environnement ``DISCORD_WEBHOOK_URL``
(fichier ``.env`` ignoré par Git). Elle n'apparaît dans aucun log. Bibliothèque
standard seulement.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger("gazette.alerte")

LIMITE_DISCORD = 1900  # Discord refuse plus de 2000 caractères
USER_AGENT = "LaGazette-Efrei"  # Discord rejette (403) l'agent par défaut de Python


def envoyer_alerte(
    message: str,
    url: str | None = None,
    timeout: float = 10.0,
    ouvrir=urllib.request.urlopen,
) -> bool:
    """Poste ``message`` sur Discord. Renvoie True si l'envoi a réussi.

    Ne lève jamais d'exception : une alerte qui échoue ne doit pas casser le
    pipeline. ``ouvrir`` sert à remplacer le réseau dans les tests.
    """
    url = url or os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if not url:
        logger.warning(
            json.dumps({"evenement": "alerte_non_envoyee", "raison": "webhook_absent"})
        )
        return False

    corps = json.dumps(
        {"username": "La gazette", "content": message[:LIMITE_DISCORD]}
    ).encode("utf-8")
    requete = urllib.request.Request(
        url,
        data=corps,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with ouvrir(requete, timeout=timeout) as reponse:
            statut = getattr(reponse, "status", 200)
    except urllib.error.HTTPError as erreur:
        logger.error(
            json.dumps({"evenement": "alerte_echec", "http_statut": erreur.code})
        )
        return False
    except (urllib.error.URLError, OSError, ValueError) as erreur:
        logger.error(
            json.dumps(
                {"evenement": "alerte_echec", "erreur": type(erreur).__name__}
            )
        )
        return False

    ok = 200 <= statut < 300
    logger.info(json.dumps({"evenement": "alerte_envoyee", "http_statut": statut}))
    return ok
