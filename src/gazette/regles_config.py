"""Configuration lisible des règles d'exclusion (TD 4).

Tout ce qui se règle (motifs, listes de rubriques, seuils) est ici, pas dans la
logique. Les motifs sont écrits SANS accents, en minuscules, sans ponctuation :
ils sont comparés à un texte normalisé (voir ``normaliser_titre``).

ATTENTION : ces motifs sont un point de départ. Il faut les valider et les ajuster
sur les vrais articles de ``data/articles_bruts/`` (docs/qualite.md, section 3).
La première règle qui s'applique gagne ; l'ordre est ``ORDRE_REGLES``.
"""

from __future__ import annotations

import re
from datetime import timedelta

# --- Seuils ---------------------------------------------------------------
MIN_LONGUEUR_TITRE = 3  # lettres/chiffres minimum (R05)
TOLERANCE_DATE_FUTURE = timedelta(hours=3)  # fuseaux mal étiquetés (R06)
SEUIL_JACCARD = 0.8  # similarité minimale de deux titres (R09)
MIN_MOTS_DOUBLON = 3  # en dessous, un titre est trop court pour être comparé
FENETRE_DOUBLONS_H = 48  # on compare aux articles gardés des dernières 48 h

# Règles évaluées dans cet ordre. R08 et R09 (doublons) viennent en dernier.
ORDRE_REGLES = (
    "R05_titre_vide",
    "R06_date_future",
    "R07_encodage_casse",
    "R01_publi",
    "R02_horoscope",
    "R03_tv",
    "R04_jeux",
    "R10_direct_diaporama",
    "R08_doublon_exact",
    "R09_doublon_approx",
)

# --- Règles à motif -------------------------------------------------------
# "champs" : champs de l'article propre où chercher le motif.
# "rubriques" : rubriques entières (normalisées) qui suffisent à écarter l'article.
REGLES_MOTIF = (
    {
        "id": "R01_publi",
        "champs": ("titre", "extrait", "rubrique"),
        "motif": re.compile(
            r"\b(contenus? (partenaires?|sponsorises?|de marque)"
            r"|publi ?reportages?|sponsorise par|avec nos partenaires"
            r"|codes? promo|bons? plans?)\b"
        ),
        "rubriques": frozenset(
            {"publi reportage", "contenu partenaire", "contenus partenaires"}
        ),
        "pourquoi": "Publicité ou contenu commercial déguisé en article.",
    },
    {
        "id": "R02_horoscope",
        "champs": ("titre", "rubrique"),
        "motif": re.compile(r"\b(horoscope|astrologie|astrologique|voyance|tarot)\b"),
        "rubriques": frozenset({"horoscope", "astro", "astrologie"}),
        "pourquoi": "Contenu récurrent sans valeur d'actualité.",
    },
    {
        "id": "R03_tv",
        "champs": ("titre", "rubrique"),
        "motif": re.compile(
            r"\b(programmes? (tv|tele)|que regarder (ce soir )?a la tele"
            r"|ce soir a la tele|a la tele ce soir|tv ce soir"
            r"|sur quelle chaine)\b"
        ),
        "rubriques": frozenset({"programme tv", "programmes tv"}),
        "pourquoi": "Programme de télévision : service, pas information.",
    },
    {
        "id": "R04_jeux",
        "champs": ("titre", "rubrique"),
        "motif": re.compile(
            r"\b(jeux? concours|tentez (de )?gagner|mots? (fleches|croises|meles)"
            r"|sudoku|quiz|loto|euromillions|keno)\b"
        ),
        "rubriques": frozenset({"jeux", "jeux concours", "mots croises", "sudoku"}),
        "pourquoi": "Jeux, concours et tirages : pas d'information.",
    },
    {
        "id": "R10_direct_diaporama",
        "champs": ("titre",),
        "motif": re.compile(r"^(en )?(direct|live|diaporama)\b"),
        "rubriques": frozenset(),
        "pourquoi": "Direct ou diaporama : le titre change, le contenu n'est pas un article.",
    },
)

DESCRIPTIONS = {
    "R05_titre_vide": "Titre vide ou réduit à moins de 3 lettres ou chiffres.",
    "R06_date_future": "Date de publication postérieure à maintenant + tolérance.",
    "R07_encodage_casse": "Titre avec caractères illisibles après réparation.",
    "R08_doublon_exact": "Même titre normalisé ou même lien qu'un article déjà gardé.",
    "R09_doublon_approx": "Titre très proche (Jaccard) d'un article déjà gardé.",
    **{r["id"]: r["pourquoi"] for r in REGLES_MOTIF},
}
