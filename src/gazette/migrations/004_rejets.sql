-- TD 4 : articles écartés, avec la règle qui les a écartés (traçabilité).
CREATE TABLE IF NOT EXISTS rejets (
    item_id     TEXT PRIMARY KEY,
    source      TEXT NOT NULL,
    titre       TEXT,
    lien        TEXT,
    regle       TEXT NOT NULL,
    detail      TEXT,
    doublon_de  TEXT,
    rejete_le   TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_rejets_regle ON rejets (regle);
CREATE INDEX IF NOT EXISTS idx_rejets_source ON rejets (source);
CREATE INDEX IF NOT EXISTS idx_rejets_rejete_le ON rejets (rejete_le);
