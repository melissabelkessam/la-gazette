# PLAN_TD4.md - Nettoyer, contrôler, stocker (à donner à Claude Code)

Contexte : projet La gazette (voir `CLAUDE.md`, `README.md`, `docs/cadrage.md`, `docs/donnees.md`). Le TD 3 est terminé : la collecte écrit un JSON par article dans `data/articles_bruts/<source>/<item_id>.json` (item_id = SHA-256 de (source, lien), identique au nom du fichier). Le TD 4 ajoute le tri entre le brut et la gazette.

Délai : environ 1 heure. Le livrable est jugé sur : règles documentées et testées, `articles_propres` alimentée à chaque passage, rapport de qualité à chaque passage, contrôles sur les vraies données, alerte qui a sonné une fois.

## Comment tu travailles (Claude Code)

1. **Une étape à la fois.** Fais l'étape demandée, puis STOP. N'enchaîne pas sans que je dise « ok ».
2. **À la fin de chaque étape :** lance `bin/test`, liste les fichiers créés ou modifiés, résume en 3 lignes ce que tu as fait et pourquoi, puis propose le message de commit. Je commit moi-même.
3. **Aucune nouvelle dépendance Python.** Bibliothèque standard seulement (`re`, `html`, `unicodedata`, `datetime`, `email.utils`, `urllib.request`, `json`, `pathlib`). Ne modifie pas `requirements.txt` ni `requirements-dev.txt` : reconstruire l'image prend 40 minutes. Les changements de code seuls se reconstruisent vite grâce au cache.
4. **Ne devine pas les données.** Les noms de champs des JSON bruts et les motifs des règles viennent des vrais fichiers de `data/articles_bruts/`, pas de ton imagination.
5. **Fixtures de tests inventées.** Aucun contenu réel de presse dans `tests/`.
6. **Secrets.** L'URL du webhook Discord vient de la variable d'environnement `DISCORD_WEBHOOK_URL`. Jamais dans le code, les tests, les logs ni les commits.
7. **Pipeline sans Prefect.** Chaque nouveau module doit marcher en ligne de commande (`python -m gazette.<module>`), Prefect ne fait que l'appeler.
8. **Points où tu dois t'arrêter et me demander :** les motifs de règles (je valide sur des exemples réels), les seuils, la politique sur les dépêches d'agence, et tout ce qui touche à `docker-compose.yml`.

## À faire par l'humain (pas par Claude Code)

- Créer le webhook Discord et mettre `DISCORD_WEBHOOK_URL=...` dans un fichier `.env` ignoré par Git.
- Valider les motifs et seuils proposés.
- Déclencher l'alerte pour de vrai et faire la capture d'écran (étape 8).
- Écrire le journal de bord (`docs/journal.md`) et la partie « pourquoi » de `docs/qualite.md`.

---

## Étape 0 - Lire et inspecter (aucun code)

- Lis `CLAUDE.md`, `README.md`, `docs/donnees.md`, `docs/cadrage.md`, `src/gazette/` (surtout `brut.py`, `registre.py`, `migrations.py`, `orchestration.py`) et `docker-compose.yml`, `Dockerfile`.
- Ouvre 5 JSON de sources différentes dans `data/articles_bruts/` et liste leurs champs exacts.
- Vérifie : le dossier `data/` est-il monté en volume dans `docker-compose.yml` ? Existe-t-il un volume pour un dossier `rapports/` ?
- Vérifie que `.env` est dans `.gitignore`.
- Réponds avec : les champs des JSON, les migrations existantes, comment `migrations.py` numérote, comment `orchestration.py` est construit, ce qu'il faudra ajouter au compose (sans l'écrire).
- STOP.

## Étape 1 - Les pollueurs, sur les vraies données

- Écris un petit script jetable (hors dépôt, ou dans `/tmp`) qui parcourt `data/articles_bruts/` et, pour chaque type de pollueur ci-dessous, affiche le nombre d'articles concernés et 3 vrais titres avec leur source :
  publi-reportages et « contenus partenaires », horoscope, programmes TV, jeux et concours, titres vides, dates dans le futur, encodage cassé (`Ã©`, `â€™`), préfixes « DIRECT » et « DIAPORAMA », doublons exacts de titre, quasi-doublons de titre.
- Propose en plus tout autre type de pollueur que tu repères.
- Ne crée aucune règle dans le dépôt. Donne-moi le tableau (type, nombre, 3 exemples, motif envisagé). C'est moi qui valide.
- STOP.

## Étape 2 - Normalisation (`src/gazette/normalisation.py`, `tests/test_normalisation.py`)

Fonctions pures, une par transformation, un test chacune (cas normal, cas limite, entrée vide) :

