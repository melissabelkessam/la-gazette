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
| 4 | **Nettoyage et qualité** : normalisation, 10 règles d'exclusion, tables `articles_propres` et `rejets`, rapport quotidien, contrôles et alerte Discord | ✅ |
| 5 | **Thèmes** : embeddings en cache, BERTopic, nommage par mots-clés, chaque run tracé (MLflow + table `runs_themes`) | ✅ code prêt, à valider sur les données réelles |
| 6 | Évaluer, versionner, déployer le modèle (MLOps 2) | à venir |
| 7 | Édition de 7 h, journal de bord | à venir |
| 8 | Supervision et alertes (Prometheus, Grafana, Healthchecks) | à venir |
| 9 | Infrastructure en code, reconstruction de zéro | à venir |

**Aujourd'hui, la chaîne suivante tourne seule**, toutes les 10 minutes :

```
sources.csv
   |
   v
1. COLLECTE      lit les flux RSS, range un fichier JSON par article      -> data/articles_bruts/   (brut)
   |
   v
2. NETTOYAGE     normalise, applique 10 règles, écarte les doublons       -> tables articles_propres et rejets (propre)
   |
   v
3. RAPPORT       compte les entrés, gardés, rejetés par règle et source   -> rapports/qualite-AAAA-MM-JJ.md
   |
   v
4. CONTRÔLES     vérifie des faits sur les données                        -> table controles_qualite + alerte Discord si un fait est faux
   |
   v
5. THÈMES        au plus 1 fois par heure : vecteurs, BERTopic, noms      -> tables themes, articles_themes, runs_themes + MLflow
```

Prefect lance cette chaîne. Si un journal ne répond pas, la collecte réessaie ; après 3 échecs de suite, la source est mise en sommeil. Tout est noté dans PostgreSQL.

**Lire ce document selon ce que vous cherchez :**

| Je veux... | Section |
|---|---|
| Lancer le projet pour la première fois | 1 et 2 |
| Comprendre ce que fait chaque fichier et où il est | 10 |
| Récupérer le travail des autres (pull, branches, fusion) | 11 |
| Comprendre la collecte | 5 |
| Comprendre le nettoyage et la qualité (TD 4) | 6 |
| Comprendre les thèmes (TD 5) | 13 et [docs/mlops.md](docs/mlops.md) |
| Résoudre un problème | 9 |

## 1. Prérequis

- **Docker Desktop** (Windows / Mac) ou **Docker + Docker Compose** (Linux), lancé.
- **Git**.
- Un éditeur de texte (VS Code conseillé).
- C'est tout : Python, PostgreSQL et Prefect tournent dans des conteneurs.

## 2. Lancer le projet

### 2.1 Récupérer le code

```bash
git clone https://github.com/melissabelkessam/la-gazette.git
cd la-gazette
```

Chacun travaille sur sa branche. Pour voir les branches et changer de branche :

```bash
git branch -a              # liste les branches (locales et sur GitHub)
git switch <nom-de-branche>
```
Voir la section 11 pour récupérer le travail des autres.

### 2.2 Créer le fichier `.env` (une seule fois, sur chaque machine)

Le fichier `.env` contient l'adresse secrète (le « webhook ») du salon Discord des alertes. **Il n'est jamais commité** (il est dans `.gitignore`).

1. Vérifier que Git l'ignore : `git check-ignore -v .env` doit afficher une ligne qui cite `.gitignore`.
2. Créer le fichier `.env` à la racine **avec VS Code** (pas avec `echo` sous PowerShell : il écrit en UTF-16 et abîme le fichier). Une seule ligne :
   ```
   DISCORD_WEBHOOK_URL=l-adresse-du-webhook
   ```
   Le modèle est dans `.env.example`.
3. L'adresse du webhook se demande à Jason. Ne la collez jamais dans un message, un ticket ou le code.

Sans `.env`, tout marche, sauf l'envoi des alertes (un avertissement `webhook_absent` s'affiche dans les logs).

### 2.3 Démarrer

```bash
docker compose up --build -d
```

Ou avec le raccourci : `bin/dev` (Linux / Mac), `.\bin\dev.ps1` (Windows PowerShell ; si Windows bloque le script : `Unblock-File bin\*.ps1`).

La **première fois**, la construction prend de 3 à 40 minutes (depuis le TD 5, l'image contient torch en version CPU, environ 1 Go de plus ; au premier run des thèmes, le modèle d'embeddings, environ 470 Mo, est téléchargé une seule fois dans le volume `modeles`) selon le réseau (téléchargement des images et installation des dépendances). Les fois suivantes, quelques secondes, grâce au cache Docker. Si le code Python a changé (après un `git pull` par exemple), relancez `docker compose up --build -d` : le code est copié dans l'image, il n'est pas lu en direct.

`docker compose up` démarre 4 conteneurs :

| Service | Rôle | Adresse |
|---|---|---|
| `postgres` | Base de données : état des sources, journal des collectes, articles propres, rejets, contrôles, thèmes, runs | interne à Docker (non exposée sur la machine) |
| `mlflow` | Serveur MLflow (TD 5) : chaque run de thèmes, ses paramètres, métriques et artefacts | http://localhost:5000 |
| `prefect` | Serveur Prefect : historique de chaque run, interface web | http://localhost:4200 |
| `orchestrateur` | Notre code : le flow `collecte` (collecte, puis nettoyage, rapport, contrôles, thèmes), planifié toutes les 10 minutes | - |

