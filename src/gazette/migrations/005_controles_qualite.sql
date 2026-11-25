-- TD 4 : résultat de chaque contrôle de qualité (le TD 8 viendra les lire).
CREATE TABLE IF NOT EXISTS controles_qualite (
    id               BIGSERIAL PRIMARY KEY,
    horodatage       TIMESTAMPTZ NOT NULL DEFAULT now(),
    nom              TEXT NOT NULL,
    portee           TEXT NOT NULL DEFAULT 'global',
    valeur           DOUBLE PRECISION,
    seuil            DOUBLE PRECISION,
    ok               BOOLEAN NOT NULL,
    alerte_envoyee   BOOLEAN NOT NULL DEFAULT FALSE,
    detail           TEXT
);

CREATE INDEX IF NOT EXISTS idx_controles_nom_portee
    ON controles_qualite (nom, portee, horodatage DESC);
