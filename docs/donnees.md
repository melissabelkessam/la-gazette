# Données : le contrat et le dictionnaire

Version TD 3 (22/10/2026) : la couche brute (Bronze) et l'état des sources. Le Silver et le Gold seront décrits aux TD 4 et 5.

## 1. Les articles bruts : `data/articles_bruts/`

Un fichier JSON par article : `data/articles_bruts/<source>/<id>.json` (exemple : `sud-ouest/a3f9c2….json`).

| Champ | Type | Obligatoire | Description |
|---|---|---|---|
| `id` | texte (64 caractères hexadécimaux) | oui | Empreinte SHA-256 de la clé naturelle `(source, lien)`. C'est aussi le nom du fichier |
| `source` | texte | oui | Nom du titre de presse, identique à `sources.nom` |
| `lien` | texte (URL) | oui | Lien de l'article, **normalisé** : paramètres `utm_*` et ancre `#` retirés |
| `titre` | texte | non | Titre, sans balise HTML ni entité |
| `resume` | texte | non | Extrait du flux (`description` ou `summary`), **jamais** le texte intégral (`content:encoded`) |
| `publie_le` | date ISO 8601, UTC | non | Date de publication donnée par le flux (`pubDate` ou `updated`), convertie en UTC |
| `recupere_le` | date ISO 8601, UTC | oui | Heure à laquelle **notre** collecte l'a récupéré (provenance) |
| `rubrique` | texte | non | Première catégorie du flux (`category`) |
| `payload` | objet | oui | L'item **tel que reçu**, réduit à une liste blanche : `title`, `link`, `id`, `summary`, `published`, `updated`, `tags` |

**Règles :**
- **Zéro doublon.** Un article déjà écrit pour `(source, lien)` a déjà son fichier : il n'est jamais réécrit. Deux passages de suite ne changent pas le nombre de fichiers.
- **Immuable.** Un fichier n'est jamais modifié. Le nettoyage (TD 4) lit ces fichiers et peut être rejoué.
- **Bornage.** Jamais d'auteur (`author`, `dc:creator`), de texte intégral, d'image ni de commentaire, y compris dans `payload`. Des tests le vérifient.
- **Écriture atomique** (fichier temporaire puis renommage) : jamais de JSON à moitié écrit.
- `data/` n'est **jamais commité** (projet non publié).

## 2. La table `sources` (migration `001_sources.sql`)

