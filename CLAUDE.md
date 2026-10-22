# CLAUDE.md - La gazette

Projet M2Ops (M2 Data Engineering & IA, Efrei, 2026-2027). Pipeline qui collecte la presse par flux RSS, garde ce qui mérite d'être dans une gazette, regroupe par thèmes et publie une édition à 7 h. L'accent est mis sur l'exploitation : ce qui compte, c'est que ça tourne seul et qu'on puisse le prouver.

Lis `README.md`, `docs/cadrage.md` et `docs/donnees.md` avant de proposer quoi que ce soit.

## Façon de travailler

- **Plan d'abord.** Pour toute tâche non triviale, propose un plan en étapes et attends mon accord avant de coder.
- **Tests d'abord.** Écris le test, vois-le échouer, puis écris le code.
- **Petits pas.** Une tâche = une branche = un diff court que je peux relire. Ne touche pas aux fichiers sans rapport avec la tâche.
- **Explique.** Pour chaque choix (outil, seuil, algorithme), dis en deux phrases pourquoi et quelle alternative tu as écartée. Je dois pouvoir l'expliquer à la soutenance.
- **Ne devine pas.** Si une décision dépend de nos données réelles ou d'un choix d'équipe, pose la question au lieu de trancher.
- **Journal.** À la fin d'une tâche, résume en 2 à 3 lignes ce qui a été généré avec ton aide, pour que je le note dans `docs/journal.md`.

## Commandes

| Je veux... | Commande |
|---|---|
| Lancer tout | `docker compose up --build -d` |
| Lint + tests (comme la CI) | `bin/test` (Windows : `.\bin\test.ps1`) |
| Un passage de collecte sans Prefect | `docker compose run --rm orchestrateur gazette.collecteur` |
| Ouvrir la base | `docker compose exec postgres psql -U gazette -d gazette` |

État attendu des tests : `19 passed, 3 skipped` (les 3 ignorés demandent une vraie base PostgreSQL et tournent en CI). Ne jamais pointer `GAZETTE_TEST_DATABASE_URL` vers une base qui contient des données : elle est vidée.

## Architecture en bref

- `src/gazette/collecte.py` : lecture d'un flux, ne garde que les champs autorisés.
- `src/gazette/brut.py` : un JSON par article dans `data/articles_bruts/<source>/<id>.json`, id = SHA-256 de (source, lien). Jamais réécrit.
- `src/gazette/registre.py` : tables `sources` et `collectes`.
- `src/gazette/collecteur.py` : boucle de collecte (politesse, reprises, mise en sommeil).
- `src/gazette/orchestration.py` : flow Prefect, toutes les 10 minutes.
- `src/gazette/migrations/` : SQL numérotés (`001_sources.sql`, `002_collectes.sql`), appliqués par `migrations.py`. Les suivantes commencent à `003`.
- `tests/` avec des flux d'exemple inventés dans `tests/fixtures/`.

## Conventions

- **Le pipeline n'est pas Prefect.** Le code métier est fait de fonctions Python ordinaires, appelables sans Prefect. Prefect ne fait que planifier et appeler.
- **Fonctions pures** pour la normalisation et les règles : entrée, sortie, pas d'effet de bord, un test chacune.
- **Rejouable.** Toute écriture en base doit pouvoir être relancée sans doublon (`ON CONFLICT ... DO NOTHING` ou équivalent).
- **Migrations versionnées**, jamais de modification d'une migration déjà appliquée.
- **Logs en JSON**, une ligne par événement utile.
- Lint avec `ruff`, tests avec `pytest`. La CI doit rester verte.

## Bornage (non négociable)

- On ne garde que **titre, extrait, lien, date, rubrique** et la source. Jamais l'article entier, les images, les commentaires.
- **Aucune donnée personnelle** : jamais `author` ni `dc:creator`.
- Le robot s'identifie (`LaGazette-Efrei`), lit seulement les flux RSS, jamais les pages d'articles.
- On ne contourne pas un refus d'un éditeur (403, robots.txt).
- Aucun contenu réel de presse dans le dépôt : les fixtures sont inventées.
- `data/` n'est jamais commité.

## Secrets

- Aucun secret dans le code, les tests, les logs ni les commits. L'URL du webhook Discord vient d'une variable d'environnement lue depuis `.env`, qui est ignoré par Git. Vérifie `.gitignore` avant d'ajouter un fichier.
- Si tu vois un secret dans un fichier, arrête-toi et préviens-moi.

## Tâche en cours : TD 4 (nettoyer, contrôler, stocker)

Objectif : entre le brut et la gazette, trier. Livrable : règles d'exclusion documentées et testées, `articles_propres` alimentée, rapport de qualité produit à chaque passage.

À produire, dans cet ordre, en proposant un plan avant chaque étape :

1. **Normalisation** : HTML retiré des titres et extraits, espaces, entités, encodage cassé (`Ã©`), dates en UTC, extrait borné. Une fonction pure par transformation, un test par fonction.
2. **Règles d'exclusion** : un identifiant chacune (`R01_publi`, `R02_horoscope`, ...), dans un fichier de configuration lisible (regex, listes, seuils), pas un modèle. Un rejet garde la première règle qui s'applique. Chaque règle est décrite dans `docs/qualite.md` (nom, ce qu'elle écarte, pourquoi, un exemple).
3. **Doublons approximatifs** : titres normalisés proches (Jaccard sur les mots ou distance d'édition), seuil à régler avec moi sur des exemples réels.
4. **Tables** : migrations `003` (`articles_propres`, couche Silver) et `004` (`rejets`). Garder l'`item_id` du brut pour retrouver le fichier d'origine (traçabilité).
5. **Rapport de qualité** : `rapports/qualite-AAAA-MM-JJ.md` avec entrés, gardés, rejetés par règle et par source, et les cinq rejets les plus fréquents.
6. **Contrôles sur les vraies données** : tâche après chaque passage (aucune date future, aucun titre vide, taux de rejet par source sous 80 %). Écrire les chiffres dans une table `controles_qualite` (le TD 8 les lira) et alerter sur Discord quand un fait est faux.
7. **Docs** : `docs/qualite.md` et `docs/donnees.md` complété (schéma, fraîcheur, rétention, ce qu'on ne stocke pas).

Hors périmètre du TD 4 : regroupement en thèmes (TD 5), supervision (TD 8).

## Décisions que je dois prendre, pas toi

- Quelles règles garder et leurs seuils (propose, je valide sur des échantillons).
- Dépêches d'agence : rejeter ou garder.
- Durée de conservation du brut et des éditions.
- Outil de contrôle (dédié ou assertions maison) : donne-moi les arguments, je choisis.
