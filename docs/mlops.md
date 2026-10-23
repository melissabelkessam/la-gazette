# MLOps : les thèmes du jour (TD 5)

Ce document dit quel modèle produit les thèmes, avec quels paramètres, et où lire chaque
run. Il se complète au TD 6 (évaluation, versions, mise en service).

## 1. Ce que fait un run

À chaque passage du flow (toutes les 10 min), la tâche Prefect `themes` vient **après le
nettoyage**. Elle lance un run si le dernier date de plus d'une heure
(`planification.intervalle_min`). Un run :

1. lit les articles de `articles_propres` publiés dans les dernières 24 h ;
2. calcule l'empreinte de l'entrée (SHA-256 des `item_id` et des textes, plus le modèle) ;
3. vectorise titre + extrait, en ne calculant que les articles absents du cache `embeddings` ;
4. regroupe et nomme (BERTopic) ;
5. écrit `themes` et `articles_themes`, et ferme la ligne du run dans `runs_themes` ;
6. envoie tout à MLflow : paramètres, métriques, artefacts.

Sans Prefect : `docker compose exec orchestrateur python -m gazette.themes --forcer`.

## 2. Le modèle et ses paramètres

| Étape | Outil | Réglage (dans `config/clustering.yaml`) |
|---|---|---|
| Vecteurs | `paraphrase-multilingual-MiniLM-L12-v2` (sentence-transformers, 384 dimensions, CPU) | `embeddings.modele`, `embeddings.revision` |
| Réduction | UMAP | `n_neighbors` 15, `n_components` 5, `min_dist` 0, cosinus |
| Regroupement | HDBSCAN | `min_cluster_size` 5, `min_samples` 3 |
| Nommage | c-TF-IDF (BERTopic), mots vides français retirés | 10 mots-clés, nom = les 3 premiers |
| Reproductibilité | graine fixée | `graine` 42 |

Le fichier de paramètres est la seule source de vérité : il est monté en lecture seule dans
le conteneur, recopié dans chaque run MLflow (artefact `config_clustering.yaml`) et son
empreinte est notée (`runs_themes.hash_config`). Changer une valeur ne demande pas de
reconstruire l'image : le prochain run l'utilise, et il est comparable aux précédents.

**Version du modèle.** La version notée est le commit Hugging Face réellement chargé (pas
seulement « main »). Le cache `embeddings` est indexé par (modèle, version) : un changement
de modèle ne mélange jamais deux espaces de vecteurs.

## 3. Ce que chaque run trace

| Demandé par le TD | Où |
|---|---|
| Fenêtre de données : dates, nombre d'articles, hash de l'entrée | `runs_themes` (`fenetre_debut`, `fenetre_fin`, `nb_articles`, `hash_entree`) et tags MLflow |
| Modèle d'embedding et sa version | `runs_themes.modele`, `modele_version` ; tags MLflow |
| Paramètres de regroupement | `runs_themes.parametres` (JSON) ; paramètres MLflow (`regroupement.min_cluster_size`...) |
| Métriques | `runs_themes.metriques` ; métriques MLflow : `nb_themes`, `taille_mediane`, `taille_max`, `part_bruit`, `silhouette`, `vecteurs_en_cache`, `vecteurs_calcules`, `duree_s` |
| Artefacts | MLflow : `themes.json` (noms, mots-clés, tailles), `affectations.json` (article → thème), `config_clustering.yaml` |

`silhouette` est calculée sur les vecteurs, hors bruit, en distance cosinus. Elle vaut `null`
s'il y a moins de deux thèmes.

## 4. Où regarder

**MLflow** : http://localhost:5000, expérience `gazette-themes`. Chaque ligne est un run ; on
peut trier par métrique, comparer deux runs et ouvrir leurs artefacts.

**Quel run a produit les thèmes en base ?** Les thèmes du jour sont ceux du dernier run
réussi, et chaque thème porte son `run_id` :

