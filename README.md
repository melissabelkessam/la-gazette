# La gazette

Un pipeline qui lit chaque matin la presse régionale et nationale (flux RSS), regroupe les articles par thèmes et livre à 7 h l'édition du jour.
Projet M2Ops · M2 Data Engineering & IA · Efrei · 2026-2027 · Mélissa, Salma, Jason, Amelia.

[![CI](../../actions/workflows/ci.yml/badge.svg)](../../actions/workflows/ci.yml)

## Lancer le projet (deux commandes)

Seul prérequis : **Docker** (avec Docker Compose).

```bash
git clone <url-du-depot> && cd la-gazette
bin/dev
```

Sous Windows PowerShell : `.\bin\dev.ps1` (si Windows bloque le script : `Unblock-File bin\*.ps1`).

`bin/dev` démarre :

| Service | Rôle | Adresse |
|---|---|---|
| `postgres` | Base de données (couches Silver et Gold) | `localhost:5432` |
| `prefect` | Orchestrateur, interface web | http://localhost:4200 |
| `collecte` | Lit le flux de Sud Ouest et écrit les articles en JSON dans `data/brut/` | — |

La ligne `collecte-1 | 20 articles écrits dans data/brut/...` puis `exited with code 0` indique que tout a marché. `Ctrl + C` pour arrêter.

## Tester

```bash
bin/test
```

Sous Windows PowerShell : `.\bin\test.ps1`. Lance le lint (`ruff`) puis les tests (`pytest`) dans un conteneur, exactement comme la CI.

Sans Docker, en local :

```bash
python -m venv .venv && source .venv/bin/activate   # Windows : .venv\Scripts\Activate.ps1
pip install -r requirements-dev.txt -e .
ruff check . && pytest
python -m gazette.collecte --source "Sud Ouest"
```

## Organisation du dépôt

| Chemin | Contenu |
|---|---|
| `src/gazette/` | Code du pipeline (`collecte.py` : lecture d'une source RSS) |
| `tests/` | Tests ; `tests/fixtures/` contient des flux d'exemple **inventés** (aucun contenu de presse dans le dépôt) |
| `sources.csv` | Les 10 sources, leurs conditions d'utilisation et leur fréquence de collecte |
| `docs/` | Cadrage, architecture, stratégie CI/CD |
| `infra/` | Configuration de l'infrastructure (supervision, déploiement) |
| `bin/` | Les commandes `dev` et `test` |
| `data/` | Données collectées, **jamais commitées** (ignorées par Git) |

## Contribuer

Voir [CONTRIBUTING.md](CONTRIBUTING.md) : une branche par sujet, une pull request revue par quelqu'un d'autre, une CI verte avant de fusionner.

## Documentation

- [Cadrage](docs/cadrage.md)
- [Stratégie CI/CD](docs/ci-cd.md)
-[Schéma d'architecture](docs/architecture.jpg)

## Bornage

Seuls le titre, l'extrait, le lien, la date et la rubrique sont conservés : jamais l'article entier, jamais les images, jamais l'auteur. Le robot s'identifie honnêtement (`LaGazette-Efrei`). Projet de cours, jamais publié.
