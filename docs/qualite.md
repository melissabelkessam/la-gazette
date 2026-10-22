# Qualité des données - règles d'exclusion (TD 4)

Document vivant : il se complète à chaque ajustement (section 7). Les exemples cités sont
de vrais titres tirés de `data/articles_bruts/` (collecte du 22/10/2026) ; aucun n'est
inventé. La section 7 se remplit après trois matins de lecture du rapport.

## 1. Principe

Entre le brut et la gazette, chaque article passe par : normalisation, règles unitaires,
puis comparaison aux articles déjà gardés (doublons). La **première règle qui s'applique
gagne** ; l'article est alors écrit dans `rejets` avec l'identifiant de la règle.
Sinon il va dans `articles_propres`.

- Les règles sont **lisibles et modifiables sans toucher à la logique** : motifs, listes
  de rubriques et seuils sont dans `src/gazette/regles_config.py`. Pas de modèle.
- Les motifs sont écrits sans accents et en minuscules : ils sont comparés à un texte
  normalisé (`normaliser_titre`).
- Ordre d'application : R05, R06, R07, R01, R02, R03, R04, R10, puis R08 et R09.
- Un rejet garde son `item_id` et la règle : on peut toujours retrouver le fichier brut
  et comprendre pourquoi l'article a été écarté.

## 2. Les dix pollueurs

Chiffres du 22/10/2026 : 427 articles traités (8 sources ; Le Télégramme et Les Échos
répondent 403 et ne sont pas collectés), 415 gardés, 12 rejetés.

| # | Pollueur | Règle | Exemple réel (source : titre) | Rejetés |
|---|---|---|---|---|
| 1 | Publi-reportages, contenus partenaires, codes promo | R01_publi | aucun cas trouvé ce jour | 0 |
| 2 | Horoscope, astrologie, voyance | R02_horoscope | aucun cas trouvé ce jour | 0 |
| 3 | Programmes TV | R03_tv | aucun cas trouvé ce jour | 0 |
| 4 | Jeux, concours, loto, mots fléchés | R04_jeux | aucun cas trouvé ce jour | 0 |
| 5 | Titres vides ou quasi vides | R05_titre_vide | aucun cas trouvé ce jour | 0 |
| 6 | Dates dans le futur | R06_date_future | article de test inséré (voir section 5) | 0 |
| 7 | Encodage cassé non réparable | R07_encodage_casse | aucun cas trouvé ce jour | 0 |
| 8 | Doublons exacts (même titre ou même lien) | R08_doublon_exact | Le Figaro : « Pierre Moscovici démissionne de la Cour des comptes européenne » | 1 |
| 9 | Quasi-doublons, titres retouchés ou repris | R09_doublon_approx | Ouest-France : « Réchauffement climatique : 96 % des récifs coralliens sont menacés d'extinction d'ici cinquante ans » | 2 |
| 10 | « DIRECT », « EN DIRECT » | R10_direct_diaporama | La Croix : « DIRECT. Manifestation du 24 octobre : interdiction à Lyon… » | 9 |

Constat honnête : sur nos 8 flux (presse généraliste nationale et régionale), les pollueurs
de type horoscope, programme TV, jeux ou publi-reportage sont absents ou très rares. Les
règles R01 à R05 et R07 existent et sont testées sur des cas inventés
(`tests/test_regles.py`) mais n'ont rien rejeté sur les vraies données. Les trois vrais
pollueurs observés sont les directs (R10) et les doublons (R08, R09).

## 3. Fiches des règles

Pour chaque règle : ce qu'elle écarte, pourquoi, comment, risque de faux positif.
**État de validation** : les motifs de départ viennent de la connaissance générale de la
presse française. R08, R09 et R10 sont confirmés par de vrais rejets (22/10/2026). R01 à
R05 et R07 n'ont encore rien rejeté sur nos flux : ils restent à valider quand des cas
réels apparaîtront (`grep` dans `data/articles_bruts/`), et chaque changement sera noté en
section 7.

### R01_publi
- **Écarte** : publi-reportages, « contenu partenaire/sponsorisé », codes promo, bons plans.
- **Pourquoi** : publicité déguisée en article ; ne doit pas figurer dans une gazette.
- **Comment** : motif sur titre, extrait et rubrique ; rubriques « publi reportage »,
  « contenu partenaire ».
- **Faux positifs** : un article qui parle d'un « partenaire » sans être sponsorisé
  (testé : conservé).
- **Exemple réel** : aucun cas sur les vraies données au 22/10/2026 (427 articles). Règle testée sur des cas inventés.

