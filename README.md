# La gazette

Un pipeline qui lit chaque matin la presse régionale et nationale (flux RSS), regroupe les articles par thèmes et livre à 7 h l'édition du jour.
Projet M2Ops · M2 Data Engineering & IA · Efrei · 2026-2027 · Mélissa, Salma, Jason, Amelia.

[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)

## Où en est le projet

| TD | Contenu | État |
|---|---|---|
| 1 | Cadrage, sources, schéma d'architecture | ✅ |
| 2 | Socle : dépôt, Docker, première CI | ✅ |
| 3 | **Collecte** : toutes les sources, toutes les 10 min, sans doublon, avec reprise et mise en sommeil | ✅ |
| 4 | Nettoyage, qualité, couche Silver | à venir |
| 5-6 | Thèmes (BERTopic) et MLOps (MLflow) | à venir |
| 7 | Édition de 7 h, journal de bord | à venir |
| 8 | Supervision et alertes | à venir |
| 9 | Infrastructure en code, reconstruction de zéro | à venir |

**Aujourd'hui, la collecte tourne seule :** toutes les 10 minutes, Prefect lance un passage qui lit les flux RSS des sources de `sources.csv`, range chaque article **une seule fois** dans un fichier JSON (`data/articles_bruts/`), réessaie quand un journal ne répond pas, met en **sommeil** une source qui échoue 3 fois de suite, et note tout dans PostgreSQL.

---

## 1. Prérequis

- **Docker Desktop** (Windows / Mac) ou **Docker + Docker Compose** (Linux), lancé.
- **Git**.
- C'est tout : Python, PostgreSQL et Prefect tournent dans des conteneurs.

## 2. Lancer le projet

```bash
git clone https://github.com/melissabelkessam/la-gazette.git
cd la-gazette
docker compose up --build -d
```

Ou avec le raccourci : `bin/dev` (Linux / Mac), `.\bin\dev.ps1` (Windows PowerShell ; si Windows bloque le script : `Unblock-File bin\*.ps1`).

La **première fois**, la construction prend 3 à 5 minutes (téléchargement des images et installation de Prefect). Les fois suivantes, quelques secondes.

`docker compose up` démarre 3 conteneurs :

| Service | Rôle | Adresse |
|---|---|---|
| `postgres` | Base de données : état des sources et journal des collectes (plus tard, couches Silver et Gold) | interne à Docker (non exposée sur la machine) |
| `prefect` | Serveur Prefect : historique de chaque run, interface web | http://localhost:4200 |
| `orchestrateur` | Notre code : le flow `collecte`, planifié toutes les 10 minutes | — |

Les trois redémarrent automatiquement (`restart: unless-stopped`), y compris après un redémarrage de Docker Desktop.

## 3. Vérifier que ça marche

**1. Les 3 conteneurs tournent :**
```bash
docker compose ps
```
`postgres` et `prefect` doivent être **healthy**, `orchestrateur` **Up**.

**2. Le flow est enregistré :**
```bash
docker compose logs orchestrateur --tail 20
```
On doit voir : `Your flow 'collecte' is being served and polling for scheduled runs!`

**3. Lancer un passage tout de suite** (sans attendre les 10 minutes) :
```bash
docker compose exec orchestrateur prefect deployment run 'collecte/collecte-continue'
```
Puis, 30 secondes à 1 minute plus tard, `docker compose logs orchestrateur --tail 20` : une ligne `collecte_source` par journal, puis un `bilan_passage` (articles reçus, écrits, ignorés, échecs).

**4. Dans l'interface :** http://localhost:4200 → **Runs**. Chaque passage apparaît, en vert s'il a réussi. **Deployments** → `collecte-continue` montre la planification.

**5. Les articles sont rangés :** le dossier `data/articles_bruts/` contient un dossier par journal, et un fichier JSON par article.

## 4. Commandes utiles

