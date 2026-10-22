"""Tests du nettoyage, du rapport et des contrôles (TD 4).

Les tests sans base tournent partout. Ceux marqués ``base`` demandent une VRAIE base
PostgreSQL jetable (elle est vidée !) : ``GAZETTE_TEST_DATABASE_URL``. Ils sont
ignorés sinon, et tournent dans la CI comme ceux du TD 3. Données inventées.
"""

import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from gazette.alerte import envoyer_alerte  # noqa: F401  (vérifie l'import)
from gazette.controles import executer_controles
from gazette.doublons import IndexDoublons
from gazette.nettoyage import dossier_brut, lire_bruts, nettoyer, traiter
from gazette.rapport_qualite import ecrire_rapport

MAINTENANT = datetime(2026, 10, 22, 12, 0, tzinfo=timezone.utc)
MIGRATIONS = Path(__file__).resolve().parents[1] / "src" / "gazette" / "migrations"
URL_TEST = os.environ.get("GAZETTE_TEST_DATABASE_URL")
base = pytest.mark.skipif(not URL_TEST, reason="GAZETTE_TEST_DATABASE_URL absente")


def brut(item_id, titre, source="Journal Test", **champs):
    donnees = {
        "id": item_id,
        "source": source,
        "lien": f"https://exemple.test/{item_id}",
        "titre": titre,
        "resume": "Un résumé inventé.",
        "publie_le": (MAINTENANT - timedelta(hours=2)).isoformat(),
        "recupere_le": (MAINTENANT - timedelta(hours=1)).isoformat(),
        "rubrique": "Société",
        "payload": {"author": "Personne Inventée"},
    }
    donnees.update(champs)
    return donnees


def ecrire_bruts(dossier, articles):
    for article in articles:
        sous_dossier = Path(dossier) / article["source"].lower().replace(" ", "-")
        sous_dossier.mkdir(parents=True, exist_ok=True)
        (sous_dossier / f"{article['id']}.json").write_text(
            json.dumps(article, ensure_ascii=False), encoding="utf-8"
        )


LOT = [
    brut("a1", "Le conseil municipal vote le budget de la ville pour l'an prochain"),
    brut("a2", "Horoscope du jeudi : une journée chargée"),
    brut("a3", "Programme TV : que regarder ce soir à la télé"),
    brut(
        "a4",
        "Le conseil municipal vote le budget de la ville pour l'an prochain",
        source="Autre Journal",
    ),
    brut("a5", "", titre_vide=True),
    brut("a6", "Une tempête annoncée sur la côte atlantique ce week-end",
         publie_le=(MAINTENANT + timedelta(days=3)).isoformat()),
    brut("a7", "Le club de football remporte le derby face au voisin"),
]


# --- Sans base de données ---------------------------------------------------

def test_dossier_brut_suit_la_variable_du_collecteur(monkeypatch):
    monkeypatch.setenv("GAZETTE_DOSSIER_BRUT", "/app/data/articles_bruts")
    assert dossier_brut() == Path("/app/data/articles_bruts")
    monkeypatch.delenv("GAZETTE_DOSSIER_BRUT")
    monkeypatch.setenv("GAZETTE_DATA_DIR", "/autre")
    assert dossier_brut() == Path("/autre/articles_bruts")


def test_lire_bruts_ignore_les_deja_traites_et_les_illisibles(tmp_path):
    ecrire_bruts(tmp_path, LOT[:2])
    (tmp_path / "journal-test" / "casse.json").write_text("{pas du json", encoding="utf-8")
    bruts, illisibles = lire_bruts(tmp_path, deja_traites={"a1"})
    assert [item_id for item_id, _ in bruts] == ["a2"]
    assert illisibles == 1


def test_traiter_garde_et_rejette_avec_la_regle():
    bruts = [(a["id"], a) for a in LOT]
    propres, rejets = traiter(bruts, IndexDoublons(), MAINTENANT)
    regles = {r["item_id"]: r["regle"] for r in rejets}
    assert {p["item_id"] for p in propres} == {"a1", "a7"}
    assert regles == {
        "a2": "R02_horoscope",
        "a3": "R03_tv",
        "a4": "R08_doublon_exact",
        "a5": "R05_titre_vide",
        "a6": "R06_date_future",
    }