### R02_horoscope
- **Écarte** : horoscope, astrologie, voyance, tarot.
- **Pourquoi** : contenu récurrent sans valeur d'actualité.
- **Comment** : motif sur titre et rubrique ; rubriques « horoscope », « astro ».
- **Exemple réel** : aucun cas sur les vraies données au 22/10/2026 (427 articles). Règle testée sur des cas inventés.

### R03_tv
- **Écarte** : programmes TV, « que regarder ce soir », « sur quelle chaîne ».
- **Pourquoi** : service au public, pas de l'information.
- **Faux positifs** : un article sur la télévision publique (testé : conservé).
- **Exemple réel** : aucun cas sur les vraies données au 22/10/2026 (427 articles). Règle testée sur des cas inventés.

### R04_jeux
- **Écarte** : jeux-concours, mots fléchés/croisés, sudoku, quiz, loto, Euromillions, Keno.
- **Pourquoi** : pas d'information.
- **Faux positifs** : le mot « concours » seul n'est PAS un motif (concours de la fonction
  publique : conservé).
- **Exemple réel** : aucun cas sur les vraies données au 22/10/2026 (427 articles). Règle testée sur des cas inventés.

### R05_titre_vide
- **Écarte** : titre vide ou de moins de 3 lettres/chiffres.
- **Pourquoi** : un titre est obligatoire dans l'édition.
- **Exemple réel** : aucun cas sur les vraies données au 22/10/2026 (427 articles). Règle testée sur des cas inventés.

### R06_date_future
- **Écarte** : `publie_le` supérieur à maintenant + 3 h.
- **Pourquoi** : date fausse ; certains flux étiquettent « GMT » une heure locale, d'où la
  tolérance de 3 h (`TOLERANCE_DATE_FUTURE`).
- **Cas limite** : une date absente est remplacée par l'heure de collecte
  (`date_estimee = vrai`) et n'est jamais « future ».
- **Exemple réel** : aucun article rejeté sur les vraies données. Le contrôle `date_future` (section 5) a détecté une ligne de test à date future et déclenché l'alerte.

### R07_encodage_casse
- **Écarte** : titre qui contient encore des caractères illisibles (« Ã© », « � »)
  après tentative de réparation.
- **Pourquoi** : titre illisible dans l'édition. La réparation (« CafÃ© » -> « Café »)
  est faite avant la règle : un titre réparable n'est pas rejeté.
- **Exemple réel** : aucun cas sur les vraies données au 22/10/2026 (427 articles). Règle testée sur des cas inventés.

### R08_doublon_exact
- **Écarte** : même titre normalisé, ou même lien, qu'un article déjà gardé (48 h).
- **Pourquoi** : le même article relu ou repris à l'identique.
- **Garde** : le plus ancien ; `rejets.doublon_de` pointe vers lui.
- **Cas limite** : un titre de moins de 3 mots significatifs n'est pas comparé
  (« Éditorial »).
- **Exemple réel (22/10/2026)** : Le Figaro, « Pierre Moscovici démissionne de la Cour des
  comptes européenne », rejeté car même titre qu'un article déjà gardé (`detail` = « même
  titre »).

### R09_doublon_approx
- **Écarte** : titre dont la similarité de Jaccard (mots de 3 lettres et plus) avec un
  article gardé atteint **0,8** (`SEUIL_JACCARD`).
- **Pourquoi** : même dépêche d'agence reprise par plusieurs journaux, titres retouchés.
- **Seuil retenu : 0,8.** Paires réelles observées le 22/10/2026 (toutes de vrais
  quasi-doublons, aucun faux positif) :

  | Jaccard | Article rejeté | Article conservé |
  |---|---|---|
  | 0,85 | « Le virus Shamonda détecté pour la première fois chez un humain, un patient immunodéprimé mort en France » | « Le virus Shamonda détecté pour la première fois chez un humain, un patient est mort en France » |
  | 0,82 | « Réchauffement climatique : 96 % des récifs coralliens sont menacés d'extinction d'ici cinquante ans » (Ouest-France) | « Réchauffement climatique : 96 % des récifs coralliens menacés d'extinction d'ici 50 ans » |

  Ces deux paires sont juste au-dessus du seuil : à 0,9 elles ne seraient pas détectées.
  Limite connue : on n'a pas encore observé de paire de faux positifs sous le seuil ;
  à vérifier sur plus de données avant de monter ou descendre le seuil.
- **Décision à confirmer** : les dépêches d'agence reprises par plusieurs titres sont
  rejetées ici (on garde la plus ancienne). Les reprises ne sont pas perdues :
  `rejets.doublon_de` pointe vers l'article conservé, donc le nombre de journaux qui
  reprennent un sujet reste calculable (utile aux thèmes, TD 5).
