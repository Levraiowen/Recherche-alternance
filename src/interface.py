"""
Éléments d'interface partagés par les pages de l'app (app.py et vues/) :
style général, en-têtes, aperçus des documents, boutons de fichiers,
e-mails prêts à envoyer, petits formatages.

Principes de la charte (voir README) :
- seuls les documents (lettre, CV) sont « en relief », comme des feuilles
  posées sur le bureau ; le reste de l'interface reste plat et calme ;
- une seule couleur d'action, le bleu encre ; les couleurs vives sont
  réservées aux statuts ;
- Spectral (dessinée par une fonderie parisienne) pour les titres,
  Instrument Sans pour l'interface.
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import io
import os
import subprocess
import sys
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

import streamlit as st

import assistant
import stockage
from candidature import ResultatCandidature
from cv_editor import BlocTexte, extraire_blocs, texte_brut
from ia_commun import ResultatGeneration
from mise_en_page import VERROU_PDFIUM, ResultatMiseEnPage, lignes_en_trop_estimees
from rapport import MOIS, date_courte, date_longue

MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_PDF = "application/pdf"
RACINE = Path(__file__).resolve().parent.parent
md = assistant.echapper_markdown  # nom d'entreprise/poste affiché tel quel dans du markdown

# Couleurs des statuts (lisibles sur fond clair comme sur fond sombre).
COULEURS_STATUT = {"gray": "#8A90A0", "blue": "#4F5FE0", "orange": "#D08A2E", "violet": "#8B63DA",
                   "green": "#2F9E6A", "red": "#D3554C"}

STYLE = """
<style>
/* Largeur de lecture confortable, contenu centré */
[data-testid="stMainBlockContainer"] { max-width: 1240px; padding-top: 2.4rem; padding-bottom: 3rem; }

/* Barre du haut : un filet discret sous le logo et la navigation */
header[data-testid="stHeader"] { border-bottom: 1px solid color-mix(in srgb, currentColor 7%, transparent); }

/* Titres : Spectral, légèrement resserré, sans l'icône de lien ajoutée au survol */
h1 { letter-spacing: -0.015em; }
h2, h3 { letter-spacing: -0.008em; }
[data-testid="stMarkdownContainer"] [data-testid="stHeaderActionElements"] { display: none; }

/* Les blocs de texte ci-dessous sont écrits en HTML dans un bloc markdown :
   le préfixe [data-testid=stMarkdownContainer] leur donne priorité sur les
   styles par défaut de Streamlit. */

/* En-tête de page : la date est écrite comme en haut d'une lettre */
[data-testid="stMarkdownContainer"] .entete-date { font-family: "Spectral", Georgia, serif; font-style: italic;
    font-size: 1.02rem; opacity: .62; text-align: right; margin: 0; padding-top: 1.15rem; }
[data-testid="stMarkdownContainer"] .entete-texte { font-size: 1.02rem; opacity: .74; max-width: 64ch;
    margin: -.35rem 0 .3rem 0; }

/* Résumé éditorial des chiffres */
[data-testid="stMarkdownContainer"] .resume { font-family: "Spectral", Georgia, serif; font-size: 1.55rem;
    line-height: 1.36; max-width: 34ch; margin: .1rem 0 .4rem 0; }

/* Les documents sont les seuls objets en relief, comme des feuilles posées sur le bureau */
[class*="st-key-feuille"] img { border-radius: 2px; background: #fff;
    box-shadow: 0 1px 2px rgba(16, 24, 40, .08), 0 18px 38px -18px rgba(16, 24, 40, .45); }
[data-testid="stMarkdownContainer"] .legende-feuille { font-size: .86rem; opacity: .72; margin: .6rem 0 0 0; }

/* Liste des candidatures : lignes séparées par un filet, la sélection teintée.
   Le bouton du nom s'étend sur toute la ligne : on clique n'importe où. */
[class*="st-key-ligne_"] { position: relative; padding: .7rem .85rem .72rem .85rem; border-radius: 10px;
    gap: 0; border-bottom: 1px solid color-mix(in srgb, currentColor 8%, transparent);
    transition: background-color .12s ease; }