Les quatre redémarrent automatiquement (`restart: unless-stopped`), y compris après un redémarrage de Docker Desktop. Prefect peut être déclaré « unhealthy » au tout premier démarrage s'il est lent : relancez `docker compose up -d` une minute plus tard.

## 3. Vérifier que ça marche

**1. Les 4 conteneurs tournent :**
```bash
docker compose ps
```
`postgres`, `prefect` et `mlflow` doivent être **healthy**, `orchestrateur` **Up**.

**2. Le flow est enregistré :**
```bash
docker compose logs orchestrateur --tail 20
```
On doit voir : `Your flow 'collecte' is being served and polling for scheduled runs!`

**3. Lancer un passage tout de suite** (sans attendre les 10 minutes) :
```bash
docker compose exec orchestrateur prefect deployment run 'collecte/collecte-continue'
```
Puis, 30 secondes à 1 minute plus tard, `docker compose logs orchestrateur --tail 40` doit montrer : `Bilan du passage` (collecte), puis `Nettoyage :`, `Rapport de qualité :` et `Contrôles :`.

**4. Dans l'interface :** http://localhost:4200 → **Runs**. Chaque passage apparaît, en vert s'il a réussi, avec 4 « Task runs » (nettoyage, rapport, contrôles, thèmes). **Deployments** → `collecte-continue` montre la planification.

**5. Les articles sont rangés :** le dossier `data/articles_bruts/` contient un dossier par journal, et un fichier JSON par article.

**6. Les tables se remplissent :**
```bash
docker compose exec postgres psql -U gazette -d gazette -P pager=off -c "SELECT (SELECT count(*) FROM articles_propres) AS propres, (SELECT count(*) FROM rejets) AS rejets, (SELECT count(*) FROM controles_qualite) AS controles;"
```

**7. Les thèmes (TD 5) :** lancer un run sans attendre, puis lire les thèmes et le run qui les a produits.
```bash
docker compose exec orchestrateur python -m gazette.themes --forcer
docker compose exec postgres psql -U gazette -d gazette -P pager=off -c "SELECT run_id, nom, taille FROM themes_du_jour;"
```
Le premier run télécharge le modèle (quelques minutes). Puis http://localhost:5000 → expérience `gazette-themes` : le même run, avec ses paramètres, ses métriques et ses artefacts. Détail : [docs/mlops.md](docs/mlops.md).

**8. Le rapport existe :** `rapports/qualite-AAAA-MM-JJ.md`.
- PowerShell : `Get-Content -Encoding utf8 rapports\qualite-2026-10-22.md` (avec `cat`, les accents s'affichent mal : le fichier est correct, c'est le terminal)
- Git Bash, Linux, Mac : `cat rapports/qualite-2026-10-22.md`

## 4. Commandes utiles

| Je veux... | Commande |
|---|---|
| Tout lancer | `docker compose up --build -d` |
| Voir l'état des conteneurs | `docker compose ps` |
| Voir ce que fait le pipeline | `docker compose logs orchestrateur --tail 30` (suivre en direct : `-f`) |
| Lancer un passage maintenant | `docker compose exec orchestrateur prefect deployment run 'collecte/collecte-continue'` |
| Un passage de collecte sans Prefect | `docker compose run --rm orchestrateur gazette.collecteur` |
| Nettoyage seul | `docker compose run --rm orchestrateur gazette.nettoyage` |
| Rapport de qualité seul | `docker compose run --rm orchestrateur gazette.rapport_qualite` |
| Contrôles seuls (et alerte) | `docker compose run --rm orchestrateur gazette.controles` |
| Nettoyage + rapport + contrôles | `docker compose run --rm orchestrateur gazette.qualite` |
| Un run de thèmes maintenant | `docker compose exec orchestrateur python -m gazette.themes --forcer` |
| Les thèmes du jour | `docker compose exec postgres psql -U gazette -d gazette -P pager=off -c "SELECT run_id, nom, taille FROM themes_du_jour;"` |
| Les derniers runs de thèmes | `docker compose exec postgres psql -U gazette -d gazette -P pager=off -c "SELECT run_id, statut, nb_articles, metriques->>'nb_themes' AS themes, fin FROM runs_themes ORDER BY debut DESC LIMIT 10;"` |
| Régler le regroupement | modifier `config/clustering.yaml` (lu à chaque run, pas besoin de reconstruire) |
| Compter les articles bruts (PowerShell) | `(Get-ChildItem data\articles_bruts -Recurse -Filter *.json).Count` |
| Compter les articles bruts (Linux / Mac / Git Bash) | `find data/articles_bruts -name '*.json' \| wc -l` |
| Retrouver le fichier brut d'un `item_id` (PowerShell) | `Get-ChildItem data\articles_bruts -Recurse -Filter <item_id>.json` |
| Retrouver le fichier brut d'un `item_id` (Git Bash) | `find data/articles_bruts -name '<item_id>.json'` |
| État des sources | `docker compose exec postgres psql -U gazette -d gazette -c "SELECT nom, actif, echecs_consecutifs, derniere_reussite FROM sources;"` |
| Articles collectés par source | `docker compose exec postgres psql -U gazette -d gazette -c "SELECT source, sum(ecrits) AS articles, sum(ignores) AS deja_vus FROM collectes GROUP BY source;"` |
| Articles propres par source | `docker compose exec postgres psql -U gazette -d gazette -P pager=off -c "SELECT source, count(*) FROM articles_propres GROUP BY source ORDER BY 2 DESC;"` |
| Pourquoi des articles ont été rejetés | `docker compose exec postgres psql -U gazette -d gazette -P pager=off -c "SELECT regle, source, titre FROM rejets ORDER BY regle, source;"` |
| Sources qui ont dormi | `docker compose exec postgres psql -U gazette -d gazette -c "SELECT nom, endormie_le, derniere_erreur FROM sources WHERE NOT actif;"` |
| Réveiller une source | `docker compose exec postgres psql -U gazette -d gazette -c "UPDATE sources SET actif = true, echecs_consecutifs = 0 WHERE nom = 'Le Monde';"` |
| Ouvrir la base | `docker compose exec postgres psql -U gazette -d gazette` (quitter : `\q`) |
| Arrêter (les données restent) | `docker compose down` |
| Tout effacer, base comprise | `docker compose down -v` (⚠️ efface la base et l'historique Prefect ; `data/` et `rapports/` restent sur votre machine) |

Astuce : avec `psql`, ajouter `-P pager=off` évite les coupures `--More--` au milieu des résultats.

**Ajouter ou retirer une source :** modifier `sources.csv`. Elle est prise en compte au passage suivant, sans redémarrage. Une source en sommeil n'est **jamais** réveillée automatiquement : une personne la réveille après avoir corrigé la cause, et le note dans `docs/journal.md`.

**Garder le pipeline en marche :** la machine doit rester allumée, connectée, avec Docker ouvert (désactiver la mise en veille). Si le réseau coupe, le collecteur le détecte (`reseau_indisponible`) et n'endort pas les sources.

## 5. Comment fonctionne la collecte (TD 3)

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

Aujourd'hui, 8 sources sur 10 répondent. Le Télégramme et Les Échos renvoient une erreur 403 (l'éditeur refuse notre robot) : on ne contourne pas, c'est noté.

