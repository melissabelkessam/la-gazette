# Stratégie CI/CD

1. **Outil : GitHub Actions** (fichier `.github/workflows/ci.yml`). Alternatives écartées : GitLab CI (imposerait de quitter GitHub) et Jenkins (un serveur de plus à installer et maintenir).
2. **Branches :** `main` est toujours déployable. Une branche par sujet (`feat/`, `fix/`, `docs/`, `infra/`), fusionnée par pull request après une revue (règles dans `CONTRIBUTING.md`).
3. **Déclencheurs :** chaque pull request vers `main` et chaque push sur `main`.
4. **Étape 1, lint :** `ruff check .` (erreurs, imports inutiles ou mal triés).
5. **Étape 2, tests :** `pytest`, sur des fixtures inventées, sans réseau. Les tests vérifient aussi le bornage : pas d'auteur, pas de texte intégral, pas d'image, dates en UTC, liens sans `utm`.
6. **Étape 3, build :** construction de l'image Docker multi-étapes (image finale petite, utilisateur non root). Elle ne s'exécute que si le lint et les tests sont verts.
7. **Étape 4, push :** uniquement sur `main`, l'image est publiée sur `ghcr.io` avec un tag `AAAAMMJJHHMMSS-sha` (date UTC + 7 premiers caractères du commit), qui dit d'où elle vient, et le tag `latest`.
8. **Garde-fou :** `main` est protégée. Une CI rouge ou une PR non relue bloque la fusion ; personne ne pousse directement sur `main`.
9. **Même chose en local :** `bin/test` lance le même lint et les mêmes tests, dans le même environnement Linux que la CI.
10. **Hors périmètre pour l'instant :** pas de déploiement automatique (TD 7), pas de matrice de versions, pas de cache avancé.
