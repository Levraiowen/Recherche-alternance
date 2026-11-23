import json

import pytest

import import_offre
from import_offre import ErreurImport, extraire_offre, normaliser_url

OFFRE = {
    "@context": "https://schema.org",
    "@type": "JobPosting",
    "title": "Data Analyst en alternance (H/F)",
    "description": "<p>Missions :</p><ul><li>Construire des tableaux de bord <b>Power BI</b></li>"
                   "<li>Analyses SQL &amp; Python</li></ul><p>Profil : Bac+3 en statistiques.</p>",
    "hiringOrganization": {"@type": "Organization", "name": "Nova Énergie"},
    "jobLocation": {"@type": "Place", "address": {"@type": "PostalAddress", "streetAddress": "20 quai Exemple",
                                                  "postalCode": "69002", "addressLocality": "Lyon"}},
}


def _page(*blocs: str, corps: str = "") -> str:
    scripts = "".join(f'<script type="application/ld+json">{b}</script>' for b in blocs)
    return f"<html><head><title>Offre</title>{scripts}</head><body>{corps}</body></html>"


def test_lecture_jobposting():
    offre = extraire_offre(_page(json.dumps(OFFRE)))
    assert offre.structuree
    assert (offre.entreprise, offre.poste) == ("Nova Énergie", "Data Analyst en alternance (H/F)")
    assert offre.adresse == "20 quai Exemple, 69002 Lyon"
    assert "• Construire des tableaux de bord Power BI" in offre.texte
    assert "Analyses SQL & Python" in offre.texte and "<" not in offre.texte


def test_jobposting_dans_un_graphe_et_json_invalide_ignore():
    graphe = json.dumps({"@context": "https://schema.org", "@graph": [{"@type": "WebPage"}, OFFRE]})
    offre = extraire_offre(_page("{ json cassé", graphe))
    assert offre.entreprise == "Nova Énergie"


def test_repli_sur_le_texte_principal():
    corps = "<nav>Menu Accueil Connexion</nav><main><h1>Chargé d'études</h1>" + "<p>Mission détaillée.</p>" * 30
    offre = extraire_offre(_page(corps=corps))
    assert not offre.structuree and "Mission détaillée." in offre.texte and "Menu Accueil" not in offre.texte


def test_page_sans_contenu_utile():
    with pytest.raises(ErreurImport):
        extraire_offre(_page(corps="<div id='app'></div>"))


def test_normalisation_et_securite_des_liens(monkeypatch):
    assert normaliser_url("www.exemple.org/offre") == "https://www.exemple.org/offre"
    assert normaliser_url("https://www.linkedin.com/jobs/search/?currentJobId=4242&k=data") == \
        "https://www.linkedin.com/jobs/view/4242/"
    for mauvais in ("", "file:///C:/Windows/win.ini", "javascript:alert(1)"):
        with pytest.raises(ErreurImport):
            normaliser_url(mauvais)
    # Adresses du réseau local refusées avant tout téléchargement
    monkeypatch.setattr(import_offre.socket, "getaddrinfo", lambda h, p: [(0, 0, 0, "", ("192.168.1.1", 0))])
    with pytest.raises(ErreurImport, match="locale"):
        import_offre.telecharger("http://box.local/admin")


def test_redirection_vers_le_reseau_local_refusee(monkeypatch):
    class Reponse:
        is_redirect = True
        headers = {"location": "http://127.0.0.1:8501/"}

        def close(self):
            pass

    class Session:
        def mount(self, prefixe, adaptateur):
            pass

        def get(self, url, **kwargs):
            return Reponse()

    import requests

    adresses = {"offres.exemple.org": "93.184.216.34", "127.0.0.1": "127.0.0.1"}
    monkeypatch.setattr(import_offre.socket, "getaddrinfo",
                        lambda h, p: [(0, 0, 0, "", (adresses[h], 0))])
    monkeypatch.setattr(requests, "Session", Session)
    with pytest.raises(ErreurImport, match="locale"):
        import_offre.telecharger("https://offres.exemple.org/offre/1")


def test_decodage_sans_relire_le_flux(monkeypatch):
    page = "<html><body><main>" + "<p>Mission détaillée en alternance data à Lyon.</p>" * 30 + "</main></body></html>"

    class Reponse:
        status_code = 200
        is_redirect = False

        def __init__(self, type_contenu, corps, repetitions=1):
            self.headers = {"content-type": type_contenu}
            self._corps, self._repetitions = corps, repetitions

        def iter_content(self, chunk_size):
            for _ in range(self._repetitions):
                yield self._corps

        @property
        def content(self):  # relire le flux contournerait la taille maximale
            raise AssertionError("le contenu ne doit jamais être relu")

        apparent_encoding = content

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    cas = {
        "sans-charset": Reponse("text/html", page.encode("utf-8")),
        "latin1-annonce-a-tort": Reponse("text/html; charset=ISO-8859-1", page.encode("utf-8")),
        "vrai-latin1": Reponse("text/html", ('<meta charset="iso-8859-1">' + page).encode("latin-1")),
        "enorme": Reponse("text/html", b"<p>" + b"x" * 1_000_000, repetitions=50),
    }
    monkeypatch.setattr(import_offre, "_ouvrir", lambda url: cas[url])
    for nom in ("sans-charset", "latin1-annonce-a-tort", "vrai-latin1"):
        assert "Mission détaillée" in import_offre.telecharger(nom), nom
    assert len(import_offre.telecharger("enorme")) <= import_offre.TAILLE_MAX_OCTETS + 10


def test_json_ld_aux_formes_inattendues():
    offre = dict(OFFRE, description=["<p>Missions : tableaux de bord</p>", "<p>Profil : statistiques</p>"],
                 **{"@type": "https://schema.org/JobPosting"})
    resultat = extraire_offre(_page(json.dumps(offre)))
    assert resultat.structuree and "tableaux de bord" in resultat.texte and "statistiques" in resultat.texte
    # JSON imbriqué à l'extrême : ignoré sans planter (repli sur le texte de la page)
    corps = "<main>" + "<p>Texte de l'offre suffisamment long pour être retenu.</p>" * 8 + "</main>"
    assert not extraire_offre(_page("[" * 100000 + "]" * 100000, corps=corps)).structuree


def test_dns_piege_refuse_a_la_connexion(monkeypatch):
    """Le site répond d'abord une adresse publique (contrôle), puis 127.0.0.1
    au moment de la connexion : la requête doit quand même être refusée."""
    import http.server
    import socket
    import threading

    visites = []

    class Serveur(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            visites.append(self.path)
            corps = b"<html><body><main>" + b"<p>Page d'administration locale.</p>" * 20 + b"</main></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)

    serveur = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Serveur)
    port = serveur.server_address[1]
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    for variable in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.delenv(variable, raising=False)
    vrai_getaddrinfo = socket.getaddrinfo
    appels = []

    def faux_dns(hote, port_, *args, **kwargs):
        if hote != "offre.piege.example":
            return vrai_getaddrinfo(hote, port_, *args, **kwargs)
        appels.append(hote)
        ip = "93.184.216.34" if len(appels) == 1 else "127.0.0.1"
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, port_ or 0))]

    monkeypatch.setattr(socket, "getaddrinfo", faux_dns)
    try:
        with pytest.raises(ErreurImport, match="locale"):
            import_offre.importer_offre(f"http://offre.piege.example:{port}/admin")
    finally:
        serveur.shutdown()
    assert len(appels) >= 2 and not visites  # connexion coupée avant tout envoi de la requête