Détail des champs et des tables : [docs/donnees.md](docs/donnees.md).

## 6. Comment fonctionne le nettoyage et la qualité (TD 4)

Après la collecte, le flow enchaîne trois tâches Prefect. Chacune est une fonction Python ordinaire, lançable à la main sans Prefect (voir section 4).

### 6.1 Nettoyage (`gazette.nettoyage`)

Lit les fichiers bruts **jamais traités** (donc incrémental et rejouable), puis pour chaque article :

1. **Normalise** : HTML retiré du titre et de l'extrait, entités décodées, espaces nettoyés, encodage cassé réparé (« CafÃ© » devient « Café »), date convertie en UTC, extrait borné à 300 caractères, paramètres de suivi (`utm_*`...) retirés du lien. Le champ `payload` du brut (qui peut contenir des auteurs) n'est jamais recopié.
2. **Applique les règles** dans cet ordre, la première qui s'applique gagne : R05, R06, R07, R01, R02, R03, R04, R10.
3. **Compare aux articles déjà gardés** (fenêtre de 48 h) : R08 (doublon exact) puis R09 (doublon approximatif).
4. **Écrit** dans `articles_propres` (gardé) ou dans `rejets` (avec la règle et, pour un doublon, l'article conservé).

| Règle | Écarte |
|---|---|
| R05_titre_vide | titre vide ou de moins de 3 lettres ou chiffres |
| R06_date_future | date de publication à plus de 3 h dans le futur |
| R07_encodage_casse | titre encore illisible après réparation |
| R01_publi | publi-reportage, contenu partenaire, codes promo |
| R02_horoscope | horoscope, astrologie, voyance |
| R03_tv | programmes TV |
| R04_jeux | jeux, concours, loto, mots fléchés |
| R10_direct_diaporama | titres « DIRECT », « EN DIRECT », « LIVE », « DIAPORAMA » |
| R08_doublon_exact | même titre ou même lien qu'un article déjà gardé |
| R09_doublon_approx | titre très proche (similarité de Jaccard ≥ 0,8) d'un article déjà gardé |

Les motifs et les seuils se règlent dans `src/gazette/regles_config.py`, sans toucher à la logique. Détail, exemples réels et justification des choix : [docs/qualite.md](docs/qualite.md).

Le 22/10/2026 : 427 articles traités, 12 rejetés (9 directs, 2 quasi-doublons, 1 doublon exact). Aucun horoscope, programme TV, jeu ou publi-reportage dans nos 8 flux.

### 6.2 Rapport de qualité (`gazette.rapport_qualite`)

Écrit `rapports/qualite-AAAA-MM-JJ.md`, recalculé à chaque passage pour la journée UTC : articles entrés, gardés, rejetés ; rejets par règle ; par source ; les cinq rejets les plus fréquents avec des exemples ; les règles qui écartent au moins 80 % d'une source (signal « règle trop gourmande »).

### 6.3 Contrôles de qualité (`gazette.controles`)

Quatre faits vérifiés sur les vraies données (ce ne sont pas des tests de code, ceux-là sont dans la CI) :

| Contrôle | Fait vérifié | Alerte |
|---|---|---|
| `date_future` | aucune date future dans `articles_propres` | oui |
| `titre_vide` | aucun titre vide dans `articles_propres` | oui |
| `taux_rejet_source` | moins de 80 % d'articles rejetés par source (sources d'au moins 10 articles) | oui |
| `fraicheur_source` | dernier article gardé de moins de 24 h par source | non (signalement) |

Chaque résultat est écrit dans la table `controles_qualite` (le TD 8 les lira pour les métriques).

## 7. Alertes Discord

Quand un contrôle échoue, un message part dans le salon `#alertes-gazette` : « ALERTE qualité - La gazette », avec le nom du contrôle, sa valeur et son seuil. Un même contrôle n'alerte qu'**une fois par 6 heures** (anti-spam) ; si l'envoi échoue, il est retenté au passage suivant. L'adresse du webhook est lue dans la variable `DISCORD_WEBHOOK_URL` (fichier `.env`) et n'apparaît dans aucun log.

