"""
Import d'une offre d'emploi à partir de son lien (Welcome to the Jungle,
Indeed, HelloWork, APEC, site carrière d'une entreprise...).

La plupart des sites d'offres décrivent l'annonce dans un bloc de données
structurées standard (schema.org « JobPosting », utilisé par Google pour son
moteur d'emplois) : on y lit directement l'intitulé, l'entreprise, l'adresse
et la description. À défaut, on récupère le texte principal de la page.

Sécurité : seuls les liens http(s) vers des sites publics sont acceptés
(adresses du réseau local refusées, y compris après une redirection et au
moment même de la connexion, ce qui déjoue les DNS « piégés »), avec un
délai et une taille de page maximaux. Le contenu récupéré n'est jamais
exécuté ni affiché comme du HTML : il est seulement converti en texte brut.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlparse

DELAI_SECONDES = (6, 15)  # connexion, lecture
TAILLE_MAX_OCTETS = 4 * 1024 * 1024
LONGUEUR_MAX_TEXTE = 15000
REDIRECTIONS_MAX = 5
ENTETES = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.6",
}


class ErreurImport(Exception):
    """Erreur lisible à afficher telle quelle dans l'interface."""


@dataclass
class OffreImportee:
    texte: str
    entreprise: str = ""
    poste: str = ""
    adresse: str = ""
    structuree: bool = False  # True si lue depuis les données JobPosting (plus fiable)


def normaliser_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        raise ErreurImport("Colle d'abord le lien de l'offre.")
    if "://" not in url:
        if re.match(r"^[a-zA-Z][a-zA-Z0-9+-]*:(?!\d)", url):
            raise ErreurImport("Lien invalide : il doit commencer par http:// ou https://.")
        url = "https://" + url
    morceaux = urlparse(url)
    if morceaux.scheme not in ("http", "https") or "." not in (morceaux.hostname or ""):
        raise ErreurImport("Lien invalide : il doit commencer par http:// ou https://.")
    # LinkedIn : une offre ouverte depuis la recherche a pour adresse
    # .../jobs/search/?currentJobId=123 ; la page publique de l'offre est /jobs/view/123.
    if morceaux.hostname.endswith("linkedin.com"):
        identifiant = parse_qs(morceaux.query).get("currentJobId", [""])[0]
        if identifiant.isdigit():
            return f"https://www.linkedin.com/jobs/view/{identifiant}/"
    return url


MESSAGE_ADRESSE_LOCALE = "Ce lien pointe vers une adresse locale : seuls les sites publics sont acceptés."


def _ip_interdite(adresse: str) -> bool:
    """Adresse du réseau local (box, imprimante, services de l'ordinateur...)."""
    try:
        ip = ipaddress.ip_address(str(adresse).split("%")[0])
    except ValueError:
        return True
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped  # ::ffff:127.0.0.1 = 127.0.0.1
    return (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast
            or ip.is_unspecified)


def _adresse_publique(hote: str) -> bool:
    """Refuse les adresses du réseau local : un lien d'offre pointe toujours
    vers un site public."""
    try:
        infos = socket.getaddrinfo(hote, None)
    except socket.gaierror as exc:
        raise ErreurImport(f"Site introuvable ({hote}) : vérifie le lien et ta connexion Internet.") from exc
    return not any(_ip_interdite(info[4][0]) for info in infos)


_SESSION_CLASSES = None


def _classes_session():
    """Session requests qui revérifie l'adresse RÉELLEMENT contactée, au moment
    de la connexion : un site piégé qui répondrait d'abord une adresse
    publique puis 127.0.0.1 (« DNS rebinding ») est refusé quand même."""
    global _SESSION_CLASSES
    if _SESSION_CLASSES is None:
        import requests
        from urllib3.connection import HTTPConnection, HTTPSConnection
        from urllib3.connectionpool import HTTPConnectionPool, HTTPSConnectionPool

        def verifier(connexion) -> None:
            if getattr(connexion, "proxy", None) or getattr(connexion, "_tunnel_host", None):
                return  # passage par un proxy : c'est lui qui contacte le site
            try:
                adresse = connexion.sock.getpeername()[0]
            except (AttributeError, OSError):
                return
            if _ip_interdite(adresse):
                connexion.close()
                raise ErreurImport(MESSAGE_ADRESSE_LOCALE)

        class ConnexionHTTP(HTTPConnection):
            def connect(self):
                super().connect()
                verifier(self)

        class ConnexionHTTPS(HTTPSConnection):
            def connect(self):
                super().connect()
                verifier(self)

        class PoolHTTP(HTTPConnectionPool):
            ConnectionCls = ConnexionHTTP

        class PoolHTTPS(HTTPSConnectionPool):
            ConnectionCls = ConnexionHTTPS

        class Adaptateur(requests.adapters.HTTPAdapter):
            def init_poolmanager(self, *args, **kwargs):
                super().init_poolmanager(*args, **kwargs)
                self.poolmanager.pool_classes_by_scheme = {"http": PoolHTTP, "https": PoolHTTPS}

        _SESSION_CLASSES = Adaptateur
    return _SESSION_CLASSES


