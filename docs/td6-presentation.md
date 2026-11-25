# TD 6 — Évaluer, versionner, déployer le modèle : ce qu'on a fait et comment le présenter

_Projet M2Ops · La gazette · M2-DE3 · Mélissa, Salma, Jason, Amelia_
_Branche : `feat/td6-modele` · PR #6 · Compétences : C7.4 (modèle évalué/déployé) + C7.2 (le changement passe par la CI)_

> **En deux phrases.** Au TD 5, un regroupement en thèmes tourne chaque jour. Au TD 6, on ajoute
> le contrôle qualité du **modèle** : une évaluation automatique avec seuils (un run raté ne publie
> pas), un registre de versions qui dit laquelle tourne, une promotion qui passe par la CI, et un
> retour arrière qu'on a exécuté pour de vrai.

---

## 1. À FAIRE LE MATIN (présentateur) — faire tourner le projet

Docker met **du temps** la première fois (≈ 1 Go : torch + le modèle d'embeddings se télécharge).
**Lance ça tôt, PC branché et réveillé.**

```bash
git switch feat/td6-modele
git pull
docker compose up --build -d        # long la 1re fois : laisse finir
docker compose ps                   # tout doit être "running"/"healthy"
```

Vérifier que ça vit :
- **MLflow** (comparaison des runs) : http://localhost:5000 → expérience `gazette-themes`.
- **La base** :
```bash
  docker compose exec postgres psql -U gazette -d gazette -c "SELECT run_id, statut, metriques->>'nb_themes' AS themes, metriques->>'verdict' AS verdict FROM runs_themes ORDER BY debut DESC LIMIT 5;"
```
- Forcer un run de thèmes tout de suite (sinon il tourne tout seul après la collecte) :
```bash
  docker compose exec orchestrateur python -m gazette.themes --forcer
```

Plan B si le réseau tombe : avoir une capture d'écran de MLflow et du `--lister` du registre.

---

## 2. Le TD 6 de A à Z (ce qu'on dit au prof)

Pour chaque point : **ce que le TP demandait → ce qu'on a fait → avec quoi → où c'est**.

### 2.1 L'évaluation automatique avec des seuils
- **Demandé** : juger un regroupement sans vérité terrain, avec des seuils, après chaque passage.
- **Fait** : après le regroupement et **avant d'écrire les thèmes**, le pipeline calcule les métriques
  (silhouette, part de bruit, taille des thèmes) et les compare aux seuils. Verdict enregistré sur le run.
- **Seuils (choix d'équipe, calés sur notre 1er vrai run : 313 articles, 18 thèmes, 21 % bruit, silhouette 0,10)** :
  `nb_themes_min=3`, `part_bruit_max=0,80`, `theme_geant_max=0,50` (aucun thème > 50 % des articles),
  `silhouette_min=0,05`.
- **Avec quoi** : un module Python pur (testé), des seuils dans un fichier de config.
- **Où** : `config/evaluation.yaml`, `src/gazette/evaluation.py`, branché dans `src/gazette/themes.py`.

### 2.2 Un run recalé ne touche pas aux thèmes en base
- **Demandé** : « un run recalé ne touche pas aux thèmes en base ».
- **Fait** : 3 verdicts — `ok` (publié) ; `recale` (un garde-fou franchi → **thèmes NON publiés**, les
  thèmes du jour restent ceux du dernier bon run) ; `revue` (dérive → publié mais signalé).
- **La dérive** : si un seuil « mou » est franchi **2 runs de suite** (bruit > 0,50 ou silhouette < 0,07),
  verdict `revue`, enregistré sur le run comme demandé.
- **L'alerte** : un run `recale` ou `revue` déclenche une **alerte Discord** (on réutilise le webhook du TD 4).
- **La relecture humaine** : `python -m gazette.evaluation --relire <run_id> --par <nom>` tire 10 articles au
  hasard, on dit à la main s'ils sont bien placés, le résultat est enregistré (table `relectures`).
- **Où** : `evaluation.py`, `themes.py`, tables `evaluations_themes` et `relectures` (migration `007`).

### 2.3 Le registre de versions + la version en service
- **Demandé** : une table `versions_modele` (version, run_id, statut, promue_le, par_qui) ; « quelle version
  tourne ce matin ? » répond en une requête ; le pipeline lit la version en service (plus de paramètres codés en dur).
- **Fait** : registre `versions_modele`, **au plus une version en `production`** (index unique partiel). Le
  pipeline lit ses paramètres **au démarrage** via `config_en_service` ; au tout premier run, le fichier
  `clustering.yaml` devient automatiquement la version `v1` (bootstrap).
- **La requête qui répond** : `SELECT * FROM version_en_service;` (une vue).
- **Où** : `src/gazette/registre_modele.py`, migration `007`, lecture branchée dans `themes.etape_themes`.

### 2.4 La promotion par la CI
- **Demandé** : changer un paramètre = une PR ; la CI évalue ; le merge promeut.
- **Fait** : un workflow `Promotion du modele` qui, sur une PR touchant `config/clustering.yaml` ou
  `config/evaluation.yaml`, **rejoue l'évaluation du modèle** (tests du regroupement, des seuils et du
  registre sur une base PostgreSQL). Si le modèle ne passe plus → PR rouge → merge bloqué.
- **Point honnête à assumer** : la **promotion réelle** s'exécute sur la machine qui fait tourner le
  pipeline (c'est elle qui porte la base de prod) — la CI de GitHub n'a pas accès à cette base. La CI
  sert donc de **garde-fou** et **rappelle la commande de promotion** au merge. C'est le découpage
  « PR → la CI évalue → on promeut », en étant clair sur où chaque chose s'exécute.
- **Où** : `.github/workflows/promotion.yml`, documenté dans `docs/mlops.md` §9.

### 2.5 Le retour arrière (testé en vrai)
- **Demandé** : revenir à la version précédente = une commande, documentée, exécutée au moins une fois.
- **Fait et EXÉCUTÉ le 25/11** : on a posé `v1` en production, changé un paramètre → `v2`, promu `v2`,
  puis `--retour-arriere` → le registre a rebasculé en `v1`. Tracé dans `docs/journal.md`.
- **La commande** : `python -m gazette.registre_modele --retour-arriere --par <nom>`.
- **Où** : `registre_modele.py`, trace dans `docs/journal.md` et `docs/mlops.md` §9.

### 2.6 La fiche modèle
- **Demandé** : ce que le modèle fait, les données, les métriques, les limites, qui décide d'une promotion.
- **Fait** : une fiche complète + le circuit documenté.
- **Où** : `docs/fiche-modele.md` et `docs/mlops.md` (sections 8 et 9).

---

## 3. La démo live (le prof passe voir « la version en service et un retour arrière »)

À lancer devant lui, dans l'ordre :

**a) Quelle version tourne, avec quels paramètres ?**
```bash
docker compose run --rm --no-deps orchestrateur gazette.registre_modele --en-service
docker compose exec postgres psql -U gazette -d gazette -c "SELECT version, promue_le, par_qui FROM version_en_service;"
```

**b) L'évaluation a bien tourné (verdict sur les runs) :**
```bash
docker compose exec postgres psql -U gazette -d gazette -c "SELECT run_id, verdict, publie, derive FROM evaluations_themes ORDER BY evalue_le DESC LIMIT 5;"
```

