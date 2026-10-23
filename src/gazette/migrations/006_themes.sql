-- TD 5 : thèmes du jour (couche Gold) et traçage des runs de regroupement.

-- Cache des vecteurs : un article n'est vectorisé qu'une fois par version de modèle.
CREATE TABLE IF NOT EXISTS embeddings (
    item_id          TEXT NOT NULL REFERENCES articles_propres (item_id) ON DELETE CASCADE,
    modele           TEXT NOT NULL,
    modele_version   TEXT NOT NULL,
    vecteur          REAL[] NOT NULL,
    cree_le          TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (item_id, modele, modele_version)
);

-- Un run de regroupement = une ligne. run_id est l'identifiant partagé avec MLflow.
CREATE TABLE IF NOT EXISTS runs_themes (
    run_id            TEXT PRIMARY KEY,
    mlflow_run_id     TEXT,
    debut             TIMESTAMPTZ NOT NULL DEFAULT now(),
    fin               TIMESTAMPTZ,
    statut            TEXT NOT NULL,          -- en_cours, ok, trop_peu_articles, echec
    fenetre_debut     TIMESTAMPTZ NOT NULL,
    fenetre_fin       TIMESTAMPTZ NOT NULL,
    nb_articles       INTEGER NOT NULL,
    hash_entree       TEXT NOT NULL,          -- SHA-256 des articles en entrée
    modele            TEXT NOT NULL,
    modele_version    TEXT NOT NULL,
    hash_config       TEXT NOT NULL,          -- SHA-256 de config/clustering.yaml
    parametres        JSONB NOT NULL,
    metriques         JSONB,
    erreur            TEXT
);

CREATE INDEX IF NOT EXISTS idx_runs_themes_fin ON runs_themes (statut, fin DESC);

CREATE TABLE IF NOT EXISTS themes (
    run_id      TEXT NOT NULL REFERENCES runs_themes (run_id) ON DELETE CASCADE,
    theme       INTEGER NOT NULL,             -- numéro du thème dans le run
    nom         TEXT NOT NULL,
    mots_cles   TEXT[] NOT NULL,
    taille      INTEGER NOT NULL,
    PRIMARY KEY (run_id, theme)
);

-- Les articles classés en bruit (thème -1 de HDBSCAN) ne sont pas rattachés.
CREATE TABLE IF NOT EXISTS articles_themes (
    run_id    TEXT NOT NULL,
    theme     INTEGER NOT NULL,
    item_id   TEXT NOT NULL REFERENCES articles_propres (item_id) ON DELETE CASCADE,
    PRIMARY KEY (run_id, item_id),
    FOREIGN KEY (run_id, theme) REFERENCES themes (run_id, theme) ON DELETE CASCADE
);

-- Les thèmes du jour = ceux du dernier run réussi.
CREATE OR REPLACE VIEW themes_du_jour AS
SELECT t.run_id, t.theme, t.nom, t.mots_cles, t.taille, r.fin AS calcule_le
FROM themes t
JOIN runs_themes r ON r.run_id = t.run_id
WHERE t.run_id = (
    SELECT run_id FROM runs_themes WHERE statut = 'ok' ORDER BY fin DESC LIMIT 1
)
ORDER BY t.taille DESC;