def _ouvrir(url: str):
    """GET en suivant les redirections une par une, en revérifiant à chaque
    étape que la destination est bien un site public en http(s)."""
    import requests

    session = requests.Session()
    adaptateur = _classes_session()()
    session.mount("http://", adaptateur)
    session.mount("https://", adaptateur)
    for _ in range(REDIRECTIONS_MAX + 1):
        morceaux = urlparse(url)
        if morceaux.scheme not in ("http", "https") or not morceaux.hostname:
            raise ErreurImport("Redirection vers un lien non autorisé.")
        if not _adresse_publique(morceaux.hostname):
            raise ErreurImport(MESSAGE_ADRESSE_LOCALE)
        reponse = session.get(url, headers=ENTETES, timeout=DELAI_SECONDES, stream=True, allow_redirects=False)
        if reponse.is_redirect and reponse.headers.get("location"):
            url = urljoin(url, reponse.headers["location"])
            reponse.close()
            continue
        return reponse
    raise ErreurImport("Trop de redirections : copie-colle le texte de l'annonce à la place.")


def telecharger(url: str) -> str:
    import requests

    try:
        with _ouvrir(url) as reponse:
            if reponse.status_code in (401, 403, 429, 999):
                raise ErreurImport(
                    f"Ce site refuse la lecture automatique (code {reponse.status_code}) — fréquent sur "
                    "LinkedIn ou Indeed. Copie-colle le texte de l'annonce à la place."
                )
            if reponse.status_code == 404:
                raise ErreurImport("Offre introuvable (erreur 404) : elle a peut-être été retirée.")
            if reponse.status_code >= 400:
                raise ErreurImport(f"Le site a répondu par une erreur ({reponse.status_code}).")
            morceaux, taille = [], 0
            for morceau in reponse.iter_content(chunk_size=65536):
                taille += len(morceau)
                if taille > TAILLE_MAX_OCTETS:
                    break  # page anormalement lourde : le début suffit largement
                morceaux.append(morceau)
            return _decoder(b"".join(morceaux), reponse.headers.get("content-type", ""))
    except requests.exceptions.Timeout as exc:
        raise ErreurImport("Le site met trop de temps à répondre : réessaie ou copie-colle l'annonce.") from exc
    except requests.exceptions.RequestException as exc:
        raise ErreurImport(f"Impossible de lire la page : {exc.__class__.__name__}.") from exc


def _decoder(brut: bytes, type_contenu: str) -> str:
    """Texte de la page à partir des SEULS octets reçus (jamais de relecture du
    flux, qui contournerait la taille maximale) : encodage annoncé par le
    serveur, sinon celui déclaré dans la page, sinon détecté."""
    from bs4.dammit import UnicodeDammit

    annonce = re.search(r"charset=[\"']?([\w.:-]+)", type_contenu or "", re.IGNORECASE)
    encodage = annonce.group(1).lower() if annonce else ""
    if encodage in ("iso-8859-1", "latin-1", "latin1", "windows-1252", "cp1252"):
        try:
            return brut.decode("utf-8")  # page en UTF-8 annoncée à tort en Latin-1 (fréquent)
        except UnicodeDecodeError:
            pass
    dammit = UnicodeDammit(brut, known_definite_encodings=[encodage] if encodage else [], is_html=True)
    if dammit.unicode_markup is not None:
        return dammit.unicode_markup
    return brut.decode("utf-8", errors="replace")


def _html_vers_texte(html: str) -> str:
    from bs4 import BeautifulSoup

    soupe = BeautifulSoup(html, "html.parser")
    for balise in soupe(["script", "style", "noscript", "template", "svg"]):
        balise.decompose()
    for saut in soupe.find_all(["br"]):
        saut.replace_with("\n")
    for bloc in soupe.find_all(["p", "div", "li", "h1", "h2", "h3", "h4", "tr", "section", "ul", "ol"]):
        bloc.insert_before("\n")
    for puce in soupe.find_all("li"):
        puce.insert_before("• ")
    return _nettoyer_texte(soupe.get_text())


def _nettoyer_texte(texte: str) -> str:
    texte = texte.replace("\xa0", " ").replace("\r", "")
    lignes = [re.sub(r"[ \t]+", " ", ligne).strip() for ligne in texte.split("\n")]
    texte = "\n".join(lignes)
    texte = re.sub(r"\n{3,}", "\n\n", texte)
    texte = re.sub(r"(•\s*\n)+", "• ", texte)
    return texte.strip()[:LONGUEUR_MAX_TEXTE]


def _blocs_json_ld(html: str) -> list:
    from bs4 import BeautifulSoup

    soupe = BeautifulSoup(html, "html.parser")
    blocs = []
    for script in soupe.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        contenu = (script.string or script.get_text() or "").strip()
        contenu = re.sub(r"^\s*<!\[CDATA\[|\]\]>\s*$", "", contenu)
        try:
            blocs.append(json.loads(contenu, strict=False))
        except (ValueError, RecursionError):  # JSON invalide ou imbriqué à l'extrême : bloc ignoré
            continue
    return blocs


