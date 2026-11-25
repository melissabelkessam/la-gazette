# TD 4 - Nettoyer, contrôler, stocker : mise en place

Ce dossier contient tous les fichiers du TD 4, avec la même arborescence que votre dépôt.
Copiez-les dans `la-gazette/` (sans écraser `README.md`, `docker-compose.yml`,
`orchestration.py`, `docs/donnees.md` : ces quatre-là se modifient à la main, voir 2).

## 1. Ce qu'il y a dedans

| Fichier | Rôle |
|---|---|
| `src/gazette/migrations/003_articles_propres.sql` | table Silver |
| `src/gazette/migrations/004_rejets.sql` | table des rejets (avec la règle) |
| `src/gazette/migrations/005_controles_qualite.sql` | résultats des contrôles |
| `src/gazette/normalisation.py` | fonctions pures de normalisation |
| `src/gazette/regles_config.py` | motifs, listes, seuils (le seul fichier à régler) |
| `src/gazette/regles.py` | règles R01 à R07 et R10 |
| `src/gazette/doublons.py` | R08 et R09 |
| `src/gazette/nettoyage.py` | brut -> articles_propres / rejets, rejouable |
| `src/gazette/rapport_qualite.py` | `rapports/qualite-AAAA-MM-JJ.md` |
| `src/gazette/controles.py` | contrôles sur les vraies données, alerte, anti-spam |
| `src/gazette/alerte.py` | envoi Discord (bibliothèque standard) |
| `src/gazette/qualite.py` | enchaîne nettoyage, rapport, contrôles |
| `src/gazette/connexion.py` | ouverture de la connexion PostgreSQL |
| `tests/test_*.py` | 85 tests (9 demandent une vraie base) |
| `docs/qualite.md` | les règles documentées (à compléter avec de vrais exemples) |
| `docs/donnees_td4_a_ajouter.md` | à coller dans `docs/donnees.md` |
| `.env.example` | modèle du fichier `.env` |

**Aucune dépendance ajoutée** : bibliothèque standard seulement. Ne touchez pas à
`requirements.txt`, la construction de l'image ne sera pas relancée à zéro.

## 2. Les quatre modifications à faire à la main

### a) `.gitignore` : ignorer `.env` (À FAIRE EN PREMIER)

```bash
echo ".env" >> .gitignore
```
Puis `cp .env.example .env`, et mettre l'URL du webhook Discord dans `.env`.
Vérifiez avec `git status` que `.env` n'apparaît pas.

### b) `docker-compose.yml` : volume des rapports et variable du webhook

Dans le service `orchestrateur`, **ajouter** (sans supprimer ce qui existe) :

