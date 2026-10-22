-- TD 4 : couche Silver. Un article propre par ligne, rejouable (item_id unique).
-- item_id = nom du fichier brut (data/articles_bruts/<source>/<item_id>.json).
CREATE TABLE IF NOT EXISTS articles_propres (
    item_id       TEXT PRIMARY KEY,
    source        TEXT NOT NULL,
    titre         TEXT NOT NULL,
    extrait       TEXT,
    lien          TEXT NOT NULL,
    rubrique      TEXT,
    publie_le     TIMESTAMPTZ NOT NULL,
    date_estimee  BOOLEAN NOT NULL DEFAULT FALSE,
    collecte_le   TIMESTAMPTZ,
    nettoye_le    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_articles_propres_publie_le ON articles_propres (publie_le);
CREATE INDEX IF NOT EXISTS idx_articles_propres_source ON articles_propres (source);
CREATE INDEX IF NOT EXISTS idx_articles_propres_nettoye_le ON articles_propres (nettoye_le);