def test_traiter_garde_le_plus_ancien_et_trace_le_doublon():
    ancien = brut("old", "Même titre assez long pour être comparé ici",
                  publie_le=(MAINTENANT - timedelta(hours=5)).isoformat())
    recent = brut("new", "Même titre assez long pour être comparé ici",
                  publie_le=(MAINTENANT - timedelta(hours=1)).isoformat())
    propres, rejets = traiter([("new", recent), ("old", ancien)], IndexDoublons(), MAINTENANT)
    assert [p["item_id"] for p in propres] == ["old"]
    assert rejets[0]["item_id"] == "new"
    assert rejets[0]["doublon_de"] == "old"


def test_traiter_ne_garde_aucun_champ_interdit():
    propres, _ = traiter([("a1", LOT[0])], IndexDoublons(), MAINTENANT)
    assert "payload" not in propres[0]
    assert "Personne Inventée" not in repr(propres[0])


# --- Avec une vraie base ----------------------------------------------------

@pytest.fixture
def conn():
    from gazette.connexion import ouvrir_connexion

    connexion = ouvrir_connexion(URL_TEST)
    with connexion.cursor() as cur:
        cur.execute("DROP TABLE IF EXISTS controles_qualite, rejets, articles_propres")
        for fichier in sorted(MIGRATIONS.glob("00[345]_*.sql")):
            cur.execute(fichier.read_text(encoding="utf-8"))
    connexion.commit()
    yield connexion
    connexion.close()


def compter(conn, table):
    with conn.cursor() as cur:
        cur.execute(f"SELECT count(*) FROM {table}")
        return cur.fetchone()[0]


@base
def test_deux_passages_zero_doublon(conn, tmp_path):
    ecrire_bruts(tmp_path, LOT)
    premier = nettoyer(conn, tmp_path, MAINTENANT)
    assert (premier["entres"], premier["gardes"], premier["rejetes"]) == (7, 2, 5)
    avant = (compter(conn, "articles_propres"), compter(conn, "rejets"))
    second = nettoyer(conn, tmp_path, MAINTENANT)
    assert second["entres"] == 0
    assert (compter(conn, "articles_propres"), compter(conn, "rejets")) == avant == (2, 5)


@base
def test_un_rejete_va_dans_rejets_avec_sa_regle(conn, tmp_path):
    ecrire_bruts(tmp_path, LOT)
    nettoyer(conn, tmp_path, MAINTENANT)
    with conn.cursor() as cur:
        cur.execute("SELECT regle, doublon_de FROM rejets WHERE item_id = 'a4'")
        assert cur.fetchone() == ("R08_doublon_exact", "a1")
        cur.execute("SELECT 1 FROM articles_propres WHERE item_id = 'a2'")
        assert cur.fetchone() is None


@base
def test_un_doublon_est_detecte_entre_deux_passages(conn, tmp_path):
    ecrire_bruts(tmp_path, LOT[:1])
    nettoyer(conn, tmp_path, MAINTENANT)
    ecrire_bruts(tmp_path, [brut("b1", LOT[0]["titre"], source="Troisieme Journal")])
    nettoyer(conn, tmp_path, MAINTENANT)
    with conn.cursor() as cur:
        cur.execute("SELECT regle FROM rejets WHERE item_id = 'b1'")
        assert cur.fetchone()[0] == "R08_doublon_exact"


@base
def test_tracabilite_de_l_article_propre_au_fichier_brut(conn, tmp_path):
    ecrire_bruts(tmp_path, LOT[:1])
    nettoyer(conn, tmp_path, MAINTENANT)
    with conn.cursor() as cur:
        cur.execute("SELECT item_id, source FROM articles_propres")
        item_id, _ = cur.fetchone()
    assert list(tmp_path.glob(f"*/{item_id}.json"))