**Rejoindre le salon :** demander le lien d'invitation à Jason (il n'est pas écrit ici, parce que le dépôt peut être public).

**Tester l'envoi :**
```bash
docker compose exec orchestrateur python -c "from gazette.alerte import envoyer_alerte; print(envoyer_alerte('Test'))"
```
Attendu : `True` et le message dans Discord.

**Déclencher une vraie alerte** (fait le 22/10/2026) :
```bash
docker compose exec postgres psql -U gazette -d gazette -c "INSERT INTO articles_propres (item_id, source, titre, lien, publie_le) VALUES ('test-alerte', 'test', 'Article de test', 'https://exemple.test/t', now() + interval '2 days');"
docker compose exec orchestrateur python -m gazette.controles
docker compose exec postgres psql -U gazette -d gazette -c "DELETE FROM articles_propres WHERE item_id = 'test-alerte';"
```
Toujours supprimer la ligne de test ensuite.

**Créer un webhook** (nouvelle installation) : Discord, réglages du salon (roue dentée), Intégrations, Webhooks, Nouveau webhook, Copier l'URL, puis la mettre dans `.env`. Si l'URL fuite : supprimer le webhook et en créer un nouveau.

## 8. Tester

```bash
bin/test          # Windows PowerShell : .\bin\test.ps1
```

Lance le lint (`ruff`) puis les tests (`pytest`) dans un conteneur, exactement comme la CI. Résultat attendu : `106 passed, 22 skipped` (le nombre augmente à chaque TD). Les 22 tests ignorés demandent une vraie base PostgreSQL : ils tournent dans la CI. Le lint limite les lignes à 100 caractères.