```bash
docker compose exec postgres psql -U gazette -d gazette -c "SELECT run_id, nom, taille FROM themes_du_jour;"
docker compose exec postgres psql -U gazette -d gazette -c "SELECT run_id, mlflow_run_id, statut, nb_articles, metriques->>'nb_themes' AS themes, metriques->>'part_bruit' AS bruit, fin FROM runs_themes ORDER BY debut DESC LIMIT 10;"
```

`runs_themes.mlflow_run_id` mène au même run dans MLflow.

**Les articles d'un thème :**

```sql
SELECT a.source, a.titre FROM articles_themes x
JOIN articles_propres a USING (item_id)
WHERE x.run_id = '<run_id>' AND x.theme = 0;
```

**Statuts d'un run** : `ok` ; `trop_peu_articles` (moins de `min_articles`, on ne regroupe
pas) ; `echec` (l'erreur est dans `runs_themes.erreur`, la tâche Prefect est rouge) ;
`en_cours`.

## 5. Choix et alternatives écartées

| Besoin | Retenu | Écartés et pourquoi |
|---|---|---|
| Modèle d'embedding | `paraphrase-multilingual-MiniLM-L12-v2` : multilingue, léger, quelques secondes sur CPU pour quelques centaines de titres | `multilingual-e5-small` : qualité proche, mais demande un préfixe « query: » à chaque texte, source d'erreurs. API d'embeddings (OpenAI, Mistral) : clé à gérer, coût, données envoyées à un tiers, contraire au budget zéro |
| Regroupement | BERTopic (UMAP + HDBSCAN + c-TF-IDF), validé au cadrage | K-means : impose le nombre de thèmes, qui change chaque jour. Classification hiérarchique seule : demande un seuil de coupe et ne nomme pas les groupes |
| Nommage | Mots-clés c-TF-IDF | LLM : non demandé, coût et non reproductible. Mots les plus fréquents : ressortent des mots communs à tous les thèmes |
| Suivi des runs | MLflow (serveur dans docker-compose) **et** table `runs_themes` | Table seule : pas d'interface pour comparer les runs ni de stockage d'artefacts. W&B : service en ligne, données hors de chez nous. DVC : versionne fichiers et modèles mais compare moins simplement les métriques d'un run à l'autre |
| Pourquoi les deux | MLflow pour comparer (TD 6) ; `runs_themes` pour relier les thèmes en base à leur run, même si MLflow est en panne | |
| Cache des vecteurs | Table `embeddings` (PostgreSQL, `REAL[]`) | Fichier `.npy` : un fichier de plus à synchroniser avec la base. pgvector : utile pour chercher des voisins, inutile ici |
| Format des paramètres | YAML (`config/clustering.yaml`, demandé par le TD) | TOML : lisible sans dépendance, mais PyYAML est déjà installé avec MLflow. Variables d'environnement : illisibles pour 15 paramètres imbriqués |

## 6. Limites connues (matière du TD 6)

- Les paramètres viennent de la documentation de BERTopic, pas encore de nos données.
  `min_cluster_size` 5 donne beaucoup de petits thèmes ; à régler au TD 6.
- La fenêtre est glissante (24 h avant le run) : les thèmes changent d'une heure à l'autre.
  Le run de l'édition de 7 h sera le run de référence (TD 7).
- Le numéro d'un thème n'a pas de sens d'un run à l'autre : comparer les noms et les articles.
- La même dépêche reprise par plusieurs journaux tire un thème vers le haut : c'est voulu
  (un sujet traité partout est un sujet du jour), à confirmer au TD 6.

## 7. Thèmes du jour relus à la main

Notés pour la séance (TD 5) puis sur deux journées (pour le TD 6) : ce qui est bon, ce qui
est absurde, une hypothèse sur pourquoi.

| Date | run_id | Thèmes | Bon | Absurde | Hypothèse |
|---|---|---|---|---|---|
| _à remplir_ | | | | | |
| _à remplir_ | | | | | |
