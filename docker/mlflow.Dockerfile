# Serveur MLflow de La gazette (TD 5) : historique des runs de thèmes et leurs artefacts.
# Image construite ici (version figée) plutôt qu'une image toute faite : même version que
# le client mlflow-skinny de l'orchestrateur.
FROM python:3.13-slim
RUN pip install --no-cache-dir mlflow==3.17.2 \
    && useradd --create-home --uid 1000 mlflow \
    && mkdir -p /mlflow/artifacts && chown -R mlflow:mlflow /mlflow
USER mlflow
EXPOSE 5000
# --allowed-hosts : le serveur refuse par défaut un nom d'hôte inconnu ; l'orchestrateur
# l'appelle par son nom de service Docker (mlflow:5000), le navigateur par localhost:5000.
CMD ["mlflow", "server", "--host", "0.0.0.0", "--port", "5000", \
     "--backend-store-uri", "sqlite:////mlflow/mlflow.db", \
     "--artifacts-destination", "/mlflow/artifacts", "--serve-artifacts", \
     "--allowed-hosts", "mlflow,mlflow:5000,localhost,localhost:5000,127.0.0.1,127.0.0.1:5000"]
