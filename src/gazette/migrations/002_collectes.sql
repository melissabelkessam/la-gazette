-- 002 : le journal des collectes, une ligne par source et par passage.
-- Il répond à « combien d'articles par source, et lesquelles ont dormi ? ».

CREATE TABLE collectes (
    id          BIGSERIAL PRIMARY KEY,
    passage     UUID NOT NULL,
    source      TEXT NOT NULL REFERENCES sources (nom),
    lance_le    TIMESTAMPTZ NOT NULL,
    statut      TEXT NOT NULL
                CHECK (statut IN ('ok', 'non_modifie', 'echec', 'mise_en_sommeil',
                                  'reseau_indisponible')),
    http_statut INTEGER,
    essais      INTEGER NOT NULL,
    recus       INTEGER NOT NULL DEFAULT 0,
    ecrits      INTEGER NOT NULL DEFAULT 0,
    ignores     INTEGER NOT NULL DEFAULT 0,
    duree_ms    INTEGER NOT NULL,
    erreur      TEXT
);

CREATE INDEX collectes_source_lance_le ON collectes (source, lance_le);