Les tests clés :
- TD 3 (`tests/test_collecteur.py`), contre un **faux serveur HTTP local** (aucun accès à Internet) : « deux passages, zéro doublon », « source en panne » (503 : 3 essais, attentes de 2 s puis 4 s, mise en sommeil), 404 sans réessai, ETag et 304, flux cassé, fréquence respectée, panne du réseau.
- TD 4 : une fonction de normalisation = un test ; chaque règle a un cas rejeté, un cas conservé et un cas limite (`tests/test_regles.py`) ; doublons exacts et approximatifs ; alerte Discord **sans réseau** (l'envoi est remplacé par un faux) ; avec une vraie base : « deux passages, zéro doublon », un rejeté va dans `rejets` avec sa règle, alerte sur date future, pas de spam.

**Sans Docker, en local :**
```bash
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt -e .
ruff check . && pytest
```

Pour lancer aussi les tests PostgreSQL en local, pointer `GAZETTE_TEST_DATABASE_URL` vers une base **jetable** (elle est vidée !), par exemple `postgresql://gazette:gazette_dev@localhost:5432/gazette_test`.

## 9. En cas de problème

| Symptôme | Solution |
|---|---|
| `port is already allocated` | Un autre programme utilise le port. Pour Prefect (4200), fermer l'autre programme ou changer le port dans `docker-compose.yml` |
| `failed to connect to the docker API` | Docker Desktop n'est pas lancé : l'ouvrir et attendre la baleine verte |
| Windows refuse de lancer `bin\*.ps1` | `Set-ExecutionPolicy -Scope Process Bypass` ou `Unblock-File bin\*.ps1` |
| La construction Docker dure très longtemps | Installation des dépendances (`pip install`) avec un réseau lent. Laisser finir, PC éveillé. Ne pas modifier `requirements.txt` sans raison : cela relance toute l'installation |
| `dependency failed to start: ... prefect ... unhealthy` | Prefect démarre lentement la première fois. Relancer `docker compose up -d` après une minute |
| `ModuleNotFoundError: importlib_metadata` | L'image est ancienne : `docker compose up --build -d` |
| `is not in the subpath of '/app'` | L'image est ancienne : `docker compose up --build -d` |
| Le code a changé mais rien ne bouge | Le code est copié dans l'image : relancer `docker compose up --build -d` |
| Les logs sont vides juste après le démarrage | Normal : attendre 30 s à 1 min |
| Le premier passage affiche `sources: 0` | Aucune source « due » à ce moment (fréquences de 10 ou 60 min). Normal |
| Une source échoue en 403 | L'éditeur refuse notre robot. On ne contourne pas : la remplacer dans `sources.csv` (et le noter dans le journal de bord) |
| Une source est en sommeil | Lire `derniere_erreur` dans la table `sources`, corriger (par exemple l'adresse dans `sources.csv`), puis la réveiller (commande section 4) |
| `PermissionError: ... 'rapports'` | Le dossier des rapports n'est pas monté. Vérifier le volume `./rapports:/app/rapports` et `GAZETTE_RAPPORTS_DIR` dans `docker-compose.yml` |
| `relation "articles_propres" does not exist` | Les migrations ne sont pas appliquées : relancer un passage (`prefect deployment run ...`) ou vérifier que les `.sql` sont dans `src/gazette/migrations/` |
| `alerte_non_envoyee / webhook_absent` | `.env` absent ou vide, ou conteneur pas relancé : `docker compose up -d` |
| `alerte_envoyee: false` alors qu'un contrôle échoue | Anti-spam de 6 h : l'alerte est déjà partie. Normal |
| `QualitÃ©` à l'écran sous PowerShell | Encodage du terminal, pas du fichier. Utiliser `Get-Content -Encoding utf8` |
| `find : format incorrect de paramètre` | Sous PowerShell, `find` est une autre commande : utiliser `Get-ChildItem` |
| `bin/test` : `E501 Line too long` | Le lint limite les lignes à 100 caractères |
| `.env` apparaît dans `git status` | Ne pas le commiter. Corriger `.gitignore` (ligne `.env`, fichier en UTF-8) |

## 10. Organisation du dépôt : où est chaque fichier et ce qu'il fait

### 10.1 Vue d'ensemble

```
la-gazette/
├── README.md                    ce document
├── CONTRIBUTING.md              règles de travail en équipe (branches, revues)
├── sources.csv                  les 10 sources et leurs réglages
├── docker-compose.yml           les 3 conteneurs (postgres, prefect, orchestrateur)
├── Dockerfile                   la recette de l'image de notre code
├── .dockerignore                fichiers exclus de l'image
├── .gitignore                   fichiers exclus de Git (data/, .env...)
├── .env.example                 modèle du fichier .env
├── .env                         VOTRE secret local (jamais commité)
├── pyproject.toml               configuration Python (paquet, ruff, pytest)
├── requirements.txt             dépendances de l'application
├── requirements-dev.txt         dépendances de développement (tests, lint)
├── bin/                         raccourcis : dev, dev.ps1, test, test.ps1
├── .github/workflows/ci.yml     la CI
├── src/gazette/                 tout le code de l'application
│   └── migrations/              les migrations SQL
├── tests/                       les tests
│   └── fixtures/                flux d'exemple inventés
├── docs/                        la documentation
├── rapports/                    rapports de qualité quotidiens
└── data/                        articles bruts (jamais commité)
```

### 10.2 À la racine

| Fichier | Ce qu'il fait | Quand on y touche |
|---|---|---|
| `sources.csv` | Liste les 10 sources : nom, adresse du flux, conditions d'utilisation vérifiées, fréquence de collecte en minutes (`frequence_min`) | pour ajouter, retirer ou régler une source (pris en compte au passage suivant) |
| `docker-compose.yml` | Décrit les 3 conteneurs : `postgres` (base), `prefect` (serveur et interface), `orchestrateur` (notre code, lance `gazette.orchestration`). Définit les variables d'environnement (`DATABASE_URL`, `GAZETTE_DOSSIER_BRUT`, `GAZETTE_RAPPORTS_DIR`, `DISCORD_WEBHOOK_URL`) et les dossiers partagés avec votre machine (`./data`, `./rapports`) | pour ajouter un service ou une variable |
| `Dockerfile` | Construit l'image de notre code en deux étapes : une étape installe les dépendances de `requirements.txt`, l'image finale copie `src/` et `sources.csv`, crée le dossier `data/articles_bruts` et tourne avec un utilisateur non administrateur (`gazette`) | pour changer la version de Python ou ajouter un fichier à l'image |
| `.dockerignore` | Liste ce que Docker ne doit pas copier dans l'image | rarement |
| `.gitignore` | Liste ce que Git ne doit jamais suivre : `data/`, `.env`, caches Python... | pour protéger un nouveau fichier sensible |
| `.env.example` | Modèle du `.env` (la ligne `DISCORD_WEBHOOK_URL=` sans valeur) | rarement |
| `.env` | Votre secret local : l'adresse du webhook Discord. **Jamais commité, jamais partagé** | une fois par machine |
| `pyproject.toml` | Configuration du paquet Python `gazette`, de `ruff` (lint, lignes de 100 caractères maximum) et de `pytest` (dossier `tests/`) | pour une option de lint ou de test |
| `requirements.txt` | Dépendances de l'application (installées dans l'image), versions figées. torch vient de l'index CPU de PyTorch (ligne `--extra-index-url`). Les modifier relance toute l'installation Docker (longue) | pour ajouter une bibliothèque |
| `config/clustering.yaml` | **Tous les paramètres des thèmes** (TD 5) : fenêtre, modèle, UMAP, HDBSCAN, nommage, graine, fréquence | pour régler le regroupement |
| `docker/mlflow.Dockerfile` | L'image du serveur MLflow (version figée) | rarement |
| `requirements-dev.txt` | Dépendances de développement : `pytest`, `ruff` | rarement |
| `CONTRIBUTING.md` | Règles de travail : une branche par sujet, une pull request relue par quelqu'un d'autre, CI verte avant de fusionner | à lire une fois |
| `bin/dev`, `bin/dev.ps1` | Raccourci pour `docker compose up --build -d` (Linux / Mac, puis PowerShell) | - |
| `bin/test`, `bin/test.ps1` | Lancent `ruff` puis `pytest` dans un conteneur, comme la CI | avant chaque commit |
| `.github/workflows/ci.yml` | La CI GitHub : à chaque push, lint, tests (avec une vraie base PostgreSQL, donc y compris les tests ignorés en local) et construction de l'image Docker | pour ajouter une étape |

### 10.3 `src/gazette/` : le code (chaque fichier a un rôle)

**Collecte (TD 3)**

| Fichier | Ce qu'il fait |
|---|---|
| `collecte.py` | Lit un flux RSS ou Atom avec feedparser et applique le **bornage** : seuls titre, extrait, lien, date et rubrique sont gardés, jamais l'auteur ni le texte complet |
| `brut.py` | Stockage brut : écrit **un fichier JSON par article** dans `data/articles_bruts/<source>/<id>.json`, jamais réécrit (zéro doublon) |
| `registre.py` | Lit et met à jour les tables `sources` (état de chaque source) et `collectes` (journal de chaque collecte) |
| `collecteur.py` | La boucle de collecte : politesse, reprises, mise en sommeil, journaux, compteurs. Contient aussi la configuration des journaux (`configurer_journaux`) et `passage_complet()` qui fait un passage entier |
| `migrations.py` | Applique les fichiers SQL manquants (dossier `migrations/`) et note ce qui est appliqué dans la table `schema_migrations` |
| `orchestration.py` | Le **flow Prefect** `collecte`, planifié toutes les 10 minutes : collecte, puis tâches `nettoyage`, `rapport_qualite`, `controles_qualite` |

**Nettoyage et qualité (TD 4)**

| Fichier | Ce qu'il fait |
|---|---|
| `normalisation.py` | Fonctions pures, une par transformation : `retirer_html`, `decoder_entites`, `normaliser_espaces`, `reparer_encodage`, `vers_utc` (dates en UTC), `borner_extrait`, `normaliser_titre`, `nettoyer_lien`, `jaccard`, et `normaliser_article` qui assemble le tout. Aucune dépendance externe |
| `regles_config.py` | La **configuration lisible** des règles : motifs, listes de rubriques, seuils (tolérance de date 3 h, seuil de Jaccard 0,8, fenêtre de doublons 48 h). C'est le fichier qu'on règle |
| `regles.py` | `appliquer_regles()` : applique R05, R06, R07, R01, R02, R03, R04, R10 à un article ; la première règle qui s'applique gagne |
| `doublons.py` | Doublons exacts (R08) et approximatifs (R09) : `IndexDoublons` garde en mémoire les articles gardés et compare les nouveaux. Garde le plus ancien |
| `nettoyage.py` | Le nettoyage complet : lit les bruts jamais traités (`lire_bruts`), normalise et applique les règles (`traiter`), écrit dans `articles_propres` et `rejets` (`nettoyer`). Rejouable. Point d'entrée : `python -m gazette.nettoyage` |
| `rapport_qualite.py` | Calcule les chiffres du jour et écrit `rapports/qualite-AAAA-MM-JJ.md` (`rendre_markdown` met en forme, `ecrire_rapport` écrit le fichier) |
| `controles.py` | Les 4 contrôles sur les vraies données, écriture dans `controles_qualite`, envoi de l'alerte avec anti-spam de 6 h |
| `alerte.py` | `envoyer_alerte()` : envoie un message au webhook Discord avec la bibliothèque standard. Ne plante jamais le pipeline ; ne montre jamais l'adresse dans les logs |
| `connexion.py` | `ouvrir_connexion()` : ouvre la connexion PostgreSQL (variable `DATABASE_URL`) |
| `qualite.py` | Enchaîne nettoyage, rapport et contrôles (`passage_qualite`) ; chaque étape reste appelable seule |
| `embeddings.py` | TD 5 : lit les articles des dernières 24 h (`lire_articles`), les vectorise avec cache (`vectoriser`, table `embeddings`) ; le modèle est chargé à la première utilisation et sa version (commit Hugging Face) est notée |
| `themes.py` | TD 5 : un run complet (`executer_run`) : empreinte de l'entrée, BERTopic (`regrouper`), noms (`nommer`), métriques (`calculer_metriques`), écriture de `themes`, `articles_themes`, `runs_themes`. Point d'entrée : `python -m gazette.themes [--forcer]` |
| `suivi_runs.py` | TD 5 : envoi de chaque run à MLflow ; une panne de MLflow n'arrête jamais le run (`SuiviTolerant`) |

**Thèmes (TD 5, prévu, noms indicatifs)** : voir section 13.

### 10.4 `src/gazette/migrations/` : les tables

| Fichier | Table créée |
|---|---|
| `001_sources.sql` | `sources` : état de chaque source (active, échecs consécutifs, dernière réussite, dernière erreur) |
| `002_collectes.sql` | `collectes` : une ligne par collecte d'une source (reçus, écrits, ignorés, durée) |
| `003_articles_propres.sql` | `articles_propres` : les articles gardés (couche Silver) |
| `004_rejets.sql` | `rejets` : les articles écartés avec la règle et l'éventuel article conservé |
| `005_controles_qualite.sql` | `controles_qualite` : le résultat de chaque contrôle |
| `006_themes.sql` | TD 5 : `embeddings` (cache), `runs_themes` (un run = une ligne), `themes`, `articles_themes`, et la vue `themes_du_jour` (thèmes du dernier run réussi) |

Règle : on n'**édite jamais** une migration déjà appliquée ; on en ajoute une nouvelle avec le numéro suivant (`006_...`). Si deux personnes créent le même numéro sur deux branches, renommer l'une avant de fusionner.

### 10.5 `tests/`

| Fichier | Ce qu'il teste |
|---|---|
| `test_collecte.py` | lecture d'un flux et bornage (TD 3) |
| `test_collecteur.py` | la boucle de collecte contre un faux serveur HTTP (TD 3) |
| `test_registre_postgres.py` | les tables de suivi des sources (vraie base, ignoré en local) |
| `test_normalisation.py` | chaque fonction de normalisation |
| `test_regles.py` | chaque règle : rejeté, conservé, cas limite |
| `test_doublons.py` | doublons exacts et approximatifs |
| `test_nettoyage.py` | le nettoyage ; avec une vraie base : zéro doublon sur deux passages, rejets tracés, contrôles et alerte |
| `test_rapport_qualite.py` | la mise en forme du rapport |
| `test_alerte.py` | l'alerte Discord, sans réseau |
| `fixtures/` | des flux d'exemple **inventés** (aucun contenu de presse dans le dépôt) |

### 10.6 `docs/`

| Fichier | Contenu |
|---|---|
| `cadrage.md` | le besoin, le bornage, l'architecture visée, les choix argumentés (voir section 12 pour les écarts avec la réalité) |
| `architecture.jpg` | le schéma d'architecture |
| `ci-cd.md` | la stratégie CI/CD |
| `donnees.md` | le contrat de données : schéma des tables, fraîcheur, rétention, ce qu'on ne stocke pas, traçabilité |
| `qualite.md` | les règles d'exclusion (nom, ce qu'elle écarte, pourquoi, exemple réel), les contrôles, les ajustements |
| `journal.md` | le journal de bord : incidents, correctifs, sources réveillées |
| `mlops.md` | (TD 5, à créer) modèles, paramètres, où lire les runs |

