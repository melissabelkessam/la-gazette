"""Orchestration Prefect : la collecte tourne toute seule, décrite ici, en code.

Un passage toutes les 10 minutes : chaque source n'est collectée que si elle est due
(Ouest-France toutes les 10 min, les autres toutes les 60 min : colonne frequence_min).
Après la collecte (TD 4) : nettoyage, rapport de qualité, contrôles et alerte.
Lancé par le service « orchestrateur » de docker-compose : python -m gazette.orchestration

Le pipeline n'est pas Prefect : chaque étape est une fonction ordinaire, appelable à la
main (python -m gazette.collecteur, gazette.nettoyage, gazette.rapport_qualite,
gazette.controles, ou gazette.qualite pour les trois à la suite).
"""

from __future__ import annotations

from prefect import flow, get_run_logger, task

from gazette import qualite
from gazette.collecteur import configurer_journaux, passage_complet

INTERVALLE_SECONDES = 600


@task(name="nettoyage")
def tache_nettoyage() -> dict:
    """Brut -> articles_propres et rejets (règles R01 à R10)."""
    bilan = qualite.etape_nettoyer()
    get_run_logger().info("Nettoyage : %s", bilan)
    return bilan


@task(name="rapport_qualite")
def tache_rapport() -> str:
    """Écrit rapports/qualite-AAAA-MM-JJ.md pour la journée en cours."""
    chemin = qualite.etape_rapport()
    get_run_logger().info("Rapport de qualité : %s", chemin)
    return chemin


@task(name="controles_qualite")
def tache_controles() -> dict:
    """Contrôles sur les vraies données ; alerte Discord si un fait est faux."""
    bilan = qualite.etape_controles()
    get_run_logger().info("Contrôles : %s", bilan)
    return bilan


@flow(name="collecte", retries=1, retry_delay_seconds=60)
def flow_collecte() -> dict:
    """Un passage : collecte, puis nettoyage, rapport et contrôles de qualité.

    Le détail par source est dans les journaux et la table collectes. Si la qualité
    échoue (base inaccessible par exemple), Prefect relance le flow une fois : la
    collecte est rejouable (zéro doublon), donc sans danger.
    """
    bilan = passage_complet()
    get_run_logger().info("Bilan du passage : %s", bilan)
    tache_nettoyage()
    tache_rapport()
    tache_controles()
    return bilan


if __name__ == "__main__":
    configurer_journaux()
    # serve() crée le déploiement « collecte-continue » et exécute les runs planifiés
    flow_collecte.serve(name="collecte-continue", interval=INTERVALLE_SECONDES)