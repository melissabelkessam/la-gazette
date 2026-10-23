"""Traçage des runs de regroupement dans MLflow (TD 5).

Chaque run envoie à MLflow : les paramètres (fichier de config aplati), la fenêtre de
données et son empreinte, le modèle et sa version, les métriques, et trois artefacts
(config_clustering.yaml, themes.json, affectations.json).

MLflow sert à comparer les runs entre eux (TD 6). La table ``runs_themes`` de PostgreSQL
garde, elle, le lien entre un run et les thèmes en base. Si MLflow est injoignable, le run
continue : il reste tracé dans ``runs_themes`` et l'incident est journalisé.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any

logger = logging.getLogger("gazette.suivi_runs")

EXPERIENCE = "gazette-themes"


def aplatir(dico: dict, prefixe: str = "") -> dict[str, Any]:
    """{'a': {'b': 1}} -> {'a.b': 1} : MLflow n'accepte que des paramètres à plat."""
    plat: dict[str, Any] = {}
    for cle, valeur in dico.items():
        nom = f"{prefixe}{cle}"
        if isinstance(valeur, dict):
            plat.update(aplatir(valeur, f"{nom}."))
        else:
            plat[nom] = valeur
    return plat


class SuiviNul:
    """Aucun suivi externe (MLflow non configuré ou en panne)."""

    actif = False
    mlflow_run_id: str | None = None

    def demarrer(self, nom: str, tags: dict) -> None:
        pass

    def parametres(self, params: dict) -> None:
        pass

    def metriques(self, metriques: dict) -> None:
        pass

    def artefact_texte(self, contenu: str, chemin: str) -> None:
        pass

    def artefact_json(self, objet: Any, chemin: str) -> None:
        pass

    def terminer(self, statut: str) -> None:
        pass


class SuiviMLflow(SuiviNul):
    """Suivi dans un serveur MLflow (``MLFLOW_TRACKING_URI``)."""

    actif = True

    def __init__(self, uri: str, experience: str = EXPERIENCE):
        import mlflow

        self._mlflow = mlflow
        mlflow.set_tracking_uri(uri)
        mlflow.set_experiment(experience)

    def demarrer(self, nom: str, tags: dict) -> None:
        # L'orchestrateur tourne en continu : un run resté ouvert après une panne
        # bloquerait tous les suivants (« run already active »). On le clôt d'abord.
        if self._mlflow.active_run() is not None:
            self._mlflow.end_run(status="KILLED")
        run = self._mlflow.start_run(run_name=nom, tags={k: str(v) for k, v in tags.items()})
        self.mlflow_run_id = run.info.run_id

    def parametres(self, params: dict) -> None:
        self._mlflow.log_params({k: str(v)[:500] for k, v in aplatir(params).items()})

    def metriques(self, metriques: dict) -> None:
        self._mlflow.log_metrics(
            {k: float(v) for k, v in metriques.items() if isinstance(v, (int, float))}
        )

    def artefact_texte(self, contenu: str, chemin: str) -> None:
        self._mlflow.log_text(contenu, chemin)

    def artefact_json(self, objet: Any, chemin: str) -> None:
        self._mlflow.log_dict(objet, chemin)

    def terminer(self, statut: str) -> None:
        self._mlflow.end_run(status="FINISHED" if statut != "echec" else "FAILED")


class SuiviTolerant(SuiviNul):
    """Enveloppe : une panne de MLflow ne fait jamais échouer le regroupement."""

    def __init__(self, interne: SuiviNul):
        self._interne = interne
        self.actif = interne.actif

    @property
    def mlflow_run_id(self) -> str | None:  # type: ignore[override]
        return self._interne.mlflow_run_id if self.actif else None

    def _appel(self, methode: str, *args) -> None:
        if not self.actif:
            return
        try:
            getattr(self._interne, methode)(*args)
        except Exception as erreur:  # noqa: BLE001 - toute panne du suivi est tolérée
            self.actif = False
            logger.warning(json.dumps({
                "evenement": "mlflow_indisponible",
                "etape": methode,
                "erreur": f"{type(erreur).__name__}: {erreur}"[:300],
            }, ensure_ascii=False))

    def demarrer(self, nom, tags):
        self._appel("demarrer", nom, tags)

    def parametres(self, params):
        self._appel("parametres", params)

    def metriques(self, metriques):
        self._appel("metriques", metriques)

    def artefact_texte(self, contenu, chemin):
        self._appel("artefact_texte", contenu, chemin)

    def artefact_json(self, objet, chemin):
        self._appel("artefact_json", objet, chemin)

    def terminer(self, statut):
        self._appel("terminer", statut)


def suivi_depuis_environnement() -> SuiviNul:
    """MLflow si ``MLFLOW_TRACKING_URI`` est défini, sinon aucun suivi externe."""
    uri = os.environ.get("MLFLOW_TRACKING_URI")
    if not uri:
        return SuiviNul()
    try:
        return SuiviTolerant(SuiviMLflow(uri))
    except Exception as erreur:  # noqa: BLE001
        logger.warning(json.dumps({
            "evenement": "mlflow_indisponible",
            "etape": "connexion",
            "erreur": f"{type(erreur).__name__}: {erreur}"[:300],
        }, ensure_ascii=False))
        return SuiviNul()