### 10.7 Dossiers de données (sur votre machine)

| Dossier | Contenu |
|---|---|
| `data/articles_bruts/<source>/` | un JSON par article. **Jamais commité.** Chaque machine a le sien : la collecte se fait localement |
| `rapports/` | un rapport de qualité par jour. Archivé dans le dépôt (réécrit à chaque passage) |

## 11. Travailler en équipe : branches, pull et fusion

Chacun·e a sa branche. Le principe de `CONTRIBUTING.md` : une branche par sujet, une **pull request** (PR) sur GitHub relue par quelqu'un d'autre, une CI verte avant de fusionner.

> Le nom de la branche principale (`main` ou `master`) se voit avec `git branch -a`. Dans les commandes ci-dessous, remplacez `main` par le vôtre.

### 11.1 Savoir où on en est

```bash
git status                 # fichiers modifiés (doit être propre avant de changer de branche)
git branch                 # branche actuelle (marquée d'une étoile)
git branch -a              # toutes les branches, y compris celles de GitHub
git log --oneline -10      # les 10 derniers commits
```

### 11.2 Essayer le travail de quelqu'un d'autre (sans toucher à sa branche)

Exemple : récupérer le TD 4 de Jason pour le tester.

```bash
git fetch origin                 # télécharge les nouveautés de GitHub (ne modifie rien chez vous)
git switch jason                 # passe sur sa branche (la crée localement la première fois)
git pull                         # met la branche à jour
docker compose up --build -d     # reconstruit avec son code
bin/test                         # vérifie que tout passe
```
Pour revenir sur votre branche : `git switch <votre-branche>`.