- `retirer_html(texte)` : balises et attributs retirés.
- `decoder_entites(texte)` : `&amp;`, `&#39;`, etc.
- `normaliser_espaces(texte)` : espaces multiples, insécables, retours à la ligne.
- `reparer_encodage(texte)` : répare le mojibake courant (`Ã©` -> `é`) sans casser un texte déjà correct.
- `vers_utc(date_texte)` : formats RSS (`GMT`, `+0000`, `+0200`) et ISO, résultat `datetime` avec fuseau UTC ; renvoie `None` si illisible.
- `borner_extrait(texte, max_car=300)` : coupe proprement à la fin d'un mot.
- `normaliser_titre(texte)` : minuscules, sans accents, sans ponctuation, pour comparer.
- `normaliser_article(brut_dict)` : applique le tout et renvoie un dict propre (titre, extrait, lien, rubrique, publie_le, source, item_id). N'invente aucun champ absent du brut.

Aucune dépendance externe. STOP.

## Étape 3 - Règles d'exclusion (`src/gazette/regles_config.py`, `src/gazette/regles.py`, `tests/test_regles.py`)

- Configuration lisible dans `regles_config.py` (regex compilées, listes de mots, seuils), pas dans un modèle. Un module Python plutôt qu'un fichier YAML (pas de dépendance, et il est copié dans l'image avec `src/`).
- Un identifiant par règle, ordre d'application figé, la première règle qui s'applique gagne :
  `R01_publi`, `R02_horoscope`, `R03_tv`, `R04_jeux`, `R05_titre_vide`, `R06_date_future`, `R07_encodage_casse`, `R10_direct_diaporama` (règles unitaires), puis `R08_doublon_exact` et `R09_doublon_approx` (règles de comparaison, étape 4).
- Motifs issus de l'étape 1, validés par moi. Pas de motif inventé.
- `appliquer_regles(article) -> (regle_id | None, detail)`.
- Tests sur des **fixtures inventées** : au moins un article rejeté et un article conservé par règle, plus un cas limite par règle (faux positif possible).
- Une règle qui rejette plus de 80 % des articles d'une source doit être signalée dans le rapport (étape 6).
- STOP.

## Étape 4 - Doublons (`src/gazette/doublons.py`, `tests/test_doublons.py`)

- `R08_doublon_exact` : même titre normalisé qu'un article déjà conservé (fenêtre de 48 h).
- `R09_doublon_approx` : similarité de Jaccard sur les mots du titre normalisé supérieure ou égale à un seuil (défaut proposé : 0,8, à régler avec moi sur des paires réelles).
- L'article le plus ancien est conservé ; le rejeté garde `doublon_de` = l'`item_id` de l'article conservé.
- Montre-moi 5 paires réelles proches et 5 paires limites avant de figer le seuil.
- Politique sur les dépêches d'agence reprises par plusieurs titres : **question ouverte**, demande-moi. Par défaut, elles sont traitées par R09 (on garde la plus ancienne).
- STOP.

## Étape 5 - Base de données (migrations, `src/gazette/nettoyage.py`, `tests/test_nettoyage.py`)

Migrations numérotées, à la suite des existantes, sans modifier les anciennes :