PROFONDEUR_MAX_JSON_LD = 12


def _est_offre(types) -> bool:
    types = types if isinstance(types, list) else [types]
    return any(isinstance(t, str) and t.rsplit("/", 1)[-1] == "JobPosting" for t in types)


def _trouver_offre(donnees, profondeur: int = 0) -> dict | None:
    """Cherche récursivement un objet de type JobPosting."""
    if profondeur > PROFONDEUR_MAX_JSON_LD:
        return None
    if isinstance(donnees, list):
        for element in donnees:
            trouve = _trouver_offre(element, profondeur + 1)
            if trouve:
                return trouve
    elif isinstance(donnees, dict):
        if _est_offre(donnees.get("@type")):
            return donnees
        for cle in ("@graph", "mainEntity", "itemListElement", "item"):
            if cle in donnees:
                trouve = _trouver_offre(donnees[cle], profondeur + 1)
                if trouve:
                    return trouve
    return None


def _texte_brut_json(valeur, profondeur: int = 0) -> str:
    """Description d'une offre, quelle que soit sa forme (texte, liste, objet)."""
    if profondeur > PROFONDEUR_MAX_JSON_LD:
        return ""
    if isinstance(valeur, str):
        return valeur
    if isinstance(valeur, list):
        return "\n".join(t for t in (_texte_brut_json(v, profondeur + 1) for v in valeur) if t)
    if isinstance(valeur, dict):
        return _texte_brut_json(valeur.get("@value") or valeur.get("text") or valeur.get("description"),
                                profondeur + 1)
    return ""


def _texte_simple(valeur) -> str:
    if isinstance(valeur, str):
        return " ".join(valeur.split())
    if isinstance(valeur, dict):
        return _texte_simple(valeur.get("name") or valeur.get("value") or "")
    if isinstance(valeur, list) and valeur:
        return _texte_simple(valeur[0])
    return ""


def _adresse(offre: dict) -> str:
    lieu = offre.get("jobLocation")
    lieu = lieu[0] if isinstance(lieu, list) and lieu else lieu
    if not isinstance(lieu, dict):
        return ""
    adresse = lieu.get("address")
    if isinstance(adresse, str):
        return " ".join(adresse.split())
    if not isinstance(adresse, dict):
        return ""
    rue = _texte_simple(adresse.get("streetAddress"))
    code, commune = _texte_simple(adresse.get("postalCode")), _texte_simple(adresse.get("addressLocality"))
    ville = " ".join(p for p in (code, commune) if p)
    return ", ".join(p for p in (rue, ville) if p)


def extraire_offre(html: str) -> OffreImportee:
    """Analyse le HTML d'une page d'offre (sans accès réseau : testable)."""
    offre = None
    for bloc in _blocs_json_ld(html):
        offre = _trouver_offre(bloc)
        if offre:
            break
    if offre:
        description = _texte_brut_json(offre.get("description"))
        texte = _html_vers_texte(description) if "<" in description else _nettoyer_texte(description)
        poste = _texte_simple(offre.get("title"))
        entreprise = _texte_simple(offre.get("hiringOrganization"))
        en_tete = "\n".join(p for p in (poste, entreprise) if p)
        return OffreImportee(
            texte=_nettoyer_texte(f"{en_tete}\n\n{texte}" if en_tete else texte),
            entreprise=entreprise,
            poste=poste,
            adresse=_adresse(offre),
            structuree=True,
        )

    from bs4 import BeautifulSoup

    soupe = BeautifulSoup(html, "html.parser")
    titre = ""
    meta = soupe.find("meta", attrs={"property": "og:title"})
    if meta and meta.get("content"):
        titre = " ".join(meta["content"].split())
    elif soupe.title and soupe.title.string:
        titre = " ".join(soupe.title.string.split())
    for balise in soupe(["nav", "header", "footer", "aside", "form", "button"]):
        balise.decompose()
    candidats = soupe.find_all(["main", "article"]) or [soupe.body or soupe]
    principal = max(candidats, key=lambda e: len(e.get_text(" ", strip=True)))
    texte = _html_vers_texte(str(principal))
    if len(texte) < 200:
        raise ErreurImport(
            "Impossible de trouver le texte de l'offre sur cette page (contenu chargé "
            "dynamiquement ou page protégée). Copie-colle le texte de l'annonce à la place."
        )
    return OffreImportee(texte=_nettoyer_texte(f"{titre}\n\n{texte}" if titre else texte), poste="")


def importer_offre(url: str) -> OffreImportee:
    html = telecharger(normaliser_url(url))
    try:
        return extraire_offre(html)
    except ErreurImport:
        raise
    except Exception as exc:  # noqa: BLE001 - page au format inattendu : message clair plutôt qu'un plantage
        raise ErreurImport(
            "Le contenu de cette page n'a pas pu être lu : copie-colle le texte de l'annonce à la place."
        ) from exc
