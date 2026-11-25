# Fiche modèle — Regroupement en thèmes de La gazette

_Projet M2Ops · M2 Data Engineering & IA · 2026-2027_
_Dernière mise à jour : 25 novembre 2026 · Mainteneurs : Mélissa, Salma, Jason, Amelia_

## Ce que fait le modèle
À partir des articles propres des dernières 24 h (titre + extrait), il regroupe les articles
qui parlent du même sujet et nomme chaque groupe. Il répond à : « de quoi parle la presse
aujourd'hui ? ». Ce n'est pas un classifieur : il n'y a pas de catégories fixes, les thèmes
émergent des articles du jour.

## Données
- **Entrée** : table `articles_propres` (couche Silver, TD 4), fenêtre glissante de 24 h.
- **Texte vectorisé** : titre + extrait court (jamais l'article intégral — bornage TD 1).
- **Pas de données personnelles** : métadonnées de presse uniquement.

## Chaîne
Embeddings (`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`, CPU, multilingue,
mis en cache) → UMAP (réduction) → HDBSCAN (regroupement, nombre de thèmes libre, bruit à
part) → c-TF-IDF (mots-clés = nom du thème). Paramètres dans `config/clustering.yaml`.

## Métriques suivies
- **nb_themes**, **taille médiane**, **taille max**
- **part_bruit** : part d'articles non rattachés (bruit HDBSCAN)
- **silhouette** (cosinus, hors bruit) : cohésion des groupes

Tracées à chaque run dans MLflow et la table `runs_themes`.

## Évaluation et seuils
`config/evaluation.yaml`. Un run est **recalé** (thèmes non publiés) s'il franchit un
garde-fou dur (`nb_themes_min`, `part_bruit_max`, `theme_geant_max`, `silhouette_min`).
Une **dérive** (dégradation sur 2 runs de suite) donne le verdict **revue**. Relecture
humaine d'un échantillon de 10 articles (`gazette.evaluation --relire`).

## Versions et cycle de vie
Registre `versions_modele` (`gazette.registre_modele`). La version **production** fait foi ;
le pipeline lit ses paramètres au démarrage. Promotion et retour arrière sont des actions
tracées (voir `docs/mlops.md` §9).
**Qui décide d'une promotion** : l'équipe, après lecture des métriques et de la relecture —
pas un `git push` à l'aveugle.

## Limites connues
- Sans vérité terrain : les métriques sont internes, pas une « justesse » absolue.
- Fenêtre glissante de 24 h : les thèmes changent d'une heure à l'autre ; le numéro d'un
  thème n'a pas de sens d'un run à l'autre (comparer les noms et les articles).
- `min_cluster_size` bas → beaucoup de petits thèmes (réglage en cours).
- Une dépêche reprise par plusieurs journaux pèse plus lourd (voulu : sujet traité partout).
- Pas de recherche d'hyperparamètres automatique, pas d'A/B (hors périmètre TD 6).