| Je veux… | Commande |
|---|---|
| Tout lancer | `docker compose up --build -d` |
| Voir l'état des conteneurs | `docker compose ps` |
| Voir ce que fait la collecte | `docker compose logs orchestrateur --tail 30` (suivre en direct : `-f`) |
| Lancer un passage maintenant | `docker compose exec orchestrateur prefect deployment run 'collecte/collecte-continue'` |
| Un passage sans Prefect | `docker compose run --rm orchestrateur gazette.collecteur` |
| Compter les articles (PowerShell) | `(Get-ChildItem data\articles_bruts -Recurse -Filter *.json).Count` |
| Compter les articles (Linux / Mac) | `find data/articles_bruts -name '*.json' \| wc -l` |
| État des sources | `docker compose exec postgres psql -U gazette -d gazette -c "SELECT nom, actif, echecs_consecutifs, derniere_reussite FROM sources;"` |
| Articles par source | `docker compose exec postgres psql -U gazette -d gazette -c "SELECT source, sum(ecrits) AS articles, sum(ignores) AS deja_vus FROM collectes GROUP BY source;"` |
| Sources qui ont dormi | `docker compose exec postgres psql -U gazette -d gazette -c "SELECT nom, endormie_le, derniere_erreur FROM sources WHERE NOT actif;"` |
| Réveiller une source | `docker compose exec postgres psql -U gazette -d gazette -c "UPDATE sources SET actif = true, echecs_consecutifs = 0 WHERE nom = 'Le Monde';"` |
| Ouvrir la base | `docker compose exec postgres psql -U gazette -d gazette` (quitter : `\q`) |
| Arrêter (les données restent) | `docker compose down` |
| Tout effacer, base comprise | `docker compose down -v` (⚠️ efface l'état des sources et l'historique) |

**Ajouter ou retirer une source :** modifier `sources.csv`. Elle est prise en compte au passage suivant, sans redémarrage. Une source en sommeil n'est **jamais** réveillée automatiquement : une personne la réveille après avoir corrigé la cause, et le note dans `docs/journal.md`.

**Garder la collecte en marche :** la machine doit rester allumée, connectée, avec Docker ouvert (désactiver la mise en veille). Si le réseau coupe, le collecteur le détecte (`reseau_indisponible`) et n'endort pas les sources.

## 5. Comment fonctionne la collecte

À chaque passage (toutes les 10 min), le flow `collecte` :

