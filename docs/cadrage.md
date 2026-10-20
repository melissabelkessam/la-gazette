# La gazette - Document de cadrage

Projet M2Ops - M2 Data Engineering & IA - Efrei - 2026-2027 - Groupe M2-DE3
Équipe : Mélissa BELKESSAM, Salma DISSI, Jason MAMPOUYA , Amelia BOUKRI 
Version : 1.1 - 20 octobre 2026 

---

## 1. Le besoin

Chaque matin, lire la presse quotidienne régionale (PQR) et nationale (PQN) et dire de quoi elle parle. La gazette est un pipeline de données autonome : il collecte ce que publient les journaux, garde ce qui mérite d'être dans une gazette, regroupe les articles par thèmes, contrôle sa propre qualité et publie à 7 h l'édition du jour (thèmes, titres, sources, liens).

C'est un projet d'exploitation (M2Ops), pas de développement. La question n'est pas « est-ce que ça marche sur notre poste ? » mais « est-ce que ça a tourné tous les matins sans personne, et comment le prouve-t-on ? ». La réponse est écrite : métriques, alertes, bulletin quotidien et journal de bord (`docs/journal.md`, tenu à partir du TD 7).

## 2. Périmètre et bornage

| Règle | Conséquence pour le projet |
|---|---|
| Titres, extraits, liens, dates, rubriques uniquement | Aucun article complet, aucune image, aucun commentaire. Les champs `content:encoded` (risque de texte intégral) et les balises d'images sont retirés dès la collecte. |
| Respect de robots.txt et des conditions d'utilisation | Chaque source a été ouverte et vérifiée à la main (flux + robots.txt). Le résultat est consigné dans `sources.csv`. |
| Aucune donnée personnelle | Les champs `author` et `dc:creator` (noms et e-mails de journalistes) sont retirés dès la collecte, y compris du brut. Référence : guide RGPD de l'équipe de développement de la CNIL. |
| Budget zéro | Outils gratuits ou open source, sur nos machines jusqu'à l'infrastructure fournie (TD 4 ou 6). Tout coût éventuel est écrit et justifié. |
| Une édition par jour, à 7 h, de moins de 24 h de fraîcheur | Objectif de service mesuré et affiché en supervision. |

**Dedans :** collecte RSS, stockage brut et propre, nettoyage et rapport de qualité, regroupement en thèmes, édition de 7 h, supervision et alertes.
**Dehors :** scraping de pages, texte intégral, résumé par LLM, « beau front », comptes utilisateurs, personnalisation.

## 3. Objectifs de service

| Indicateur | Cible | Mesure |
|---|---|---|
| Publication | Tous les jours avant 7 h | Heure de publication, tracée dans les logs et exposée en métrique |
| Fraîcheur | Tous les articles de l'édition ont moins de 24 h | Âge maximal des articles de l'édition |
| Exhaustivité de la collecte | Aucun article perdu entre deux collectes | Contrôle de chevauchement à chaque collecte (section 6.3) |
| Disponibilité des sources | Au moins un article par source et par 24 h | Nombre d'articles collectés par source |
| Qualité | Taux de doublons et d'articles écartés suivis | Rapport de qualité produit à chaque run |

## 4. Sources

10 sources retenues (5 PQN, 5 PQR), toutes lues par flux RSS 2.0. Détail dans `sources.csv`.

| Statut après vérification | Sources |
|---|---|
| Autorisé sans réserve | Les Échos, La Croix, Sud Ouest, Midi Libre, La Dépêche du Midi |
| Autorisé par robots.txt, avertissements forts | Le Monde, Le Figaro, Libération |
| Interdit par robots.txt (`User-agent: *` / `Disallow: /`) | Ouest-France, Le Télégramme |
| Écartée | La Voix du Nord (flux bloqués par un pare-feu depuis décembre 2025) |

L'usage des sources restrictives est validé par l'enseignant pour ce projet de cours non publié : robots.txt n'empêche pas techniquement l'accès, mais l'interdit. Il faudrait retirer ces sources si la gazette devenait publique.

Pièges repérés en ouvrant les flux : fuseaux horaires différents (`GMT`, `+0000`, `+0200`), paramètres de suivi `utm_*` dans les liens (Ouest-France), même dépêche AFP reprise par plusieurs titres, articles « EN DIRECT » dont le titre change mais pas le lien, extraits absents ou tronqués, contenus hors actualité (programme TV), volumes très différents d'une source à l'autre.

## 5. Architecture

![alt text](gazette_workflow_2_(1)-1.jpg)

**Où ça tourne :** tout tourne dans des conteneurs Docker décrits par `docker-compose`, sur nos machines jusqu'au TD 4 ou 6, puis sur l'infrastructure fournie. Seuls Healthchecks.io et Discord sont hors de notre infrastructure, volontairement (section 9.3).

