"""Registre des versions du modèle de regroupement (TD 6).

Une « version » = un jeu de paramètres (le contenu de ``config/clustering.yaml`` à un
instant). Le registre (table ``versions_modele``) dit laquelle est en service :

- ``production`` : la version que le pipeline utilise (au plus une à la fois) ;
- ``candidat``   : une version enregistrée, pas encore promue ;
- ``archivee``   : une ancienne production.

« Quelle version tourne ce matin, et avec quels paramètres ? » -> vue ``version_en_service``.

Promotion et retour arrière sont des actions TRACÉES (``promue_le``, ``par_qui``), pas un
``git push`` à l'aveugle. Le pipeline lit ses paramètres ici au démarrage
(``config_en_service``) : plus de paramètres codés en dur.

En ligne de commande :
    python -m gazette.registre_modele --lister
    python -m gazette.registre_modele --enregistrer [--run RUN_ID] [--par NOM]
    python -m gazette.registre_modele --promouvoir vN --par NOM
    python -m gazette.registre_modele --retour-arriere --par NOM
    python -m gazette.registre_modele --en-service
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os


def empreinte(parametres: dict) -> str:
    """SHA-256 des paramètres (même formule que themes.empreinte_config)."""
    texte = json.dumps(parametres, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(texte.encode("utf-8")).hexdigest()


def version_en_service(conn) -> dict | None:
    """La version 'production' et ses paramètres, ou None si le registre est vide."""
    ligne = conn.execute(
        "SELECT version, parametres, hash_config, run_id, promue_le, par_qui "
        "FROM versions_modele WHERE statut = 'production'"
    ).fetchone()
    if not ligne:
        return None
    return {"version": ligne[0], "parametres": ligne[1], "hash_config": ligne[2],
            "run_id": ligne[3], "promue_le": ligne[4], "par_qui": ligne[5]}


def prochaine_etiquette(conn) -> str:
    n = conn.execute("SELECT count(*) FROM versions_modele").fetchone()[0]
    return f"v{n + 1}"


def enregistrer_version(conn, parametres: dict, run_id: str | None = None,
                        statut: str = "candidat", par_qui: str | None = None,
                        note: str | None = None) -> str:
    """Enregistre une version et renvoie son étiquette.

    Si une version de même empreinte existe déjà, on ne duplique pas : on renvoie la
    sienne (et on la relie au run si elle n'en avait pas).
    """
    h = empreinte(parametres)
    existante = conn.execute(
        "SELECT version, run_id FROM versions_modele WHERE hash_config = %s", (h,)
    ).fetchone()
    if existante:
        if run_id and existante[1] is None:
            conn.execute("UPDATE versions_modele SET run_id = %s WHERE version = %s",
                         (run_id, existante[0]))
        return existante[0]
    version = prochaine_etiquette(conn)
    promue = "now()" if statut == "production" else "NULL"
    conn.execute(
        "INSERT INTO versions_modele (version, hash_config, parametres, run_id, statut, "
        f"promue_le, par_qui, note) VALUES (%s, %s, %s, %s, %s, {promue}, %s, %s)",
        (version, h, json.dumps(parametres, ensure_ascii=False), run_id, statut,
         par_qui, note),
    )
    return version


def config_en_service(conn, defaut: dict, par_qui: str = "bootstrap") -> dict:
    """Paramètres de la version en service.

    Registre vide : enregistre ``defaut`` comme v1 production (bootstrap) et le renvoie.
    Le pipeline appelle ceci au démarrage, à la place du fichier codé en dur.
    """
    service = version_en_service(conn)
    if service:
        return service["parametres"]
    enregistrer_version(conn, defaut, statut="production", par_qui=par_qui,
                        note="version initiale (bootstrap depuis config/clustering.yaml)")
    return defaut


def promouvoir(conn, version: str, par_qui: str) -> dict:
    """Promeut ``version`` en production ; l'ancienne production passe en 'archivee'."""
    if not conn.execute("SELECT 1 FROM versions_modele WHERE version = %s",
                        (version,)).fetchone():
        raise ValueError(f"version inconnue : {version}")
    with conn.transaction():
        conn.execute("UPDATE versions_modele SET statut = 'archivee' WHERE statut = 'production'")
        conn.execute(
            "UPDATE versions_modele SET statut = 'production', promue_le = now(), par_qui = %s "
            "WHERE version = %s", (par_qui, version))
    return {"version": version, "par_qui": par_qui}


def retour_arriere(conn, par_qui: str) -> dict:
    """Retour arrière : production actuelle -> archivée, et la version archivée la plus
    récemment promue -> production. Renvoie {ancienne, nouvelle}."""
    actuelle = version_en_service(conn)
    if not actuelle:
        raise ValueError("aucune version en production : rien à annuler")
    precedente = conn.execute(
        "SELECT version FROM versions_modele WHERE statut = 'archivee' AND version <> %s "
        "ORDER BY promue_le DESC NULLS LAST LIMIT 1", (actuelle["version"],)
    ).fetchone()
    if not precedente:
        raise ValueError("aucune version précédente à restaurer")
    with conn.transaction():
        conn.execute("UPDATE versions_modele SET statut = 'archivee' WHERE statut = 'production'")
        conn.execute(
            "UPDATE versions_modele SET statut = 'production', promue_le = now(), par_qui = %s "
            "WHERE version = %s", (par_qui, precedente[0]))
    return {"ancienne": actuelle["version"], "nouvelle": precedente[0]}


def lister(conn) -> list[dict]:
    colonnes = ("version", "statut", "hash_config", "run_id", "cree_le", "promue_le", "par_qui")
    lignes = conn.execute(
        "SELECT version, statut, hash_config, run_id, cree_le, promue_le, par_qui "
        "FROM versions_modele ORDER BY cree_le"
    ).fetchall()
    return [dict(zip(colonnes, r)) for r in lignes]


# --- Ligne de commande --------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Registre des versions du modèle (TD 6)")
    parser.add_argument("--lister", action="store_true", help="liste toutes les versions")
    parser.add_argument("--en-service", action="store_true", help="la version en production")
    parser.add_argument("--enregistrer", action="store_true",
                        help="enregistre config/clustering.yaml comme nouvelle version candidate")
    parser.add_argument("--promouvoir", metavar="VERSION", help="promeut une version en production")
    parser.add_argument("--retour-arriere", action="store_true",
                        dest="retour", help="revient à la version précédente")
    parser.add_argument("--run", help="relie la version enregistrée à ce run_id")
    parser.add_argument("--par", default=os.environ.get("USER", "inconnu"), help="qui agit (trace)")
    args = parser.parse_args()

    from gazette.connexion import ouvrir_connexion
    from gazette.migrations import appliquer_migrations
    from gazette.themes import charger_config

    conn = ouvrir_connexion()
    conn.autocommit = True
    appliquer_migrations(conn)
    try:
        if args.promouvoir:
            r = promouvoir(conn, args.promouvoir, args.par)
            print(f"{r['version']} est maintenant en production (par {r['par_qui']}).")
        elif args.retour:
            r = retour_arriere(conn, args.par)
            print(f"Retour arrière : {r['ancienne']} -> {r['nouvelle']} en production.")
        elif args.enregistrer:
            v = enregistrer_version(conn, charger_config(), run_id=args.run, par_qui=args.par)
            print(f"Version enregistrée : {v} (statut candidat).")
        elif args.en_service:
            s = version_en_service(conn)
            print(json.dumps(s, ensure_ascii=False, default=str, indent=2) if s
                  else "Aucune version en production.")
        else:
            for v in lister(conn):
                print(f"{v['version']:>4}  {v['statut']:<10}  run={v['run_id']}  "
                      f"promue_le={v['promue_le']}  par={v['par_qui']}")
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())