"""Passage de qualité complet : nettoyage, rapport, contrôles (TD 4).

Chaque étape ouvre sa propre connexion et reste appelable seule. Prefect
n'appelle que ces fonctions (voir LISEZMOI_TD4.md pour le branchement) :
``python -m gazette.qualite`` marche aussi sans orchestrateur.
"""

from __future__ import annotations

import json
import logging

from gazette.connexion import ouvrir_connexion
from gazette.controles import executer_controles
from gazette.nettoyage import nettoyer
from gazette.rapport_qualite import ecrire_rapport

logger = logging.getLogger("gazette.qualite")


def _avec_connexion(fonction):
    conn = ouvrir_connexion()
    try:
        return fonction(conn)
    finally:
        conn.close()


def etape_nettoyer() -> dict:
    return _avec_connexion(nettoyer)


def etape_rapport() -> str:
    return str(_avec_connexion(ecrire_rapport))


def etape_controles() -> dict:
    return _avec_connexion(executer_controles)


def passage_qualite() -> dict:
    """Nettoyage, puis rapport, puis contrôles. Renvoie un résumé."""
    resume = {
        "nettoyage": etape_nettoyer(),
        "rapport": etape_rapport(),
        "controles": etape_controles(),
    }
    evenement = {
        "evenement": "passage_qualite",
        "gardes": resume["nettoyage"]["gardes"],
        "rejetes": resume["nettoyage"]["rejetes"],
        "echecs": resume["controles"]["echecs"],
    }
    logger.info(json.dumps(evenement, ensure_ascii=False))
    return resume


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    passage_qualite()