**Principe : l'orchestrateur n'est pas le pipeline.** Le code métier est fait de fonctions Python ordinaires, lançables sans Prefect (`python -m gazette.run --date AAAA-MM-JJ`). Prefect n'apporte que la planification, les reprises, l'historique et les logs. Si Prefect tombe, le pipeline peut être relancé à la main ou par le watchdog.

## 6. Données

### 6.1 Fréquence de collecte

Un flux RSS ne garde que ses derniers articles : le lire une seule fois par jour ferait perdre les articles de la veille. La collecte tourne donc en continu, et l'édition une fois par jour sur les articles stockés des dernières 24 h.

La fréquence est fixée par source dans `sources.csv` (colonne `frequence_min`), selon le temps que couvre son flux :

| Source | Mesure à la main (20/10) | Fréquence |
|---|---|---|
| Ouest-France | 10 articles couvrant environ 24 minutes en journée | 10 minutes |
| Les 9 autres | Flux couvrant plusieurs heures (de ~20 articles/jour pour Le Télégramme à ~95 pour La Dépêche) | 60 minutes |

Cela représente environ 360 requêtes par jour au total, réparties sur 10 sites. Les en-têtes `ETag` et `If-Modified-Since` évitent de retélécharger un flux inchangé.

### 6.2 Identifiant et doublons

Chaque article reçoit un `item_id` : l'empreinte SHA-256 de son lien **normalisé** (paramètres de suivi `utm_*` retirés). Le `guid` du flux sert de secours ; il est normalisé de la même façon, car celui d'Ouest-France contient lui aussi des paramètres `utm`.

- **Doublons techniques** (même article relu à chaque collecte) : bloqués au stockage brut. Avant d'écrire, la collecte lit les `item_id` déjà présents dans les fichiers Parquet du jour et de la veille, et n'écrit que les articles nouveaux. La collecte peut donc être rejouée sans créer de doublon.
- **Quasi-doublons** (même dépêche AFP dans plusieurs journaux, Midi Libre et La Dépêche du même groupe) : ce ne sont pas des doublons techniques. Ils sont regroupés par les thèmes, ou fusionnés au nettoyage (décision au TD 4).

### 6.3 Contrôle de chevauchement

À chaque collecte, on vérifie qu'au moins un article du flux était déjà connu. Si c'est le cas, les deux collectes se chevauchent et rien n'a été perdu. Si tous les articles sont nouveaux, des articles ont pu être manqués entre les deux collectes : une alerte est émise et la fréquence de la source est revue. Le taux de chevauchement par source est exposé en métrique dans Grafana. C'est ce qui permet de prouver, et non de supposer, que la collecte est complète.

### 6.4 Stockage

| Couche | Technologie | Contenu |
|---|---|---|
| Brut | Fichiers Parquet, un fichier par collecte : `brut/source=<source>/date=<date>/collecte_<HHMM>.parquet` | Une ligne par article nouveau : XML de l'article tel que reçu (champs interdits retirés), `item_id`, source, URL du flux, heure de collecte |
| Propre | PostgreSQL, contrainte d'unicité sur `item_id` | Articles normalisés (titre, extrait, lien, date en UTC, source, rubrique), thèmes, éditions publiées |

Le brut n'est jamais modifié : chaque collecte écrit un nouveau fichier, et on peut toujours rejouer le nettoyage. Le propre est petit (articles nettoyés seulement) et se prête aux requêtes du type « les articles des dernières 24 h ».

### 6.5 Qualité

Chaque run produit un rapport : articles collectés par source, doublons ignorés, articles écartés par règle, articles conservés, taux de chevauchement. Les règles (article sans extrait, contenus hors actualité, préfixes « DIRECT » ou « DIAPORAMA », articles en direct…) sont écrites et versionnées dans `docs/qualite.md`.

## 7. Thèmes

BERTopic, directement : embeddings multilingues (sentence-transformers), réduction de dimension (UMAP), regroupement par HDBSCAN, noms des thèmes par mots-clés (c-TF-IDF), sans LLM. Le nombre de sujets varie chaque jour ; HDBSCAN ne fixe pas K et met de côté les articles isolés. Les graines aléatoires sont fixées pour que deux runs sur les mêmes données donnent les mêmes thèmes.

Chaque run est tracé, évalué et versionné (TD 5 et 6) ; l'outil de suivi reste à choisir (section 12).

## 8. Choix technologiques et alternatives écartées