### 11.3 Récupérer le travail d'un·e autre dans SA branche

Exemple : la personne du TD 5 veut le TD 4 (nettoyage) dans sa propre branche.

```bash
git status                       # doit être propre ; sinon : git add . puis git commit, ou git stash
git fetch origin
git merge origin/jason           # fusionne la branche jason dans la branche actuelle
```

Si Git écrit `CONFLICT` : deux personnes ont modifié le même endroit d'un fichier.
1. `git status` liste les fichiers en conflit.
2. Ouvrir chacun dans VS Code : les passages à arbitrer sont encadrés par `<<<<<<<`, `=======` et `>>>>>>>`. Garder le bon contenu (souvent les deux, mélangés) et supprimer les marqueurs.
3. `git add <fichier>` pour chaque fichier réglé, puis `git commit`.
4. Relancer `bin/test` avant de continuer.

Fichiers où les conflits sont **probables** : `README.md`, `docker-compose.yml`, `src/gazette/orchestration.py`, `requirements.txt`, les fichiers de `docs/`, et les migrations (deux fichiers `006_...` sur deux branches).

Pour abandonner une fusion qui se passe mal : `git merge --abort`.

### 11.4 Le flux recommandé (par pull request)

1. Vous travaillez et committez sur votre branche.
2. `git push` envoie la branche sur GitHub.
3. Sur GitHub, ouvrir une **pull request** de votre branche vers `main`.
4. Un·e coéquipier·ère relit, la **CI doit être verte**, puis on fusionne.
5. Tout le monde se met à jour :
   ```bash
   git switch main
   git pull
   git switch <votre-branche>
   git merge main
   ```

Premier push d'une nouvelle branche : `git push -u origin <votre-branche>`.

### 11.5 Après chaque pull ou fusion