```yaml
    environment:
      DISCORD_WEBHOOK_URL: ${DISCORD_WEBHOOK_URL:-}
    volumes:
      - ./rapports:/app/rapports
```
Si `environment` ou `volumes` existent déjà (c'est le cas pour `./data:/app/data`), ajoutez
seulement les lignes manquantes dans les blocs existants. Compose lit `.env` tout seul.

### c) `src/gazette/orchestration.py` : brancher la qualité après la collecte

Dans le flow `collecte`, après `passage_complet()`, ajouter l'appel. Version simple :

```python
from gazette import qualite

@flow(name="collecte", retries=1, retry_delay_seconds=60)
def flow_collecte():
    bilan = passage_complet()
    qualite.passage_qualite()   # nettoyage, rapport, contrôles
    return bilan
```
Pour voir chaque étape dans l'interface Prefect, utilisez des tâches :

```python
from prefect import task

@task(name="nettoyage")
def tache_nettoyage():
    return qualite.etape_nettoyer()

@task(name="rapport_qualite")
def tache_rapport():
    return qualite.etape_rapport()

@task(name="controles_qualite")
def tache_controles():
    return qualite.etape_controles()

# dans flow_collecte, après passage_complet() :
tache_nettoyage()
tache_rapport()
tache_controles()
```
Si la qualité échoue (base inaccessible par exemple), Prefect relance le flow une fois,
donc la collecte aussi : sans danger, elle est rejouable (zéro doublon).

### d) `docs/donnees.md` et `README.md`

Coller `docs/donnees_td4_a_ajouter.md` dans `docs/donnees.md`. Dans le README, passer la
ligne TD 4 à « en cours » puis « fait », et ajouter les commandes de la section 4 ci-dessous.

## 3. Trois points à vérifier dans VOTRE code (je ne l'ai pas vu)

1. **Connexion à la base.** `connexion.py` lit `GAZETTE_DATABASE_URL` (ou `DATABASE_URL`),
   et utilise psycopg 3, sinon psycopg2. Si `registre.py` a déjà une fonction de connexion,
   remplacez le corps de `ouvrir_connexion()` par un appel à celle-ci : une seule façon de
   se connecter dans le projet. Vérifiez le nom de la variable dans `docker-compose.yml`.
2. **Migrations dans l'image.** Vos migrations 001 et 002 sont chargées depuis
   `src/gazette/migrations/`. Si `pyproject.toml` liste les fichiers `.sql` un par un
   (package-data), ajoutez les trois nouveaux ; si c'est un motif `*.sql`, rien à faire.
   Les migrations s'appliquent toutes seules au prochain passage de collecte.
3. **Dossier des données.** Le code lit `data/articles_bruts/` (relatif au dossier de travail,
   `/app/data` dans le conteneur, monté par votre compose). On peut le changer avec
   `GAZETTE_DATA_DIR`. Les rapports vont dans `rapports/` (`GAZETTE_RAPPORTS_DIR`).

## 4. Lancer et vérifier

```bash
bin/test                                   # lint + tests (comme la CI)
docker compose up --build -d               # reconstruit vite : requirements.txt inchangé
docker compose exec orchestrateur prefect deployment run 'collecte/collecte-continue'
docker compose logs orchestrateur --tail 40
```

Sans Prefect (principe : le pipeline n'est pas l'orchestrateur) :

```bash
docker compose run --rm orchestrateur gazette.nettoyage
docker compose run --rm orchestrateur gazette.rapport_qualite
docker compose run --rm orchestrateur gazette.controles
docker compose run --rm orchestrateur gazette.qualite      # les trois à la suite
```

Vérifier que les tables se remplissent :

```bash
docker compose exec postgres psql -U gazette -d gazette -c "SELECT count(*) FROM articles_propres;"
docker compose exec postgres psql -U gazette -d gazette -c "SELECT regle, count(*) FROM rejets GROUP BY regle ORDER BY 2 DESC;"
docker compose exec postgres psql -U gazette -d gazette -c "SELECT nom, portee, valeur, ok FROM controles_qualite ORDER BY id DESC LIMIT 10;"
cat rapports/qualite-*.md
```
Au premier passage, les quelques centaines d'articles déjà collectés sont traités d'un coup,
puis chaque passage ne traite que les nouveaux.

## 5. Déclencher l'alerte pour de vrai (à faire vous-mêmes, avec capture d'écran)

1. Le webhook Discord est dans `.env` et le conteneur a été relancé
   (`docker compose up -d`).
2. Insérer un article à date future :
   ```bash
   docker compose exec postgres psql -U gazette -d gazette -c "INSERT INTO articles_propres (item_id, source, titre, lien, publie_le) VALUES ('test-alerte', 'test', 'Article de test alerte', 'https://exemple.test/t', now() + interval '2 days');"
   ```
3. Lancer les contrôles :
   ```bash
   docker compose exec orchestrateur python -m gazette.controles
   ```
4. Le message « ALERTE qualité - La gazette » arrive sur Discord. **Capture d'écran**, puis
   noter l'heure et le résultat dans `docs/journal.md`.
5. Supprimer la ligne de test :
   ```bash
   docker compose exec postgres psql -U gazette -d gazette -c "DELETE FROM articles_propres WHERE item_id = 'test-alerte';"
   ```
Relancer la commande 3 aussitôt n'envoie PAS un second message (anti-spam de 6 h) : c'est voulu.

## 6. Ce qui a été testé, et ce qui ne l'a pas été

**Testé** (PostgreSQL 16, psycopg 3, Python 3.12) : les 85 tests passent ; essai de bout en
bout en ligne de commande (nettoyage, second passage sans doublon, rapport, contrôles) ;
envoi HTTP réel de l'alerte vers un faux serveur Discord local (message correct, en-tête
`User-Agent` présent, anti-spam, URL du webhook absente des logs).

**Non testé** (je n'ai pas votre dépôt) : l'image Docker, Prefect, votre `registre.py` et
votre `migrations.py`, votre configuration `ruff` (relancez `bin/test` et corrigez les
éventuelles remarques de style), un vrai webhook Discord, et surtout **vos vraies données**.

## 7. À valider par vous (c'est ce que la grille regarde)

- **Les motifs de `regles_config.py`** viennent de ma connaissance de la presse française,
  pas de vos articles. Parcourez `data/articles_bruts/` (`grep -rli "horoscope" ...`), vérifiez
  les rejets dans le rapport, corrigez les motifs, puis écrivez les vrais exemples dans
  `docs/qualite.md` (les cases « À COMPLÉTER »).
- **Le seuil de similarité (0,8)** : regardez des paires réelles de titres proches.
- **Dépêches d'agence** : rejetées par R09 (on garde la plus ancienne). À confirmer.
- **La rétention** (90 jours) est une proposition ; la suppression effective n'est pas codée.
- **Le journal de bord** et les « pourquoi » : à écrire par vous. Mentionnez l'usage de
  Claude, comme Paul l'a autorisé.

Après trois matins de lecture du rapport, ajustez au moins une règle et notez-le dans la
section 7 de `docs/qualite.md`.

## 8. Brouillon d'entrée pour `docs/journal.md`

> **22/10/2026, TD 4.** Mise en place du nettoyage : normalisation, 10 règles d'exclusion,
> tables `articles_propres`, `rejets` et `controles_qualite`, rapport quotidien, contrôles
> avec alerte Discord. Code généré avec l'aide de Claude puis relu et testé par l'équipe
> (85 tests). Premier passage : X articles gardés, Y rejetés (à compléter). Alerte
> déclenchée à HH:MM avec un article à date future : message reçu (capture jointe).
> Ajustements prévus après trois matins de rapport : à compléter.