- `003_articles_propres.sql` : `item_id` (clé unique, = nom du fichier brut), `source`, `titre`, `extrait`, `lien`, `rubrique`, `publie_le` (timestamptz UTC), `date_estimee` (boolean, vrai si la date a été remplacée par l'heure de collecte), `collecte_le`, `nettoye_le` (défaut now). Index sur `publie_le` et `source`.
- `004_rejets.sql` : `item_id` (unique), `source`, `titre`, `lien`, `regle`, `detail`, `doublon_de`, `rejete_le` (défaut now). Index sur `regle` et `source`.
- `005_controles_qualite.sql` : `id`, `horodatage`, `nom`, `portee` (ex. une source ou « global »), `valeur`, `seuil`, `ok` (boolean), `detail`.

`nettoyage.py` :

- Lit les JSON bruts dont l'`item_id` n'est ni dans `articles_propres` ni dans `rejets` (donc rejouable et incrémental).
- Normalise, applique les règles, insère dans `articles_propres` ou `rejets`, avec `ON CONFLICT (item_id) DO NOTHING`.
- Journalise une ligne JSON par passage (entrés, gardés, rejetés par règle, durée), dans le même style que `collecteur.py`.
- Point d'entrée : `python -m gazette.nettoyage`.
- Traçabilité : de n'importe quelle ligne propre ou rejetée, `item_id` + `source` retrouvent `data/articles_bruts/<source>/<item_id>.json`.
- Tests de base de données marqués comme les existants (`GAZETTE_TEST_DATABASE_URL`, ignorés sans base) : « deux passages, zéro doublon », « un article rejeté va dans rejets avec sa règle ».
- STOP.

## Étape 6 - Rapport de qualité (`src/gazette/rapport_qualite.py`, `tests/test_rapport_qualite.py`)

- Génère `rapports/qualite-AAAA-MM-JJ.md` (recalculé à chaque passage à partir de la base, pour la journée en cours) :
  entrés, gardés, rejetés ; rejetés par règle ; par source (entrés, gardés, rejetés, taux de rejet) ; les 5 rejets les plus fréquents avec 2 titres d'exemple chacun ; les règles qui rejettent plus de 80 % d'une source (signal « règle trop gourmande »).
- Le rapport doit permettre de repérer une règle trop gourmande : sinon il ne sert à rien.
- Vérifie dans `docker-compose.yml` que `rapports/` est monté en volume pour survivre au conteneur ; propose la modification (c'est un changement de compose, demande-moi d'abord).
- Point d'entrée : `python -m gazette.rapport_qualite`.
- STOP.

## Étape 7 - Contrôles et alerte (`src/gazette/controles.py`, `src/gazette/alerte.py`, tests)

`controles.py` : vérifie des faits sur les vraies données, écrit chaque résultat dans `controles_qualite` et renvoie la liste des échecs :

- aucune date future dans `articles_propres` ;
- aucun titre vide dans `articles_propres` ;
- taux de rejet par source inférieur ou égal à 80 % (ignorer une source avec moins de 10 articles entrés) ;
- au moins 1 article propre dans les dernières 24 h (source par source, signalement seulement).

Choix à justifier en 3 lignes dans `docs/qualite.md` : assertions maison en SQL plutôt qu'un outil dédié (Great Expectations, Soda), pour notre volume.

`alerte.py` :

- `envoyer_alerte(message)` : POST JSON vers le webhook Discord avec `urllib.request`, URL lue dans `DISCORD_WEBHOOK_URL`.
- Si la variable est absente : log d'avertissement, pas de plantage. L'URL n'apparaît dans aucun log.
- Message court : nom du contrôle, valeur, seuil, source concernée.
- Tests : aucun appel réseau (remplace l'envoi par un faux).

`docker-compose.yml` : transmettre la variable au service `orchestrateur` (`env_file: .env` ou `environment`), ajouter `.env.example` sans valeur réelle. Demande-moi avant de modifier le compose.

Point d'entrée : `python -m gazette.controles`. STOP.

## Étape 8 - Brancher dans Prefect (`src/gazette/orchestration.py`)

- Dans le flow `collecte` existant, après la collecte : tâche `nettoyer`, puis `rapport_qualite`, puis `controler`.
- La collecte reste prioritaire : une erreur de nettoyage ne doit pas faire perdre ce qui est déjà écrit. Le flow peut finir en échec visible dans Prefect, mais les fichiers bruts restent.
- Les fonctions métier restent appelables sans Prefect.
- Je reconstruis et relance moi-même (`docker compose up --build -d`), puis je lance un passage à la main.
- **Alerte pour de vrai (par moi) :**
  1. insérer à la main une ligne de test dans `articles_propres` avec une date future (`psql`) ;
  2. lancer `docker compose exec orchestrateur python -m gazette.controles` ;
  3. vérifier le message sur Discord, faire une capture d'écran ;
  4. supprimer la ligne de test.
- STOP.

## Étape 9 - Documentation

Rédige un premier jet, je le relis et j'écris moi-même les « pourquoi » :

- `docs/qualite.md` : pour chaque règle (identifiant, ce qu'elle écarte, pourquoi, un vrai exemple avec sa source, seuil), les dix pollueurs de l'étape 1, le choix « assertions maison », une section vide « Ajustements après lecture du rapport » à remplir plus tard.
- `docs/donnees.md` (complété) : schéma de `articles_propres`, `rejets`, `controles_qualite` ; fraîcheur attendue ; rétention (proposition : brut 90 jours, éditions de plus d'un mois archivées) ; ce qu'on ne stocke pas ; traçabilité (de l'article propre vers le JSON brut).
- `README.md` : tableau « Où en est le projet » (TD 4 en cours), commandes `python -m gazette.nettoyage`, `gazette.rapport_qualite`, `gazette.controles`.
- Une entrée de brouillon pour `docs/journal.md` : ce qui a été généré avec Claude Code et ce qui a été vérifié à la main (je la complète).
- STOP.

## Étape 10 - Vérification finale

- `bin/test` vert (lint et tests).
- Un passage de collecte complet, puis vérifier : `articles_propres` et `rejets` se remplissent, `rapports/qualite-AAAA-MM-JJ.md` existe, `controles_qualite` contient des lignes.
- Un deuxième passage : aucun doublon dans `articles_propres` ni `rejets`.
- `git status` : ni `.env`, ni `data/`, ni l'URL du webhook ne sont suivis.
- Donne-moi le récapitulatif : fichiers créés, tests ajoutés, ce qui reste à faire par l'humain.

## Si le temps manque, couper dans cet ordre

1. Les doublons approximatifs (garder R08 seulement).
2. Le contrôle « au moins 1 article par source en 24 h ».
3. Réduire les règles à 5 ou 6 bien faites.

Ne jamais couper : `articles_propres`, `rejets`, le rapport, l'alerte qui a sonné, les tests.
