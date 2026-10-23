# À AJOUTER à docs/donnees.md (contrat de données, TD 4)

## Tables ajoutées

### articles_propres (couche Silver) - migration 003

| Colonne | Type | Origine dans le brut | Remarque |
|---|---|---|---|
| item_id | TEXT, clé primaire | `id` (= nom du fichier JSON) | unique : insertion rejouable |
| source | TEXT | `source` | |
| titre | TEXT | `titre` | HTML, entités, encodage nettoyés |
| extrait | TEXT | `resume` | borné à 300 caractères |
| lien | TEXT | `lien` | paramètres de suivi retirés |
| rubrique | TEXT | `rubrique` | |
| publie_le | TIMESTAMPTZ | `publie_le` | converti en UTC |
| date_estimee | BOOLEAN | calculé | vrai si la date a été remplacée par l'heure de collecte |
| collecte_le | TIMESTAMPTZ | `recupere_le` | |
| nettoye_le | TIMESTAMPTZ | calculé | défaut now() |

### rejets - migration 004

`item_id` (clé), `source`, `titre`, `lien`, `regle` (identifiant R01...R10), `detail`
(motif ou valeur qui a déclenché), `doublon_de` (item_id conservé, pour R08/R09),
`rejete_le`.

### controles_qualite - migration 005

`id`, `horodatage`, `nom`, `portee` (global ou nom de source), `valeur`, `seuil`, `ok`,
`alerte_envoyee`, `detail`. Le TD 8 lira cette table pour les métriques.

## Fraîcheur

Une collecte et un nettoyage toutes les 10 minutes. Une édition ne contient que des
articles de moins de 24 h (objectif de service, vérifié au TD 7 et suivi au TD 8).

## Rétention (proposition à valider)

| Donnée | Durée | Ensuite |
|---|---|---|
| Brut (`data/articles_bruts/`) | 90 jours | supprimé |
| `articles_propres`, `rejets` | 90 jours | supprimés (le rapport du jour reste archivé) |
| `controles_qualite` | 90 jours | supprimés |
| Rapports de qualité (`rapports/`) | conservés | |
| Éditions publiées | 1 mois en ligne | archivage froid (TD 7) |

La suppression effective est à implémenter ; pour l'instant la durée est une règle écrite.

## Ce qu'on ne stocke pas

Aucun article complet, aucune image, aucun commentaire. Aucune donnée personnelle :
jamais `author` ni `dc:creator`. Le champ `payload` du brut n'est jamais recopié dans
`articles_propres` ni `rejets`. Seuls titre, extrait court, lien, date, rubrique et source
sont conservés.

## Traçabilité

D'un article propre ou rejeté, `item_id` retrouve le fichier brut :

```bash
find data/articles_bruts -name '<item_id>.json'
```

et `rejets.regle` donne la raison du rejet, `rejets.doublon_de` l'article conservé.
Exemple :

```sql
SELECT item_id, source, titre, lien FROM articles_propres WHERE item_id = '<item_id>';
SELECT regle, detail, doublon_de FROM rejets WHERE item_id = '<item_id>';
```
## Tables ajoutées au TD 5 (couche Gold) - migration 006

### embeddings

Cache des vecteurs. Clé : (`item_id`, `modele`, `modele_version`) : un article n'est vectorisé
qu'une fois par version de modèle. `vecteur` (REAL[], 384 valeurs), `cree_le`. Supprimé avec
l'article propre (`ON DELETE CASCADE`).

### runs_themes

Un run de regroupement = une ligne : `run_id` (clé, partagé avec MLflow), `mlflow_run_id`,
`debut`, `fin`, `statut` (`en_cours`, `ok`, `trop_peu_articles`, `echec`), `fenetre_debut`,
`fenetre_fin`, `nb_articles`, `hash_entree` (SHA-256 des articles en entrée), `modele`,
`modele_version`, `hash_config`, `parametres` (JSON du fichier `config/clustering.yaml`),
`metriques` (JSON), `erreur`.

### themes

(`run_id`, `theme`) clé ; `nom` (3 premiers mots-clés), `mots_cles` (TEXT[]), `taille`.

### articles_themes

(`run_id`, `item_id`) clé ; `theme`. Les articles classés en bruit par HDBSCAN ne sont pas
rattachés.

### Vue themes_du_jour

Les thèmes du dernier run `ok`, triés par taille, avec `calcule_le`.

Aucune nouvelle donnée de presse n'est stockée : les thèmes sont calculés à partir des
champs déjà présents dans `articles_propres`. Les artefacts MLflow (`affectations.json`)
contiennent des `item_id` et des sources, pas de titres.