- **Exemples réels** : les deux paires du tableau ci-dessus (22/10/2026).

### R10_direct_diaporama
- **Écarte** : titres commençant par « DIRECT », « EN DIRECT », « LIVE », « DIAPORAMA ».
- **Pourquoi** : le titre change au fil de la journée sans que le lien change ; ce n'est
  pas un article stable.
- **Exemples réels (22/10/2026)** : La Croix, « DIRECT. Manifestation du 24 octobre :
  interdiction à Lyon… » ; Le Monde, « EN DIRECT, manifestations du 17 octobre : la
  justice suspend l'interdiction de la manifestation… ». 9 rejets sur 427 articles.
- **Contrepartie** : ces directs portent sur de vrais sujets d'actualité. On les perd ;
  le sujet reste couvert par les autres articles. Piste : en garder un par sujet.

## 4. Normalisation

Une fonction pure par transformation (`src/gazette/normalisation.py`), un test chacune :
HTML retiré (balises, commentaires, scripts), entités décodées, espaces et caractères
invisibles nettoyés, encodage réparé, dates converties en UTC, extrait borné à 300
caractères au mot près, paramètres de suivi (`utm_*`, `fbclid`...) retirés du lien.
Le champ `payload` du brut n'est jamais recopié (il peut contenir des auteurs).

## 5. Contrôles de qualité

Ils vérifient des **faits sur les vraies données**, après chaque passage (pas de tests de
code : ceux-là sont dans la CI). Résultats écrits dans `controles_qualite`.

| Contrôle | Fait vérifié | Seuil | Alerte |
|---|---|---|---|
| `date_future` | aucune date future dans `articles_propres` | 0 (tolérance 3 h) | oui |
| `titre_vide` | aucun titre vide dans `articles_propres` | 0 | oui |
| `taux_rejet_source` | part rejetée par source sur la journée UTC | 80 % (sources d'au moins 10 articles) | oui |
| `fraicheur_source` | âge du dernier article gardé par source | 24 h | non (signalement) |

**Alerte** : message Discord (webhook lu dans `DISCORD_WEBHOOK_URL`). Anti-spam : un même
contrôle en échec n'alerte qu'une fois par 6 h ; si l'envoi échoue, il est retenté au
passage suivant.

**Essai réel de l'alerte (22/10/2026).** Un article de test avec une date à +2 jours a été
inséré dans `articles_propres`. Le contrôle `date_future` est passé en échec
(`echecs: ["date_future:global"]`), le message « ALERTE qualité - La gazette » est arrivé sur
le salon Discord de l'équipe (HTTP 204, `alerte_envoyee: true`). Un second lancement n'a
pas renvoyé de message (anti-spam de 6 h). Après suppression de la ligne de test, le
contrôle est revenu à `echecs: []`.

**Choix : assertions maison en SQL plutôt qu'un outil dédié.**
- *Great Expectations* : très complet, mais lourd (dépendance, configuration, génération
  de documents) pour quatre faits simples ; alourdirait la construction de l'image.
- *Soda* : plus léger, mais encore une dépendance et un langage de plus à apprendre.
- *Assertions maison* : quatre requêtes SQL lisibles, aucune dépendance, résultats déjà
  dans notre base, testables avec une base jetable. Limite : pas de bibliothèque de
  contrôles toute prête ; à réévaluer si le nombre de contrôles grandit.

## 6. Rapport de qualité

`rapports/qualite-AAAA-MM-JJ.md`, recalculé à chaque passage pour la journée UTC : entrés,
gardés, rejetés ; rejets par règle ; par source ; les cinq rejets les plus fréquents avec
deux titres d'exemple ; les règles qui écartent au moins 80 % d'une source (signal
« règle trop gourmande »).

## 7. Ajustements après lecture du rapport

À remplir après trois matins de lecture (au moins un ajustement attendu).

| Date | Règle | Ce qui a été constaté | Changement | Pourquoi |
|---|---|---|---|---|
| À COMPLÉTER | | | | |

## 8. Questions ouvertes

- Dépêches d'agence : rejet par R09 (actuel) ou conservation pour les thèmes ?
- Seuil de Jaccard (0,8) : confirmé sur 2 paires réelles (0,82 et 0,85), à tester sur plus
  de données, notamment du côté des faux positifs.
- R10 : faut-il garder un direct par sujet plutôt que les rejeter tous ?
- Date absente : remplacement par l'heure de collecte (actuel) ou rejet ?
