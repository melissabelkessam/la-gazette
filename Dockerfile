# --- Étape 1 : construction (on installe les dépendances) ---
FROM python:3.13-slim AS construction
WORKDIR /build
COPY requirements.txt pyproject.toml ./
COPY src/ src/
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt .

# --- Étape 2 : image finale, petite (seulement le résultat de l'étape 1) ---
FROM python:3.13-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1
# Un utilisateur sans droits d'administrateur
RUN useradd --create-home --uid 1000 gazette
WORKDIR /app
COPY --from=construction /install /usr/local
COPY sources.csv ./
RUN mkdir -p /app/data && chown gazette:gazette /app/data
USER gazette
ENTRYPOINT ["python", "-m", "gazette.collecte"]
CMD ["--source", "Sud Ouest"]