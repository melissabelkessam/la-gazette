-- 001 : la table des sources, son état de collecte.
-- Une migration n'est jamais modifiée une fois commitée : on en ajoute une nouvelle.

CREATE TABLE sources (
    nom                 TEXT PRIMARY KEY,
    type                TEXT NOT NULL CHECK (type IN ('PQN', 'PQR')),
    url_flux            TEXT NOT NULL,
    actif               BOOLEAN NOT NULL DEFAULT TRUE,
    derniere_reussite   TIMESTAMPTZ,
    echecs_consecutifs  INTEGER NOT NULL DEFAULT 0 CHECK (echecs_consecutifs >= 0),
    etag                TEXT,
    last_modified       TEXT,
    -- en plus du minimum demandé : fréquence par source (cadrage, section 6.1)
    frequence_min       INTEGER NOT NULL DEFAULT 60 CHECK (frequence_min > 0),
    derniere_tentative  TIMESTAMPTZ,
    derniere_erreur     TEXT,
    endormie_le         TIMESTAMPTZ
);