@base
def test_le_rapport_compte_par_regle_et_par_source(conn, tmp_path):
    ecrire_bruts(tmp_path, LOT)
    nettoyer(conn, tmp_path, MAINTENANT)
    maintenant = datetime.now(timezone.utc)  # le rapport lit la journée en cours
    with conn.cursor() as cur:
        cur.execute("UPDATE articles_propres SET nettoye_le = %s", (maintenant,))
        cur.execute("UPDATE rejets SET rejete_le = %s", (maintenant,))
    conn.commit()
    chemin = ecrire_rapport(conn, maintenant.date(), tmp_path / "rapports", maintenant)
    texte = chemin.read_text(encoding="utf-8")
    assert chemin.name == f"qualite-{maintenant.date().isoformat()}.md"
    assert "| 7 | 2 | 5 |" in texte
    assert "R02_horoscope | 1" in texte
    assert "Journal Test" in texte


@base
def test_controles_ok_sur_des_donnees_propres(conn, tmp_path):
    ecrire_bruts(tmp_path, LOT)
    nettoyer(conn, tmp_path, MAINTENANT)
    envoyes = []
    bilan = executer_controles(conn, MAINTENANT, envoyer=lambda m: envoyes.append(m) or True)
    assert bilan["echecs"] == []
    assert envoyes == []
    assert compter(conn, "controles_qualite") >= 2


def _inserer_date_future(conn, maintenant):
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO articles_propres (item_id, source, titre, lien, publie_le) "
            "VALUES ('test-futur', 'Journal Test', 'Article de test', "
            "'https://exemple.test/f', %s)",
            (maintenant + timedelta(days=2),),
        )
    conn.commit()


@base
def test_alerte_sur_date_future_et_pas_de_spam(conn):
    _inserer_date_future(conn, MAINTENANT)
    envoyes = []

    def faux_envoyer(message):
        envoyes.append(message)
        return True

    premier = executer_controles(conn, MAINTENANT, envoyer=faux_envoyer)
    assert "date_future:global" in premier["echecs"]
    assert premier["alerte_envoyee"] is True
    assert "date_future" in envoyes[0]

    # un passage 10 minutes plus tard : même échec, pas de nouvelle alerte
    executer_controles(conn, MAINTENANT + timedelta(minutes=10), envoyer=faux_envoyer)
    assert len(envoyes) == 1

    # 7 heures plus tard : l'anti-spam est expiré, l'alerte repart
    executer_controles(conn, MAINTENANT + timedelta(hours=7), envoyer=faux_envoyer)
    assert len(envoyes) == 2


@base
def test_alerte_non_envoyee_est_retentee(conn):
    _inserer_date_future(conn, MAINTENANT)
    tentatives = []

    def echec(message):
        tentatives.append(message)
        return False

    executer_controles(conn, MAINTENANT, envoyer=echec)
    executer_controles(conn, MAINTENANT + timedelta(minutes=10), envoyer=echec)
    assert len(tentatives) == 2  # tant que l'envoi échoue, on réessaie


@base
def test_alerte_sur_taux_de_rejet_trop_eleve(conn):
    with conn.cursor() as cur:
        for i in range(12):
            cur.execute(
                "INSERT INTO rejets (item_id, source, titre, regle, rejete_le) "
                "VALUES (%s, 'Source Lente', 'x', 'R02_horoscope', %s)",
                (f"r{i}", MAINTENANT),
            )
        cur.execute(
            "INSERT INTO articles_propres (item_id, source, titre, lien, publie_le, nettoye_le) "
            "VALUES ('p1', 'Source Lente', 'Un titre', 'https://exemple.test/p', %s, %s)",
            (MAINTENANT - timedelta(hours=1), MAINTENANT),
        )
    conn.commit()
    bilan = executer_controles(conn, MAINTENANT, envoyer=lambda m: True)
    assert "taux_rejet_source:Source Lente" in bilan["echecs"]