Une ligne par titre de presse. Remplie depuis `sources.csv` à chaque passage (ajout des nouvelles sources, mise à jour de l'adresse et de la fréquence) ; l'état n'est modifié que par le collecteur.

| Colonne | Type | Description |
|---|---|---|
| `nom` | texte, clé primaire | Nom du titre (`sources.csv` : `nom`) |
| `type` | `PQN` ou `PQR` | Presse nationale ou régionale |
| `url_flux` | texte | Adresse du flux RSS (`sources.csv` : `acces`) |
| `actif` | booléen | `false` = **en sommeil** : la source n'est plus collectée |
| `derniere_reussite` | date (UTC) | Dernière collecte réussie (200 ou 304) |
| `echecs_consecutifs` | entier ≥ 0 | Échecs de suite ; remis à 0 à la première réussite ; à **3**, mise en sommeil |
| `etag` | texte | Dernier en-tête `ETag` reçu, renvoyé en `If-None-Match` |
| `last_modified` | texte | Dernier `Last-Modified` reçu, renvoyé en `If-Modified-Since` |
| `frequence_min` | entier > 0 | Fréquence de collecte en minutes (`sources.csv` : `frequence_min`) |
| `derniere_tentative` | date (UTC) | Dernier essai, réussi ou non : sert au calcul de la fréquence |
| `derniere_erreur` | texte | Message du dernier échec (vidé à la réussite suivante) |
| `endormie_le` | date (UTC) | Date de la mise en sommeil |

## 3. La table `collectes` (migration `002_collectes.sql`)

Le journal des collectes : une ligne par source et par passage.

| Colonne | Description |
|---|---|
| `passage` | Identifiant (UUID) commun aux sources d'un même passage |
| `source`, `lance_le` | Quelle source, quel passage |
| `statut` | `ok`, `non_modifie` (304), `echec`, `mise_en_sommeil`, `reseau_indisponible` |
| `http_statut`, `essais` | Dernière réponse HTTP (vide si aucune réponse) et nombre de tentatives |
| `recus`, `ecrits`, `ignores` | Articles lus dans le flux, nouveaux articles écrits, articles déjà connus |
| `duree_ms`, `erreur` | Durée de la collecte de la source et message d'erreur éventuel |

`schema_migrations` liste les migrations déjà appliquées (version, date).

## 4. Règles de collecte

| Situation | Comportement |
|---|---|
| 200 | Lecture du flux, écriture des seuls articles nouveaux, réussite notée |
| 304 (rien de neuf grâce à l'ETag) | Rien n'est téléchargé, réussite notée |
| 408, 425, 429, 500, 502, 503, 504, délai dépassé, erreur réseau | **Transitoire** : 3 essais, attentes de 2 s puis 4 s (backoff) |
| 404, 410, 403… | **Permanente** : pas de nouvel essai |
| Réponse qui n'est ni du RSS ni de l'Atom | Flux cassé : compté comme un échec |
| Échec après les essais | `echecs_consecutifs` + 1 ; au 3ᵉ échec de suite, `actif = false` et ligne d'alerte `ALERTE_source_en_sommeil` dans les journaux |
| **Aucune** source ne répond (pas de réponse HTTP) | C'est notre réseau qui est tombé : statut `reseau_indisponible`, les compteurs ne bougent pas |

Politesse : User-Agent `LaGazette-Efrei`, une source après l'autre (jamais en parallèle), délai de 20 s, fréquence par source (Ouest-France 10 min, les autres 60 min).

## 5. Exploiter la collecte

**Lancer :** `bin/dev` (ou `docker compose up --build -d`). Prefect lance un passage toutes les 10 minutes ; l'interface est sur http://localhost:4200.

**Un passage à la main, sans Prefect :** `docker compose run --rm orchestrateur gazette.collecteur`

**Combien d'articles par source, et lesquelles ont dormi ?**
```bash
docker compose exec postgres psql -U gazette -d gazette
```
```sql
-- articles écrits par source depuis le début
SELECT source, sum(ecrits) AS articles, count(*) AS passages,
       count(*) FILTER (WHERE statut IN ('echec', 'mise_en_sommeil')) AS echecs
FROM collectes GROUP BY source ORDER BY source;

-- état des sources
SELECT nom, actif, echecs_consecutifs, derniere_reussite, endormie_le, derniere_erreur
FROM sources ORDER BY nom;
```

**Réveiller une source en sommeil** (après avoir corrigé la cause, par exemple l'adresse dans `sources.csv`), et le noter dans le journal de bord :
```sql
UPDATE sources SET actif = true, echecs_consecutifs = 0 WHERE nom = 'Le Monde';
```

## 6. Choix de l'orchestrateur

| Option | Retenue ? | Pourquoi |
|---|---|---|
| **Prefect** (`gazette/orchestration.py`, déploiement créé par `serve()`) | **Oui** | Planification décrite en code, historique et journaux de chaque run dans l'interface, reprise du flow, simple à écrire en Python |
| cron | Non | Ni historique, ni reprise : un passage raté passe inaperçu |
| Dagster | Non | Plus riche pour les données, mais plus long à prendre en main pour un seul flow |

**L'orchestrateur n'est pas le pipeline** : `python -m gazette.collecteur` fait le même passage sans Prefect. La collecte tourne jusqu'au TD 4 sur la machine d'un membre de l'équipe ; l'infrastructure de production arrive plus tard.