# Contribuer à La gazette

## La règle d'or

**`main` est toujours déployable.** Personne ne pousse directement sur `main` : tout passe par une pull request (PR) avec une CI verte.

## Le circuit d'une modification

1. Partir de `main` à jour :
   ```bash
   git checkout main && git pull
   ```
2. Créer une branche pour **un seul sujet** :
   ```bash
   git checkout -b feat/collecte-ouest-france
   ```
3. Avant chaque commit, vérifier en local :
   ```bash
   bin/test        # Windows : .\bin\test.ps1
   ```
4. Pousser la branche et ouvrir une PR vers `main` :
   ```bash
   git push -u origin feat/collecte-ouest-france
   ```
5. La CI se lance sur la PR. **Rouge = on corrige**, la fusion est bloquée.
6. **Une autre personne relit** la PR (même rapidement) et l'approuve.
7. La personne qui a ouvert la PR fusionne (**Squash and merge**), puis supprime la branche.

## Nommage des branches

| Préfixe | Pour | Exemple |
|---|---|---|
| `feat/` | Une nouvelle fonctionnalité | `feat/collecte-ouest-france` |
| `fix/` | Une correction | `fix/dates-gmt` |
| `docs/` | De la documentation | `docs/runbook` |
| `infra/` | Docker, CI, supervision, déploiement | `infra/prometheus` |
| `chore/` | Rangement, dépendances | `chore/maj-httpx` |

## Format des commits

Format : `type(sujet): description courte`, en français, au présent.

```
feat(collecte): lecture du flux d'Ouest-France
fix(collecte): conversion des dates GMT en UTC
docs(cadrage): ajout des validations de l'enseignant
infra(ci): push de l'image sur ghcr.io
test(collecte): cas d'un article sans extrait
```

Types : `feat`, `fix`, `docs`, `test`, `infra`, `chore`.

## Qui fait quoi

| Domaine | Responsables | Relit par défaut |
|---|---|---|
| Collecte, stockage, sources (blocs 1 à 3) | Mélissa, Salma | Jason ou Amelia |
| Thèmes, supervision, infrastructure (blocs 4 à 6) | Jason, Amelia | Mélissa ou Salma |
| Documentation | Tout le monde | N'importe qui d'autre |

**Qui fusionne :** l'auteur·e de la PR, une fois la CI verte et une approbation obtenue.

## Ce qu'on ne commite jamais

- Des **données collectées** (`data/` est ignoré par Git) : le projet n'est jamais publié.
- Un **vrai contenu de presse** dans les fixtures de test : on invente des articles qui imitent la structure.
- Des **mots de passe ou des jetons** : ils vont dans les variables d'environnement ou les secrets GitHub.
- Le dossier `.venv/`.

## Bornage à respecter dans le code

- On ne garde que **titre, extrait, lien, date et rubrique**.
- On retire **l'auteur** (`author`, `dc:creator`), le **texte intégral** (`content:encoded`) et les **images**.
- Le robot s'identifie honnêtement (`LaGazette-Efrei`) et ne lit que les flux RSS, jamais les pages d'articles.

Toute nouvelle règle de ce type doit avoir **son test**.
