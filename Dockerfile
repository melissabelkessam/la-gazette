# --- Étape 1 : construction (on installe les dépendances) ---
FROM python:3.13-slim AS construction
WORKDIR /build
COPY requirements.txt ./
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# --- Étape 2 : image finale, petite (seulement le résultat de l'étape 1) ---
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    HF_HOME=/app/modeles \
    GAZETTE_CONFIG_CLUSTERING=/app/config/clustering.yaml \
    MLFLOW_DISABLE_AGENT_HINT=1
# Un utilisateur sans droits d'administrateur
RUN useradd --create-home --uid 1000 gazette
WORKDIR /app
COPY --from=construction /install /usr/local
# Le code reste sous /app : Prefect exige que le fichier du flow soit dans le dossier de travail
COPY src/ src/
COPY sources.csv ./
COPY config/ config/
# modeles/ : cache du modèle d'embeddings (volume Docker, téléchargé une seule fois)
RUN mkdir -p /app/data/articles_bruts /app/modeles \
    && chown -R gazette:gazette /app/data /app/modeles
USER gazette
# Par défaut : l'orchestrateur Prefect (collecte toutes les 10 min).
# Un passage à la main : docker compose run --rm orchestrateur gazette.collecteur
ENTRYPOINT ["python", "-m"]
CMD ["gazette.orchestration"]