**c) Un retour arrière en direct** (on crée une v2, on la promeut, on revient) :
```bash
docker compose run --rm --no-deps orchestrateur gazette.registre_modele --lister
# promouvoir la v2 archivée pour la démo, puis revenir :
docker compose run --rm --no-deps orchestrateur gazette.registre_modele --promouvoir v2 --par <nom>
docker compose run --rm --no-deps orchestrateur gazette.registre_modele --retour-arriere --par <nom>
docker compose run --rm --no-deps orchestrateur gazette.registre_modele --lister
```
→ montrer que la production repasse à `v1`, et la trace (`promue_le`, `par_qui`).

**d) MLflow** : http://localhost:5000 → comparer deux runs, ouvrir leurs métriques et artefacts.

---

## 4. Les outils utilisés (et pourquoi)

| Besoin | Outil | Pourquoi |
|---|---|---|
| Orchestration | **Prefect** | le pipeline (collecte → nettoyage → thèmes → évaluation) tourne seul, décrit en code |
| Embeddings | **sentence-transformers** (MiniLM multilingue, CPU) | léger, multilingue, pas de clé ni de coût |
| Regroupement | **BERTopic** (UMAP + HDBSCAN + c-TF-IDF) | trouve seul le nombre de thèmes, accepte le bruit, nomme les groupes |
| Suivi des runs | **MLflow** + table `runs_themes` | comparer les runs (TD 6) et relier les thèmes à leur run |
| Base | **PostgreSQL 16** | articles, thèmes, runs, évaluations, versions |
| Conteneurs | **Docker Compose** | tourne pareil sur toutes les machines |
| Tests + lint | **pytest** + **ruff** | 2.4 tests automatisés ; la CI bloque le merge si c'est rouge |
| CI/CD | **GitHub Actions** | lint → tests → build ; + workflow de promotion |

---

## 5. Choix et limites qu'on assume (bon à dire à l'oral)

- **Pas de vérité terrain** : nos métriques sont internes (silhouette, bruit). On complète par une
  **relecture humaine** d'un échantillon. C'est voulu : on ne prétend pas mesurer une « justesse » absolue.
- **La promotion se fait là où vit la base de prod**, pas dans la CI (qui n'y a pas accès). La CI reste
  le garde-fou qui évalue et bloque une PR qui casserait le modèle.
- **Pas de recherche d'hyperparamètres automatique, pas d'A/B** : hors périmètre du TD 6, on est resté
  sur « un pipeline qui évalue, promeut, déploie et revient en arrière — propre ».
- `min_cluster_size` bas donne beaucoup de petits thèmes : réglage en cours, c'est justement ce que le
  registre + la promotion permettent de faire proprement (une PR, pas un `git push` à l'aveugle).

---

## 6. Ce qui reste (honnête)

- **Merger la PR #6** dans `main` une fois relue par un·e coéquipier·e (CI verte).
- **Remplir le tableau §7 de `docs/mlops.md`** : chacun·e relit les thèmes d'une journée (bon / absurde /
  hypothèse) — c'est la lecture humaine demandée par le prof, à ne pas inventer.