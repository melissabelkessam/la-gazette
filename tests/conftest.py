"""Outils partagés par les tests : un faux éditeur de presse, servi en local."""

from __future__ import annotations

import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest


class FauxEditeur:
    """Un serveur HTTP local dont on choisit les réponses, et qui compte les appels."""

    def __init__(self, reponses):
        self.reponses = list(reponses)  # liste de (statut, corps, entêtes), la dernière se répète
        self.requetes = []
        editeur = self

        class Gestionnaire(BaseHTTPRequestHandler):
            def do_GET(self):
                editeur.requetes.append(dict(self.headers))
                rang = min(len(editeur.requetes), len(editeur.reponses)) - 1
                statut, corps, entetes = editeur.reponses[rang]
                self.send_response(statut)
                for cle, valeur in entetes.items():
                    self.send_header(cle, valeur)
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)

            def log_message(self, *args):
                pass

        self.serveur = ThreadingHTTPServer(("127.0.0.1", 0), Gestionnaire)
        self.url = f"http://127.0.0.1:{self.serveur.server_port}/rss.xml"
        threading.Thread(target=self.serveur.serve_forever, daemon=True).start()

    def fermer(self):
        self.serveur.shutdown()
        self.serveur.server_close()


@pytest.fixture
def editeur(request):
    serveurs = []

    def creer(*reponses):
        serveur = FauxEditeur(reponses)
        serveurs.append(serveur)
        return serveur

    yield creer
    for serveur in serveurs:
        serveur.fermer()