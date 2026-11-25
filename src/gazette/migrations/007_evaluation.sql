-- TD 6 : évaluation du modèle, registre de versions, relecture humaine.

-- Verdict d'évaluation d'un run (1 ligne par run évalué).
-- verdict : 'ok' (publié) | 'revue' (publié mais à surveiller, dérive) | 'recale' (NON publié).
-- Le statut du run dans runs_themes reflète la publication : 'ok' si publié, 'recale' sinon.
CREATE TABLE IF NOT EXISTS evaluations_themes (
    run_id        TEXT PRIMARY KEY REFERENCES runs_themes (run_id) ON DELETE CASCADE,
    verdict       TEXT NOT NULL,              -- ok, revue, recale
    publie        BOOLEAN NOT NULL,           -- les thèmes de ce run sont-ils en base ?
    derive        BOOLEAN NOT NULL DEFAULT false,
    seuils        JSONB NOT NULL,             -- copie des seuils appliqués (traçabilité)
    details       JSONB NOT NULL,             -- franchissements + raisons de dérive
    evalue_le     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Registre des versions du modèle. Une version = un jeu de paramètres (clustering.yaml).
-- statut : 'candidat' (a passé les seuils) | 'production' (en service) | 'archivee'.
-- Au plus UNE version en production à la fois (index partiel ci-dessous).
CREATE TABLE IF NOT EXISTS versions_modele (
    version       TEXT PRIMARY KEY,           -- étiquette lisible : v1, v2, ...
    hash_config   TEXT NOT NULL,              -- SHA-256 des paramètres (= hash_config du run)
    parametres    JSONB NOT NULL,             -- copie figée de clustering.yaml
    run_id        TEXT REFERENCES runs_themes (run_id) ON DELETE SET NULL,  -- run qui l'a validée
    statut        TEXT NOT NULL DEFAULT 'candidat',
    cree_le       TIMESTAMPTZ NOT NULL DEFAULT now(),
    promue_le     TIMESTAMPTZ,
    par_qui       TEXT,
    note          TEXT
);

-- Garantit qu'il n'y a jamais deux versions 'production' en même temps.
CREATE UNIQUE INDEX IF NOT EXISTS idx_une_seule_production
    ON versions_modele (statut) WHERE statut = 'production';

-- Relecture humaine : un échantillon d'articles d'un run, chacun jugé bien placé ou non.
CREATE TABLE IF NOT EXISTS relectures (
    id          BIGSERIAL PRIMARY KEY,
    run_id      TEXT NOT NULL REFERENCES runs_themes (run_id) ON DELETE CASCADE,
    item_id     TEXT NOT NULL,
    theme       INTEGER NOT NULL,
    correct     BOOLEAN NOT NULL,             -- l'article est-il bien dans ce thème ?
    par_qui     TEXT,
    le          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_relectures_run ON relectures (run_id);

-- « Quelle version tourne ce matin, et avec quels paramètres ? » -> une requête.
CREATE OR REPLACE VIEW version_en_service AS
SELECT version, parametres, hash_config, run_id, promue_le, par_qui
FROM versions_modele
WHERE statut = 'production';