| Besoin | Choix | Alternatives écartées | Pourquoi pas elles |
|---|---|---|---|
| Lire la presse | Flux RSS (httpx + feedparser) | API d'agrégateurs (NewsAPI…) ; scraping HTML | API : quotas gratuits faibles, dépendance à un tiers, PQR mal couverte. Scraping : interdit par le bornage (texte intégral) et fragile. |
| Orchestration | Prefect | cron ; Dagster ; Airflow | cron : ni reprise, ni historique, une panne passe inaperçue. Dagster : plus riche pour les données mais plus long à apprendre ; Prefect fait aussi les reprises et les notifications. Airflow : trop lourd pour notre volume. |
| Stockage brut | Fichiers Parquet | JSON (un fichier par article) ; PostgreSQL | JSON : des milliers de petits fichiers, lents à relire et non typés. PostgreSQL : lourd pour des milliers d'items relus à chaque collecte. Parquet est typé, compressé et partitionnable. |
| Stockage propre | PostgreSQL | Fichiers ; SQLite | Fichiers : il faudrait tout rouvrir pour chercher. SQLite : un seul écrivain à la fois, pas d'accès réseau pour les autres services. |
| Environnement | Docker + docker-compose | Installation locale ; machine virtuelle | Local : « ça marche sur mon poste ». VM : plus lourde et moins portable. |
| Thèmes | BERTopic | TF-IDF + K-means ; LDA | K-means : impose de fixer le nombre de thèmes, alors qu'il varie chaque jour. LDA : faible sur des textes courts (titre + extrait). |
| Métriques et tableaux de bord | Prometheus + Grafana | Zabbix ; stack ELK | Zabbix : orienté supervision de serveurs, moins adapté aux métriques métier. ELK : très gourmand en mémoire, pensé pour les journaux. |
| Alertes fines | Alertmanager | Alertes codées à la main ; Grafana Alerting seul | À la main : ni regroupement, ni répétition, ni routage. Grafana seul : moins adapté à la règle « alerte toujours active » du dead man's switch. |
| Détection d'absence (dead man's switch) | Healthchecks.io (offre gratuite) | Uptime Kuma ; Datadog | Uptime Kuma : open source mais devrait tourner sur une autre machine que la nôtre. Datadog : payant. |
| Canal d'alerte | Discord (webhook, simple appel HTTP) | E-mail ; WhatsApp | E-mail : configuration SMTP pénible, écarté sur conseil de l'enseignant. WhatsApp : API officielle de Meta (compte vérifié, souvent payante), contraire au budget zéro. Telegram (bot gratuit) est gardé en réserve. |

## 9. Supervision et résilience

### 9.1 Le bulletin du matin (infos métier)

Chaque matin, après la publication, le pipeline envoie un bulletin sur Discord : heure de publication, articles collectés par source, articles conservés après nettoyage, nombre de thèmes, sources en échec ou vides, taux de chevauchement. Ces chiffres sont aussi exposés en métriques Prometheus pour être suivis dans Grafana.

Alertes sur les chiffres (le pipeline tourne mais quelque chose ne va pas) :
- une source à 0 article sur 24 h ;
- une collecte sans chevauchement (articles possiblement perdus) ;
- un total collecté en baisse de plus de 50 % par rapport à la veille ;
- une édition publiée après 7 h, ou contenant un article de plus de 24 h.

Alertes sur les pannes : une étape Prefect qui échoue après ses reprises envoie un message Discord (hook `on_failure`).

### 9.2 Le watchdog

Processus de contrôle indépendant de Prefect (tâche planifiée dans un conteneur dédié). À heures fixes, il vérifie sans passer par Prefect qu'un run du jour s'est terminé, que l'édition existe et qu'elle est fraîche, et que chaque source a produit au moins un article. En cas d'écart, il alerte. Si l'édition manque à l'heure limite, il relance le pipeline par son point d'entrée Python. Chaque relance est tracée dans le journal de bord.

### 9.3 Et si tout tombe en même temps ?

Prefect, le watchdog et la supervision tournent sur la même machine : si elle s'arrête, ils s'arrêtent tous ensemble et aucune alerte interne ne part. Healthchecks.io est volontairement hors de notre machine et sert de **dead man's switch** : c'est l'absence de signal qui déclenche l'alerte. Il reçoit deux signaux :
- le pipeline, au début et à la fin du run quotidien ;
- la supervision elle-même, toutes les 15 minutes (règle Alertmanager toujours active), pour prouver qu'elle est vivante.

Si un signal manque, Healthchecks.io prévient l'équipe **directement sur Discord**, sans passer par notre Alertmanager, qui pourrait être tombé avec le reste.

| Ce qui tombe | Qui prévient |
|---|---|
| Prefect seul | Le watchdog (et il relance), puis Healthchecks.io |
| La supervision seule | Healthchecks.io (signal de la supervision absent) |
| Toute la machine | Healthchecks.io (aucun signal reçu) |
| Discord | Le bulletin du matin n'arrive pas : l'équipe le remarque ; Healthchecks.io peut notifier Telegram en secours |
| Healthchecks.io | Le bulletin du matin et Grafana continuent ; l'absence de signal y est visible |