1. applique les **migrations** SQL manquantes (`src/gazette/migrations/`) ;
2. recopie **`sources.csv`** dans la table `sources` ;
3. choisit les sources **dues** : actives, et dont la fréquence est écoulée (Ouest-France 10 min, les autres 60 min) ;
4. pour chaque source, **l'une après l'autre** :
   - télécharge le flux poliment : User-Agent `LaGazette-Efrei`, ETag / Last-Modified (un 304 = rien de neuf, rien n'est retéléchargé), délai de 20 s ;
   - **erreur transitoire** (503, 429, 5xx, délai dépassé) : 3 essais, attentes de 2 s puis 4 s (backoff) ;
   - **erreur permanente** (404, 403, 410) ou **flux cassé** : pas de nouvel essai ;
   - lit le flux avec feedparser et ne garde que **titre, extrait, lien, date, rubrique** ;
   - écrit chaque article **nouveau** dans `data/articles_bruts/<source>/<id>.json` (id = empreinte SHA-256 de (source, lien) : un article déjà rangé n'est jamais réécrit) ;
   - met à jour la table `sources` : réussite (compteur remis à 0) ou échec (compteur + 1 ; au **3ᵉ échec de suite**, mise en **sommeil** et ligne `ALERTE_source_en_sommeil` dans les logs) ;
   - écrit une ligne dans la table `collectes` et une ligne de log JSON (reçus, écrits, ignorés, durée) ;
5. écrit un **bilan** du passage.

Si **aucune** source ne répond, c'est notre réseau qui est tombé : statut `reseau_indisponible`, les compteurs ne bougent pas.

Détail des champs et des tables : [docs/donnees.md](docs/donnees.md).

## 6. Tester

```bash
bin/test          # Windows PowerShell : .\bin\test.ps1
```

Lance le lint (`ruff`) puis les tests (`pytest`) dans un conteneur, exactement comme la CI. Résultat attendu : `19 passed, 3 skipped`. Les 3 tests ignorés demandent une vraie base PostgreSQL : ils tournent dans la CI.

Les tests clés du TD 3 (`tests/test_collecteur.py`), contre un **faux serveur HTTP local** (aucun accès à Internet) :
- **« deux passages, zéro doublon »** : le nombre de fichiers ne bouge pas au second passage ;
- **« source en panne »** : le serveur renvoie 503 → 3 essais, attentes de 2 s puis 4 s, échec compté ; au 3ᵉ passage, la source est endormie et n'est plus appelée ;
- et aussi : 404 sans réessai, ETag et 304, flux cassé, une source en panne n'empêche pas les autres, fréquence respectée, panne de notre réseau.

**Sans Docker, en local :**
```bash
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt -e .
ruff check . && pytest
```

Pour lancer aussi les tests PostgreSQL en local, pointer `GAZETTE_TEST_DATABASE_URL` vers une base **jetable** (elle est vidée !), par exemple `postgresql://gazette:gazette_dev@localhost:5432/gazette_test`.

## 7. En cas de problème

| Symptôme | Solution |
|---|---|
| `port is already allocated` | Un autre programme utilise le port. Pour Prefect (4200), fermer l'autre programme ou changer le port dans `docker-compose.yml` |
| `failed to connect to the docker API` | Docker Desktop n'est pas lancé : l'ouvrir et attendre la baleine verte |
| Windows refuse de lancer `bin\*.ps1` | `Set-ExecutionPolicy -Scope Process Bypass` ou `Unblock-File bin\*.ps1` |
| `ModuleNotFoundError: importlib_metadata` | L'image est ancienne : `docker compose up --build -d` |
| `is not in the subpath of '/app'` | L'image est ancienne : `docker compose up --build -d` |
| Les logs sont vides juste après le démarrage | Normal : attendre 30 s à 1 min |
| Une source échoue en 403 | L'éditeur refuse notre robot. On ne contourne pas : la remplacer dans `sources.csv` (et le noter dans le journal de bord) |
| Une source est en sommeil | Lire `derniere_erreur` dans la table `sources`, corriger (par exemple l'adresse dans `sources.csv`), puis la réveiller (commande ci-dessus) |

## 8. Organisation du dépôt

| Chemin | Contenu |
|---|---|
| `src/gazette/collecte.py` | Lecture d'un flux RSS ou Atom, bornage (seuls les champs autorisés sont gardés) |
| `src/gazette/brut.py` | Stockage brut : un fichier JSON par article, sans doublon |
| `src/gazette/registre.py` | Lecture et mise à jour des tables `sources` et `collectes` |
| `src/gazette/collecteur.py` | La boucle de collecte : politesse, reprise, sommeil, journaux, compteurs |
| `src/gazette/orchestration.py` | Le flow Prefect, planifié toutes les 10 minutes |
| `src/gazette/migrations.py` | Applique les migrations SQL manquantes |
| `src/gazette/migrations/` | Les migrations versionnées : `001_sources.sql`, `002_collectes.sql` |
| `tests/` | Tests ; `tests/fixtures/` contient des flux d'exemple **inventés** (aucun contenu de presse dans le dépôt) |
| `sources.csv` | Les 10 sources, leurs conditions d'utilisation et leur fréquence de collecte |
| `docs/` | Cadrage, architecture, CI/CD, données, journal de bord |
| `bin/` | Les commandes `dev` et `test` |
| `Dockerfile`, `docker-compose.yml` | L'environnement, décrit en code |
| `.github/workflows/ci.yml` | La CI : lint, tests (avec une vraie base PostgreSQL), image Docker |
| `data/` | Données collectées, **jamais commitées** (ignorées par Git) |

## 9. Choix techniques (TD 3)

| Besoin | Retenu | Écartés |
|---|---|---|
| Orchestration | **Prefect** : planification en code, historique, reprise | cron (ni historique ni reprise) · Dagster (plus long à prendre en main pour un seul flow) |
| Migrations | **Fichiers SQL numérotés + petit script** | Alembic (pensé pour un ORM qu'on n'utilise pas) · création à la main (pas reproductible) |
| Lecture des flux | **feedparser** | lxml / xml.etree (RSS, Atom, dates et encodages à gérer à la main) |
| Téléchargement | **httpx** | requests (délais moins fins) · aiohttp (asynchrone, plus complexe) |
| Stockage brut | **Un JSON par article** | un gros fichier par jour (dédoublonnage plus compliqué) |

Les autres choix (stockage Silver/Gold, thèmes, supervision…) sont argumentés dans le [cadrage](docs/cadrage.md).

## Contribuer

Voir [CONTRIBUTING.md](CONTRIBUTING.md) : une branche par sujet, une pull request revue par quelqu'un d'autre, une CI verte avant de fusionner.

## Documentation

- [Cadrage](docs/cadrage.md)
- [Schéma d'architecture](docs/architecture.jpg)
- [Stratégie CI/CD](docs/ci-cd.md)
- [Données : contrat et dictionnaire](docs/donnees.md)
- [Journal de bord](docs/journal.md)

## Bornage

Seuls le titre, l'extrait, le lien, la date et la rubrique sont conservés : jamais l'article entier, jamais les images, jamais l'auteur, jamais les commentaires. Le robot s'identifie honnêtement (`LaGazette-Efrei`) et ne lit que les flux RSS, jamais les pages d'articles. Projet de cours, jamais publié.