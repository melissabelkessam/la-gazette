"""Orchestration Prefect : la collecte tourne toute seule, décrite ici, en code.

Un passage toutes les 10 minutes : chaque source n'est collectée que si elle est due
(Ouest-France toutes les 10 min, les autres toutes les 60 min : colonne frequence_min).
Lancé par le service « orchestrateur » de docker-compose : python -m gazette.orchestration
"""

from __future__ import annotations

from prefect import flow, get_run_logger

from gazette.collecteur import configurer_journaux, passage_complet

INTERVALLE_SECONDES = 600


@flow(name="collecte", retries=1, retry_delay_seconds=60)
def flow_collecte() -> dict:
    """Un passage de collecte. Le détail par source est dans les journaux et la table collectes."""
    bilan = passage_complet()
    get_run_logger().info("Bilan du passage : %s", bilan)
    return bilan


if __name__ == "__main__":
    configurer_journaux()
    # serve() crée le déploiement « collecte-continue » et exécute les runs planifiés
    flow_collecte.serve(name="collecte-continue", interval=INTERVALLE_SECONDES)