### 9.4 Calendrier d'une journée

| Heure | Événement |
|---|---|
| En continu | Collecte des flux : toutes les heures, Ouest-France toutes les 10 minutes |
| 6 h 00 | Prefect lance le run de l'édition (dernière collecte, nettoyage, thèmes, édition) ; signal de début à Healthchecks.io |
| 6 h 30 | Contrôle du watchdog : le run est-il terminé ? |
| 6 h 45 | Heure limite : si l'édition manque, relance directe par le watchdog |
| 7 h 00 | Publication de l'édition ; signal de fin à Healthchecks.io |
| 7 h 05 | Bulletin du matin sur Discord ; second contrôle du watchdog |
| 7 h 15 | Healthchecks.io alerte sur Discord si le signal de fin n'est pas arrivé |

## 10. Infrastructure en code

Tout ce qui tourne est décrit en code, jamais cliqué : environnement de dev en docker-compose (TD 2), ordonnancement (TD 3), déploiement (TD 7), tableaux de bord et alertes (TD 8). Le TD 9 reconstruit l'ensemble de zéro à partir du dépôt. La CI (GitHub Actions) teste le code à chaque commit, construit les images Docker et les pousse sur GitHub. L'outil de déploiement sur l'infrastructure fournie (Ansible pour une machine virtuelle, manifestes Kubernetes pour un cluster, OpenTofu si l'hébergeur a une API) sera choisi quand elle sera connue.

## 11. Risques

| Risque | Impact | Parade |
|---|---|---|
| Flux RSS indisponible, bloqué ou modifié (cas réel : La Voix du Nord) | Source vide | Reprises, alerte « source à 0 », source de remplacement |
| Flux qui se renouvelle trop vite (cas réel : Ouest-France, 10 articles en 24 min) | Articles perdus entre deux collectes | Fréquence par source, contrôle de chevauchement avec alerte |
| Conditions qui se durcissent (le robots.txt du Télégramme a été révisé le 15/10/2026) | Source à retirer | Revérification des robots.txt à chaque TD, consignée dans `sources.csv` |
| Sources restrictives (Le Monde, Le Figaro, Libération, Ouest-France, Le Télégramme) | Usage contestable hors projet de cours | Validation de l'enseignant, gazette non publiée, robot identifié honnêtement (User-Agent « LaGazette-Efrei »), lecture du seul flux, jamais des pages d'articles |
| Données personnelles dans les flux (`author`, `dc:creator`) | Non-respect du bornage | Champs retirés avant tout stockage |
| Texte intégral dans `content:encoded` | Non-respect du bornage | Champ retiré avant tout stockage |
| Panne de Prefect | Pas de run | Watchdog indépendant et point d'entrée Python sans Prefect |
| Machine éteinte à l'heure du run | Pas d'édition, pas d'alerte interne | Healthchecks.io hors de notre infrastructure, alerte directe sur Discord |
| Thèmes instables d'un jour à l'autre | Édition peu lisible | Graines fixées, évaluation et versionnement des runs |

## 12. Décisions ouvertes

| Sujet | À trancher avant |
|---|---|
| Validation par l'enseignant du Figaro, de Libération et du Télégramme | TD 3 |
| Quasi-doublons : fusion au nettoyage ou regroupement par les thèmes | TD 4 |
| Outil de suivi et de versionnement des runs de thèmes (MLflow à comparer à deux alternatives) | TD 5 |
| Outil de déploiement sur l'infrastructure fournie | TD 7 |

## 13. Rôles

| Membre | Rôle |
|---|---|
| Mélissa, Salma | Données : collecte, stockage, sources (blocs 1 à 3) |
| Jason, Amelia | Exploitation : thèmes, supervision, infrastructure en code (blocs 4 à 6) |

Un·e responsable d'exploitation est désigné·e chaque semaine d'intersession. Il ou elle lit le bulletin du matin et tient le journal de bord.

## 14. Planning

| TD | Contenu | Compétences |
|---|---|---|
| 1 | Cadrage, sources, schéma (ce document) | C7.1 |
| 2 | Socle : dépôt, conteneurs (dont Prefect), première CI | C7.2, C8.2 |
| 3 | Collecte (script lancé à la main, puis intégré à Prefect) et stockage brut | C7.3, C7.1 |
| 4 | Nettoyage, qualité, stockage propre | C7.3 |
| 5 | Thèmes (MLOps 1) | C7.4 |
| 6 | Évaluation, versionnement, déploiement du modèle (MLOps 2) | C7.4, C7.2 |
| 7 | Livraison de l'édition de 7 h, début du journal de bord | C7.3, C7.2, C7.1 |
| 8 | Surveillance et administration | C8.1 |
| 9 | Infrastructure en code, reconstruction de zéro | C8.2 |
| 10 | Consolidation et soutenance | C7.1 à C8.2 |