1. Le fichier `.env` existe-t-il sur cette machine ? (`git check-ignore -v .env`).
2. `docker compose up --build -d` (le code est copié dans l'image ; long si `requirements.txt` a changé).
3. `bin/test`.
4. Les migrations s'appliquent toutes seules au prochain passage ; vérifier avec `\dt` dans `psql`.

### 11.6 Avant chaque commit

```bash
git status                 # lire la liste : ni .env, ni data/, aucun secret
git add .
git status                 # relire
git commit -m "message clair"
git push
```
Ne jamais commiter : `.env`, `data/`, l'adresse d'un webhook, un mot de passe. Un secret commité reste dans l'historique : il faut alors le révoquer (supprimer le webhook et en créer un nouveau).

## 12. Choix techniques

### TD 3

| Besoin | Retenu | Écartés |
|---|---|---|
| Orchestration | **Prefect** : planification en code, historique, reprise | cron (ni historique ni reprise) · Dagster (plus long à prendre en main pour un seul flow) |
| Migrations | **Fichiers SQL numérotés + petit script** | Alembic (pensé pour un ORM qu'on n'utilise pas) · création à la main (pas reproductible) |
| Lecture des flux | **feedparser** | lxml / xml.etree (RSS, Atom, dates et encodages à gérer à la main) |
| Téléchargement | **httpx** | requests (délais moins fins) · aiohttp (asynchrone, plus complexe) |
| Stockage brut | **Un JSON par article** | un gros fichier par jour (dédoublonnage plus compliqué) |

### TD 4

| Besoin | Retenu | Écartés |
|---|---|---|
| Règles d'exclusion | **Module Python de configuration** (regex, listes, seuils) | modèle d'apprentissage (hors périmètre, pas explicable) · fichier YAML (dépendance de plus) |
| Doublons approximatifs | **Similarité de Jaccard** sur les mots du titre | distance d'édition (plus coûteuse, moins adaptée à des titres de longueurs différentes) |
| Contrôles de données | **Assertions maison en SQL** | Great Expectations, Soda (dépendance et configuration lourdes pour 4 faits simples) |
| Canal d'alerte | **Webhook Discord** | e-mail (configuration SMTP pénible) · Slack (compte et application à créer) |
| Envoi de l'alerte | **`urllib` de la bibliothèque standard** | requests, httpx (dépendance de plus pour un seul appel) |
| Suivi des résultats | **Table `controles_qualite`** | métriques en mémoire (perdues à chaque passage, les flows sont de courte durée) |

### TD 5

| Besoin | Retenu | Écartés |
|---|---|---|
| Modèle d'embedding | **paraphrase-multilingual-MiniLM-L12-v2** : multilingue, léger, CPU | multilingual-e5-small (préfixe « query: » obligatoire) · API d'embeddings (clé, coût, données chez un tiers) |
| Regroupement | **BERTopic** (UMAP + HDBSCAN), validé au cadrage | K-means (nombre de thèmes fixé à l'avance) · hiérarchique seul (seuil de coupe, pas de noms) |
| Nommage | **Mots-clés c-TF-IDF** | LLM (non demandé, coût, non reproductible) · mots les plus fréquents (communs à tous les thèmes) |
| Suivi des runs | **MLflow + table `runs_themes`** | table seule (pas d'interface ni d'artefacts) · W&B (en ligne) · DVC (compare moins bien les runs) |
| Cache des vecteurs | **Table `embeddings`** | fichier .npy (à synchroniser avec la base) · pgvector (inutile sans recherche de voisins) |
| Paramètres | **YAML** (`config/clustering.yaml`) | TOML (PyYAML déjà présent avec MLflow) · variables d'environnement (illisibles) |

Détail et arguments : [docs/mlops.md](docs/mlops.md).

Les autres choix (supervision, infrastructure en code...) sont argumentés dans le [cadrage](docs/cadrage.md).

**Écarts connus entre `docs/cadrage.md` et la réalité** (à corriger dans le cadrage) :
- le brut est **un JSON par article**, pas du Parquet ni du JSONL ;
- la collecte tourne **toutes les 10 minutes** (fréquence par source), pas « toutes les heures » ;
- les alertes partent **directement du pipeline vers Discord** ; Healthchecks.io, UptimeRobot, Prometheus, Grafana et Alertmanager sont prévus au TD 8 ;
- couches : Bronze = fichiers JSON, Silver = `articles_propres`, Gold = thèmes (TD 5).

## 13. TD 5 : thèmes

Tout est expliqué dans [docs/mlops.md](docs/mlops.md) : modèle, paramètres, ce que trace chaque run, où le lire.

En bref : la tâche Prefect `themes` vient après le nettoyage, au plus une fois par heure. Elle vectorise titre + extrait des articles propres des dernières 24 h (cache dans `embeddings`), regroupe avec BERTopic, nomme chaque thème par ses mots-clés, écrit `themes` et `articles_themes`, et trace le run dans `runs_themes` et dans MLflow (http://localhost:5000). Les thèmes en base portent le `run_id` qui les a produits ; la vue `themes_du_jour` donne ceux du dernier run réussi.

**Pour la prochaine séance (TD 6)** : laisser tourner pour garder les runs ; relire à la main les thèmes de deux journées et noter dans `docs/mlops.md` (section 7) ce qui est bon, ce qui est absurde, et une hypothèse.

**Points d'attention :**
- Un `git pull` qui touche `requirements.txt` relance une longue construction : la lancer tôt, PC éveillé.
- Si `torch==2.14.1+cpu` n'est pas trouvé à la construction, la version n'existe pas encore sur l'index CPU : prendre la dernière version listée sur https://download.pytorch.org/whl/cpu/torch/ et la noter ici.
- Le port 5000 est pris sur certains Mac (AirPlay) : changer `"5000:5000"` en `"5001:5000"` dans `docker-compose.yml`.

## Contribuer

Voir [CONTRIBUTING.md](CONTRIBUTING.md) : une branche par sujet, une pull request revue par quelqu'un d'autre, une CI verte avant de fusionner. Le guide Git de la section 11 explique les commandes.

## Documentation

- [Cadrage](docs/cadrage.md)
- [Schéma d'architecture](docs/architecture.jpg)
- [Stratégie CI/CD](docs/ci-cd.md)
- [Données : contrat et dictionnaire](docs/donnees.md)
- [Qualité : règles d'exclusion et contrôles](docs/qualite.md)
- [Journal de bord](docs/journal.md)

## Bornage

Seuls le titre, l'extrait, le lien, la date et la rubrique sont conservés : jamais l'article entier, jamais les images, jamais l'auteur, jamais les commentaires. Aucune donnée personnelle. Le robot s'identifie honnêtement (`LaGazette-Efrei`) et ne lit que les flux RSS, jamais les pages d'articles. Aucun secret dans le code, les tests, les logs ni les commits. Projet de cours, jamais publié.