[class*="st-key-ligne_"]:hover { background: color-mix(in srgb, currentColor 4%, transparent); }
[class*="st-key-ligne_sel_"], [class*="st-key-ligne_sel_"]:hover {
    background: color-mix(in srgb, #4F5FE0 10%, transparent); border-bottom-color: transparent; }
[class*="st-key-ligne_"] [data-testid="stVerticalBlock"] { gap: .1rem; }
[class*="st-key-ligne_"] [data-testid="stBaseButton-tertiary"] { padding: 0; min-height: 0; color: inherit;
    justify-content: flex-start; text-align: left; }
[class*="st-key-ligne_"] [data-testid="stBaseButton-tertiary"] p { font-size: 1rem; font-weight: 600; }
[class*="st-key-ligne_"] [data-testid="stBaseButton-tertiary"]::after { content: ""; position: absolute; inset: 0; }
[class*="st-key-ligne_"] [data-testid="stColumn"], [class*="st-key-ligne_"] [data-testid="stElementContainer"],
[class*="st-key-ligne_"] [data-testid="stHorizontalBlock"], [class*="st-key-ligne_"] .stButton,
[class*="st-key-ligne_"] [data-testid="stTooltipHoverTarget"] { position: static; }
[data-testid="stMarkdownContainer"] .ligne-poste { font-size: .88rem; opacity: .68; margin: 0; }
[class*="st-key-ligne_"] [data-testid="stCaptionContainer"] { font-size: .8rem; }

/* Rappels en haut de « Nouvelle candidature » (relances, profil incomplet) : de petites pastilles */
[class*="st-key-rappels"] [data-testid="stPageLink-NavLink"] { border-radius: 999px; padding: .15rem .75rem;
    background: color-mix(in srgb, #4F5FE0 9%, transparent); }
[class*="st-key-rappels"] [data-testid="stPageLink-NavLink"]:hover {
    background: color-mix(in srgb, #4F5FE0 15%, transparent); }

/* Panneau doux : relances, vue d'ensemble */
[class*="st-key-panneau"] { background: color-mix(in srgb, currentColor 4%, transparent);
    border-radius: 14px; padding: 1.1rem 1.25rem 1.2rem 1.25rem; }

/* Faits clés d'une candidature (libellé discret au-dessus de la valeur), en grille */
[data-testid="stMarkdownContainer"] .faits { display: grid; gap: .8rem 1.4rem; margin: .3rem 0 1.1rem 0;
    grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); }
[data-testid="stMarkdownContainer"] .fait { margin: 0; }
[data-testid="stMarkdownContainer"] .fait small { display: block; font-size: .78rem; opacity: .62; }
[data-testid="stMarkdownContainer"] .fait span { font-size: .96rem; }

/* Barre de répartition des statuts */
[data-testid="stMarkdownContainer"] .repartition { display: flex; height: 10px; border-radius: 999px;
    overflow: hidden; gap: 2px; background: color-mix(in srgb, currentColor 8%, transparent); }
[data-testid="stMarkdownContainer"] .repartition span { display: block; height: 100%; }
[data-testid="stMarkdownContainer"] .legende { display: flex; flex-wrap: wrap; gap: .35rem 1.15rem;
    font-size: .86rem; margin: .7rem 0 .2rem 0; }
[data-testid="stMarkdownContainer"] .legende i { display: inline-block; width: .58rem; height: .58rem;
    border-radius: 50%; margin-right: .38rem; }
[data-testid="stMarkdownContainer"] .legende b { font-weight: 600; margin-left: .25rem; }

/* États vides : une invitation à agir */
[data-testid="stMarkdownContainer"] .etat-vide { text-align: center; padding: 2.6rem 1rem 2.2rem 1rem; }
[data-testid="stMarkdownContainer"] .etat-vide svg { width: 150px; height: auto; margin: 0 auto 1.1rem auto;
    display: block; }
[data-testid="stMarkdownContainer"] .etat-vide .titre { font-family: "Spectral", Georgia, serif;
    font-size: 1.32rem; margin: 0; }
[data-testid="stMarkdownContainer"] .etat-vide .texte { opacity: .7; max-width: 42ch; margin: .45rem auto 0 auto;
    font-size: .97rem; }

/* Aperçu de l'en-tête de lettre (page Profil) : une vraie feuille, même en thème sombre */
[data-testid="stMarkdownContainer"] .mini-lettre { background: #fff; color: #1B2030; border-radius: 2px;
    padding: 1.5rem 1.6rem 1.9rem 1.6rem; font-family: Calibri, Carlito, "Instrument Sans", sans-serif;
    font-size: .78rem; line-height: 1.5;
    box-shadow: 0 1px 2px rgba(16, 24, 40, .08), 0 18px 38px -18px rgba(16, 24, 40, .45); }
[data-testid="stMarkdownContainer"] .mini-lettre p { margin: 0; font-size: .78rem; }
[data-testid="stMarkdownContainer"] .mini-lettre .nom { font-weight: 700; }
[data-testid="stMarkdownContainer"] .mini-lettre .droite { text-align: right; }
[data-testid="stMarkdownContainer"] .mini-lettre .ecart { height: .9rem; }
[data-testid="stMarkdownContainer"] .mini-lettre .objet { font-weight: 700; }
[data-testid="stMarkdownContainer"] .mini-lettre .vide { color: #B3B8C6; font-style: italic; }
[data-testid="stMarkdownContainer"] .mini-lettre i.trait { display: block; height: .42rem; border-radius: 2px;
    background: #E9ECF2; margin: .5rem 0; }

/* Pied de page */
[class*="st-key-pied"] { border-top: 1px solid color-mix(in srgb, currentColor 8%, transparent);
    margin-top: 2.5rem; padding-top: .9rem; }
[class*="st-key-pied"] [data-testid="stCaptionContainer"] { opacity: .8; }

/* Onglets un peu plus aérés */
[data-baseweb="tab-list"] { gap: 1.35rem; }

@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
</style>
"""


def injecter_style() -> None:
    """Style commun, injecté une fois par affichage."""
    if hasattr(st, "html"):
        st.html(STYLE)
    else:  # Streamlit plus ancien
        st.markdown(STYLE, unsafe_allow_html=True)


def html(contenu: str) -> None:
    """Petit fragment HTML (déjà échappé) dans la page."""
    st.markdown(contenu, unsafe_allow_html=True)


def echapper_html(texte: str) -> str:
    import html as module_html

    return module_html.escape(texte or "", quote=True)


# ----------------------------------------------------------------------------
# En-têtes et états vides
# ----------------------------------------------------------------------------


def ligne_date(profil: dict | None = None, jour: date | None = None) -> str:
    """« Nanterre, le 23 novembre 2026 » : la ligne qu'on écrit en haut d'une lettre."""
    jour = jour or date.today()
    ville = ((profil or {}).get("ville") or "").strip()
    return f"{ville}, le {date_longue(jour)}" if ville else f"Le {date_longue(jour)}"


def entete(titre: str, description: str = "", profil: dict | None = None) -> None:
    col_titre, col_date = st.columns([3, 1.4], vertical_alignment="top")
    with col_titre:
        st.title(titre, anchor=False)
    with col_date:
        html(f'<p class="entete-date">{echapper_html(ligne_date(profil))}</p>')
    if description:
        html(f'<p class="entete-texte">{description}</p>')


ILLUSTRATIONS = {
    # Deux feuilles vierges, la lettre devant le CV
    "feuilles": """<svg viewBox="0 0 160 120" fill="none" xmlns="http://www.w3.org/2000/svg">
<rect x="58" y="10" width="72" height="96" rx="3" stroke="currentColor" stroke-opacity=".35" stroke-width="1.6"/>
<path d="M68 26h40M68 34h52M68 42h46" stroke="currentColor" stroke-opacity=".25" stroke-width="1.6"
 stroke-linecap="round"/>
<rect x="30" y="20" width="72" height="96" rx="3" fill="var(--fond-feuille, #fff)" stroke="#4F5FE0"
 stroke-width="1.8"/>
<path d="M40 38h26M40 52h52M40 60h52M40 68h52M40 76h34" stroke="#4F5FE0" stroke-opacity=".55"
 stroke-width="1.8" stroke-linecap="round"/>
<path d="M40 96c6-6 10 4 16-2s9 3 14-1" stroke="#4F5FE0" stroke-width="1.8" stroke-linecap="round"/>
</svg>""",
    # Une enveloppe ouverte d'où dépasse une lettre
    "enveloppe": """<svg viewBox="0 0 160 120" fill="none" xmlns="http://www.w3.org/2000/svg">
<rect x="46" y="14" width="68" height="62" rx="3" stroke="#4F5FE0" stroke-width="1.8"/>
<path d="M56 30h48M56 38h48M56 46h30" stroke="#4F5FE0" stroke-opacity=".55" stroke-width="1.8"
 stroke-linecap="round"/>
<path d="M28 58l52 34 52-34v46a4 4 0 0 1-4 4H32a4 4 0 0 1-4-4V58z" fill="var(--fond-feuille, #fff)"
 stroke="currentColor" stroke-opacity=".45" stroke-width="1.6" stroke-linejoin="round"/>
<path d="M28 104l38-26M132 104l-38-26" stroke="currentColor" stroke-opacity=".3" stroke-width="1.6"
 stroke-linecap="round"/>
</svg>""",
    # Une feuille avec un signe plus
    "cv": """<svg viewBox="0 0 160 120" fill="none" xmlns="http://www.w3.org/2000/svg">
<path d="M52 10h40l16 16v80a4 4 0 0 1-4 4H52a4 4 0 0 1-4-4V14a4 4 0 0 1 4-4z" stroke="currentColor"
 stroke-opacity=".45" stroke-width="1.6"/>
<path d="M92 10v12a4 4 0 0 0 4 4h12" stroke="currentColor" stroke-opacity=".45" stroke-width="1.6"/>
<circle cx="78" cy="64" r="16" stroke="#4F5FE0" stroke-width="1.8"/>
<path d="M78 56v16M70 64h16" stroke="#4F5FE0" stroke-width="1.8" stroke-linecap="round"/>
</svg>""",
}


def etat_vide(illustration: str, titre: str, texte: str) -> None:
    html(f'<div class="etat-vide">{ILLUSTRATIONS[illustration]}<p class="titre">{echapper_html(titre)}</p>'
         f'<p class="texte">{echapper_html(texte)}</p></div>')


def _fait_html(libelle: str, valeur: str) -> str:
    return f'<p class="fait"><small>{echapper_html(libelle)}</small><span>{echapper_html(valeur or "—")}</span></p>'


def fait(libelle: str, valeur: str) -> None:
    """Petit fait clé : libellé discret, valeur lisible."""
    html(_fait_html(libelle, valeur))


def faits(liste: list[tuple[str, str]]) -> None:
    """Plusieurs faits clés en grille (autant de colonnes que la largeur le permet)."""
    html(f'<div class="faits">{"".join(_fait_html(libelle, valeur) for libelle, valeur in liste)}</div>')


def repartition_statuts(comptes: list[tuple[str, int]]) -> None:
    """Barre horizontale des statuts, avec sa légende chiffrée."""
    import suivi

    total = sum(n for _, n in comptes) or 1
    segments, legende = [], []
    for cle, nombre in comptes:
        nom, _, couleur = suivi.STATUTS[cle]
        teinte = COULEURS_STATUT.get(couleur, "#8A90A0")
        segments.append(f'<span style="width:{100 * nombre / total:.2f}%;background:{teinte}" '
                        f'title="{echapper_html(nom)} : {nombre}"></span>')
        legende.append(f'<span><i style="background:{teinte}"></i>{echapper_html(nom)}<b>{nombre}</b></span>')
    html(f'<div class="repartition">{"".join(segments)}</div><div class="legende">{"".join(legende)}</div>')


# ----------------------------------------------------------------------------
# Fichiers : téléchargement, dossier, aperçus
# ----------------------------------------------------------------------------


@functools.cache
def _streamlit_recent() -> bool:
    """Les boutons de téléchargement « différés » (fichier lu seulement au
    clic) existent depuis Streamlit 1.52."""
    try:
        from packaging.version import Version

        return Version(st.__version__) >= Version("1.52")
    except Exception:  # noqa: BLE001
        return False


def fichier_autorise(chemin: Path | None) -> bool:
    """Seuls les fichiers générés par l'app (dans outputs/) sont proposés au
    téléchargement : un chemin modifié dans l'historique (à la main ou par une
    sauvegarde piégée) ne peut pas servir à récupérer un autre fichier du PC."""
    if chemin is None:
        return False
    try:
        return chemin.is_file() and chemin.resolve().is_relative_to(stockage.DOSSIER_OUTPUTS.resolve())
    except OSError:
        return False


def dossier_autorise(dossier: Path | None) -> bool:
    """On n'ouvre que de vrais dossiers situés dans outputs/ : un chemin
    modifié à la main dans l'historique ne doit jamais permettre de lancer
    un programme."""
    if dossier is None:
        return False
    try:
        return dossier.is_dir() and dossier.resolve().is_relative_to(stockage.DOSSIER_OUTPUTS.resolve())
    except OSError:
        return False


def bouton_telechargement(chemin: Path | None, libelle: str, mime: str, cle: str, **options) -> bool:
    """Bouton de téléchargement si le fichier existe encore sur le disque."""
    if not fichier_autorise(chemin):
        return False
    if _streamlit_recent():
        # Fichier lu seulement au clic, sans recharger la page ensuite.
        st.download_button(libelle, data=lambda: chemin.read_bytes(), file_name=chemin.name,
                           mime=mime, key=cle, on_click="ignore", **options)
    else:
        st.download_button(libelle, data=chemin.read_bytes(), file_name=chemin.name, mime=mime, key=cle,
                           **options)
    return True


def ouvrir_dossier(dossier: Path) -> None:
    if not dossier_autorise(dossier):
        raise OSError("dossier introuvable ou hors du dossier outputs/")
    if os.name == "nt":
        os.startfile(str(dossier.resolve()))  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(dossier)])
    else:
        subprocess.Popen(["xdg-open", str(dossier)])


def bouton_ouvrir_dossier(dossier: Path | None, cle: str) -> None:
    if not dossier_autorise(dossier):
        return
    if st.button("Ouvrir le dossier", key=cle, icon=":material/folder_open:", help=str(dossier)):
        try:
            ouvrir_dossier(dossier)
        except OSError as exc:
            st.warning(f"Impossible d'ouvrir le dossier automatiquement : {exc}")


@contextlib.contextmanager
def signaler_erreur_enregistrement():
    """Un fichier de données verrouillé (antivirus, OneDrive...) donne un
    message clair plutôt qu'une page d'erreur ; rien n'est perdu."""
    try:
        yield
    except OSError as exc:
        st.error(f"Enregistrement impossible pour le moment : {exc}")


@st.cache_data(show_spinner=False, max_entries=24)
def _apercu_png(chemin: str, date_modif: float, largeur: int) -> bytes | None:
    """Miniature de la 1re page d'un PDF."""
    try:
        import pypdfium2 as pdfium

        with VERROU_PDFIUM:
            document = pdfium.PdfDocument(chemin)
            try:
                page = document[0]
                echelle = 2 * largeur / page.get_size()[0]  # rendu 2x : net sur les écrans haute densité
                image = page.render(scale=echelle).to_pil().convert("RGB")
            finally:
                document.close()
        tampon = io.BytesIO()
        image.save(tampon, format="PNG", optimize=True)
        return tampon.getvalue()
    except Exception:  # noqa: BLE001 - un aperçu raté ne doit rien bloquer
        return None


def feuille(chemin: Path | None, cle: str, legende: str = "", largeur: int = 420) -> None:
    """Aperçu d'un document, présenté comme une feuille posée sur le bureau."""
    if not fichier_autorise(chemin):
        return
    png = _apercu_png(str(chemin), chemin.stat().st_mtime, largeur)
    with st.container(key=f"feuille_{cle}"):
        if png:
            st.image(png, width="stretch")
        if legende:
            html(f'<p class="legende-feuille">{legende}</p>')


def statut_page(nom: str, resultat: ResultatMiseEnPage | None) -> str:
    """Légende d'une feuille : « 1 page » (et le resserrement éventuel)."""
    if resultat is None or resultat.chemin_pdf is None:
        return ""
    if resultat.une_page:
        return "1 page" if resultat.niveau == 0 else f"1 page, mise en page resserrée ({resultat.description})"
    return f"{resultat.pages} pages"


def alerte_pages(nom: str, resultat: ResultatMiseEnPage | None) -> None:
    if resultat is None or resultat.chemin_pdf is None or resultat.une_page:
        return
    conseil = ("Raccourcis un peu ton CV de référence (page Mes CV)." if nom == "CV"
               else "Raccourcis un paragraphe dans l'onglet Retouches.")
    st.warning(f"{nom} : encore {resultat.pages} pages, même avec la mise en page la plus resserrée (environ "
               f"{lignes_en_trop_estimees(resultat)} ligne(s) de trop). {conseil}", icon=":material/warning:")


# ----------------------------------------------------------------------------
# E-mails et textes
# ----------------------------------------------------------------------------


def lien_mailto(objet: str, corps: str, destinataire: str = "") -> str:
    """Lien qui ouvre la messagerie avec le message prérempli. Tout est encodé
    (un « ? » ou un « & » dans l'adresse ne peut pas ajouter de destinataire
    caché) ; sauts de ligne en CRLF comme le veut la norme des liens mailto."""
    destinataire = destinataire.strip() if "@" in (destinataire or "") else ""
    corps = (corps or "").replace("\r\n", "\n").replace("\n", "\r\n")
    return f"mailto:{quote(destinataire, safe='@')}?subject={quote(objet or '', safe='')}&body={quote(corps, safe='')}"


def bloc_mail(objet: str, corps: str, destinataire: str) -> None:
    """E-mail prêt à copier (bouton de copie intégré) ou à ouvrir dans la messagerie."""
    st.caption("Objet")
    st.code(objet or "(sans objet)", language=None, wrap_lines=True)
    st.caption("Message")
    st.code(corps, language=None, wrap_lines=True)
    # Pas de `key=` : st.link_button ne l'accepte pas avant les versions récentes de Streamlit.
    st.link_button("Ouvrir dans ma messagerie", lien_mailto(objet, corps, destinataire),
                   icon=":material/mail:",
                   help="Ouvre ton logiciel de messagerie avec l'objet et le message déjà remplis.")


def texte_lettre(resultat: ResultatGeneration, nom: str) -> str:
    """Lettre en texte brut (formule d'appel, paragraphes, politesse, nom)."""
    morceaux = [resultat.formule_appel, *resultat.paragraphes, resultat.formule_politesse, nom]
    return "\n\n".join(m.strip() for m in morceaux if m and m.strip())


# ----------------------------------------------------------------------------
# Historique et CV
# ----------------------------------------------------------------------------


def formater_date(iso: str, avec_heure: bool = True) -> str:
    try:
        valeur = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso or ""
    jour = f"{valeur.day} {MOIS[valeur.month - 1]} {valeur.year}"
    return f"{jour} à {valeur:%H:%M}" if avec_heure else jour


def date_relative(iso: str, aujourd_hui: date | None = None) -> str:
    """« aujourd'hui », « hier », « il y a 5 jours », sinon « 3 oct. »."""
    try:
        jour = datetime.fromisoformat(iso).date()
    except (TypeError, ValueError):
        return ""
    ecart = ((aujourd_hui or date.today()) - jour).days
    if ecart == 0:
        return "aujourd'hui"
    if ecart == 1:
        return "hier"
    if 1 < ecart < 7:
        return f"il y a {ecart} jours"
    return date_courte(jour) + ("" if jour.year == (aujourd_hui or date.today()).year else f" {jour.year}")


def pluriel(nombre: int, mot: str, forme_plurielle: str = "") -> str:
    """« 1 candidature », « 3 candidatures »."""
    return f"{nombre} {mot if nombre <= 1 else (forme_plurielle or mot + 's')}"


def cle_css(identifiant: str) -> str:
    """Identifiant d'entrée transformé en clé utilisable comme classe CSS."""
    return hashlib.sha1(identifiant.encode("utf-8")).hexdigest()[:12]


def entree_historique(resultat: ResultatGeneration, production: ResultatCandidature,
                      dossier: Path, identifiant: str) -> dict:
    return {
        "id": identifiant,
        "date": datetime.now().isoformat(timespec="seconds"),
        "entreprise": resultat.entreprise or "Entreprise non précisée",
        "poste": resultat.poste,
        "dossier": stockage.chemin_relatif(dossier),
        "lettre_docx": stockage.chemin_relatif(production.chemin_lettre_docx),
        "cv_docx": stockage.chemin_relatif(production.chemin_cv_docx),
        "lettre_pdf": stockage.chemin_relatif(production.chemin_lettre_pdf),
        "cv_pdf": stockage.chemin_relatif(production.chemin_cv_pdf),
        "pages_lettre": production.lettre.pages if production.lettre else None,
        "pages_cv": production.cv.pages if production.cv else None,
        "methode_pdf": production.methode_pdf,
        "modele_ia": resultat.modele,
        "score": resultat.score,
        "email_objet": resultat.email_objet,
        "email_corps": resultat.email_corps,
        "langue": resultat.langue,
    }


def afficher_erreur_production(exc: Exception) -> None:
    if isinstance(exc, PermissionError):
        st.error(
            "Impossible d'écrire un des fichiers : il est sans doute ouvert dans un autre "
            f"programme (Word, lecteur PDF...). Ferme-le puis réessaie.\n\nDétail : {exc}"
        )
    else:
        st.error(f"Erreur pendant la création des fichiers : {exc}")


def entree_par_id(identifiant: str) -> dict | None:
    return next((e for e in stockage.charger_historique() if stockage.identifiant_entree(e) == identifiant), None)


def contexte_candidature(entree: dict) -> str:
    """Annonce mémorisée, ou à défaut le texte de la lettre envoyée."""
    return entree.get("annonce") or assistant.texte_docx(stockage.resoudre_chemin(entree.get("lettre_docx")))


@st.cache_data(show_spinner=False, max_entries=8)
def _blocs_cv_en_cache(chemin: str, signature: tuple[int, int]) -> list[BlocTexte]:
    return extraire_blocs(Path(chemin))


def blocs_cv(chemin: Path) -> list[BlocTexte]:
    """Blocs de texte d'un CV, sans relire le .docx à chaque affichage."""
    infos = chemin.stat()
    return _blocs_cv_en_cache(str(chemin), (infos.st_mtime_ns, infos.st_size))


def cv_de_entree(entree: dict) -> Path | None:
    """CV de référence utilisé pour une candidature (le principal par défaut)."""
    nom = entree.get("cv_reference")
    return next((cv.chemin for cv in stockage.lister_cvs() if cv.nom == nom), None) if nom else None


def texte_cv(chemin: Path | None) -> str:
    try:
        return texte_brut(blocs_cv(chemin or stockage.FICHIER_CV))
    except Exception:  # noqa: BLE001
        return ""


def lire_docx_importe(fichier) -> bytes | None:
    """Contenu d'un fichier importé s'il s'agit bien d'un .docx lisible."""
    contenu = fichier.getvalue()
    try:
        from docx import Document

        Document(io.BytesIO(contenu))
    except Exception:  # noqa: BLE001
        st.error("Ce fichier n'est pas un document Word (.docx) valide : il n'a pas été enregistré.")
        return None
    return contenu
