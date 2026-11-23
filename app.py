"""
App de génération de candidatures (lettre de motivation + CV adapté) pour
les alternances. Lancement : streamlit run app.py (ou double-clic sur
Lancer.bat sous Windows).
"""

from __future__ import annotations

import contextlib
import functools
import hashlib
import io
import os
import re
import subprocess
import sys
import time
from dataclasses import replace
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent / "src"))

import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).parent / ".env")

from version import VERSION  # noqa: E402

st.set_page_config(page_title="Candidatures alternance", page_icon="📄", layout="wide")


def _version_installee() -> str:
    """Version écrite sur le disque (src/version.py), relue à chaque affichage."""
    try:
        texte = (Path(__file__).parent / "src" / "version.py").read_text(encoding="utf-8")
    except OSError:
        return VERSION
    for ligne in texte.splitlines():
        if ligne.startswith("VERSION"):
            return ligne.split("=", 1)[1].strip().strip("\"'")
    return VERSION


# Fichiers mis à jour pendant que l'app tournait : les modules déjà chargés en
# mémoire sont encore les anciens, et les mélanger avec le nouveau code
# provoquerait des erreurs incompréhensibles. On demande simplement de relancer.
if _version_installee() != VERSION:
    st.title("🔄 Mise à jour installée")
    st.info(
        f"Une nouvelle version de l'app ({_version_installee()}) a été installée pendant qu'elle tournait "
        f"(version chargée : {VERSION}). Ferme l'app avec le bouton ci-dessous, puis relance-la avec ton "
        "raccourci habituel."
    )
    if st.button("🛑 Fermer l'app"):
        st.success("Application fermée. Tu peux fermer cet onglet et relancer l'app.")
        time.sleep(0.6)
        os._exit(0)
    st.stop()

import ai_client  # noqa: E402
import assistant  # noqa: E402
import stockage  # noqa: E402
import suivi  # noqa: E402
from ai_client import ErreurGeneration, generer_candidature  # noqa: E402
from candidature import ResultatCandidature, produire_candidature, verifier_cv_reference  # noqa: E402
from cv_editor import BlocTexte, extraire_blocs, texte_brut  # noqa: E402
from ia_commun import (  # noqa: E402
    CORPS_LETTRE_MAX,
    CORPS_LETTRE_MIN,
    LONGUEURS,
    TONS,
    ResultatGeneration,
    consignes_redaction,
)
from import_offre import ErreurImport, importer_offre  # noqa: E402
from mise_en_page import VERROU_PDFIUM, ResultatMiseEnPage, lignes_en_trop_estimees  # noqa: E402
from pdf_export import ErreurConversionPDF  # noqa: E402

MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_PDF = "application/pdf"
TAILLE_PAGE_HISTORIQUE = 15
md = assistant.echapper_markdown  # nom d'entreprise/poste affiché tel quel dans du markdown


# ----------------------------------------------------------------------------
# Petits utilitaires d'affichage
# ----------------------------------------------------------------------------


@functools.cache
def _streamlit_recent() -> bool:
    """Les boutons de téléchargement « différés » (fichier lu seulement au
    clic) existent depuis Streamlit 1.52 : avec une version plus ancienne, on
    lit le fichier tout de suite (plus lent si l'historique est long)."""
    try:
        from packaging.version import Version

        return Version(st.__version__) >= Version("1.52")
    except Exception:  # noqa: BLE001
        return False


def bouton_telechargement(chemin: Path | None, libelle: str, mime: str, cle: str) -> bool:
    """Bouton de téléchargement si le fichier existe encore sur le disque."""
    if not fichier_autorise(chemin):
        return False
    if _streamlit_recent():
        # Fichier lu seulement au clic, et pas de rechargement de la page
        # après le téléchargement (les retouches en cours restent affichées).
        st.download_button(libelle, data=lambda: chemin.read_bytes(), file_name=chemin.name,
                           mime=mime, key=cle, on_click="ignore")
    else:
        st.download_button(libelle, data=chemin.read_bytes(), file_name=chemin.name, mime=mime, key=cle)
    return True


@contextlib.contextmanager
def signaler_erreur_enregistrement():
    """Un fichier de données verrouillé (antivirus, OneDrive...) donne un
    message clair plutôt qu'une page d'erreur ; rien n'est perdu."""
    try:
        yield
    except OSError as exc:
        st.error(f"Enregistrement impossible pour le moment : {exc}")


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
    if st.button("📂 Ouvrir le dossier", key=cle, help=str(dossier)):
        try:
            ouvrir_dossier(dossier)
        except OSError as exc:
            st.warning(f"Impossible d'ouvrir le dossier automatiquement : {exc}")


@st.cache_data(show_spinner=False, max_entries=24)
def _apercu_png(chemin: str, date_modif: float, largeur: int) -> bytes | None:
    """Miniature de la 1re page d'un PDF (pour vérifier d'un coup d'œil)."""
    try:
        import pypdfium2 as pdfium
        from PIL import ImageDraw

        with VERROU_PDFIUM:
            document = pdfium.PdfDocument(chemin)
            try:
                page = document[0]
                echelle = 2 * largeur / page.get_size()[0]  # rendu 2x : net sur les écrans haute densité
                image = page.render(scale=echelle).to_pil().convert("RGB")
            finally:
                document.close()
        ImageDraw.Draw(image).rectangle([0, 0, image.width - 1, image.height - 1], outline=(200, 200, 200), width=2)
        tampon = io.BytesIO()
        image.save(tampon, format="PNG", optimize=True)
        return tampon.getvalue()
    except Exception:  # noqa: BLE001 - un aperçu raté ne doit rien bloquer
        return None


def apercu_pdf(chemin: Path | None, largeur: int = 420) -> None:
    if chemin is None or not chemin.is_file():
        return
    png = _apercu_png(str(chemin), chemin.stat().st_mtime, largeur)
    if png:
        st.image(png, width=largeur)


def ligne_statut_page(nom: str, resultat: ResultatMiseEnPage | None) -> None:
    if resultat is None or resultat.chemin_pdf is None:
        return
    if resultat.une_page:
        precision = "" if resultat.niveau == 0 else f" — mise en page resserrée : {resultat.description}"
        st.markdown(f"✅ **{nom}** : 1 page{precision}")
    else:
        st.warning(
            f"⚠️ **{nom}** : encore {resultat.pages} pages, même avec la mise en page la plus "
            f"resserrée (il dépasse d'environ {lignes_en_trop_estimees(resultat)} ligne(s)). "
            + ("Raccourcis un peu ton CV de référence (onglet « Mes CV »)."
               if nom == "CV" else "Raccourcis un paragraphe dans l'onglet « Retouches » ci-dessous.")
        )


def formater_date(iso: str, avec_heure: bool = True) -> str:
    try:
        valeur = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso or ""
    return valeur.strftime("%d/%m/%Y à %H:%M" if avec_heure else "%d/%m/%Y")


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
    # Pas de `key=` : st.link_button ne l'accepte pas avant les versions
    # récentes de Streamlit (et n'en a pas besoin pour un simple lien).
    st.link_button("📧 Ouvrir dans ma messagerie", lien_mailto(objet, corps, destinataire),
                   help="Ouvre ton logiciel de messagerie avec l'objet et le message déjà remplis.")


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
    }


def texte_lettre(resultat: ResultatGeneration, nom: str) -> str:
    """Lettre en texte brut (formule d'appel, paragraphes, politesse, nom)."""
    morceaux = [resultat.formule_appel, *resultat.paragraphes, resultat.formule_politesse, nom]
    return "\n\n".join(m.strip() for m in morceaux if m and m.strip())


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


# ----------------------------------------------------------------------------
# Fermeture propre de l'app
# ----------------------------------------------------------------------------

# Fermeture demandée lors d'un tour précédent : on affiche UNIQUEMENT ce
# message, puis on arrête le serveur. Un site ne peut pas forcer la fermeture
# d'un onglet que le navigateur a ouvert lui-même (restriction de sécurité de
# tous les navigateurs) : window.close() marche parfois, pas toujours —
# d'où le message explicite en secours.
if st.session_state.get("fermeture_demandee"):
    st.title("👋 Application fermée")
    st.success(
        "Le serveur est arrêté proprement (la fenêtre noire s'est refermée toute "
        "seule). Tu peux fermer cet onglet."
    )
    try:
        components.html("<script>window.close();</script>", height=0)
    except Exception:  # noqa: BLE001 - API dépréciée dans les versions récentes : l'arrêt passe avant
        pass
    time.sleep(0.6)
    os._exit(0)

# Sauvegarde automatique des données (une fois par jour, au premier affichage).
if "sauvegarde_auto" not in st.session_state:
    st.session_state["sauvegarde_auto"] = stockage.sauvegarde_automatique()

col_titre, col_fermer = st.columns([6, 1], vertical_alignment="center")
with col_titre:
    st.title("📄 Générateur de candidatures — alternance")
with col_fermer:
    if st.button("🛑 Fermer l'app", help="Ferme proprement l'application (et la fenêtre noire associée)."):
        st.session_state["fermeture_demandee"] = True
        st.rerun()

st.caption(
    f"Version {VERSION} · IA : **{ai_client.fournisseur_actif()}** ({ai_client.modele_configure()}) · "
    "après une mise à jour, ferme l'app et relance-la pour charger le nouveau code."
)

onglet_candidature, onglet_suivi, onglet_cv, onglet_profil = st.tabs(
    ["✉️ Nouvelle candidature", "🗂️ Mes candidatures", "📎 Mes CV", "👤 Mon profil"]
)

# ----------------------------------------------------------------------------
# Onglet : Nouvelle candidature
# ----------------------------------------------------------------------------


CHAMPS_OFFRE = ("f_url", "f_annonce", "f_entreprise", "f_poste", "f_adresse", "f_contact", "f_remarques")
# Champs propres à UNE offre : quand on passe à une autre offre, une valeur
# restée de la précédente (souvent dans les options repliées) ne doit pas se
# retrouver dans la nouvelle candidature.
CHAMPS_LIES_A_L_OFFRE = {"f_entreprise": "l'entreprise", "f_poste": "le poste", "f_adresse": "l'adresse",
                         "f_contact": "l'e-mail du recruteur", "f_url": "le lien"}
SEUIL_MEME_OFFRE = 0.6  # part de mots communs au-delà de laquelle une annonce modifiée reste « la même offre »


def _memoriser_offre(valeurs: dict[str, str], annonce: str, *, ajouter: bool) -> None:
    """Retient les valeurs utilisées pour l'offre en cours (import ou génération)."""
    precedentes = st.session_state.get("valeurs_offre_precedente", {}) if ajouter else {}
    for cle, valeur in valeurs.items():
        if valeur and valeur.strip():
            precedentes.setdefault(cle, set()).add(valeur)
    st.session_state["valeurs_offre_precedente"] = precedentes
    st.session_state["annonce_reference"] = annonce


def _oublier_offre_precedente(garder: frozenset[str] = frozenset()) -> list[str]:
    """Vide les champs qui contiennent encore une valeur de l'offre précédente
    (jamais ce que l'utilisateur a tapé pour l'offre en cours). Renvoie les
    libellés des champs vidés."""
    precedentes = st.session_state.get("valeurs_offre_precedente", {})
    vides = []
    for cle, libelle in CHAMPS_LIES_A_L_OFFRE.items():
        valeur = st.session_state.get(cle, "")
        if cle not in garder and valeur and valeur in precedentes.get(cle, ()):
            st.session_state[cle] = ""
            vides.append(libelle)
    st.session_state["valeurs_offre_precedente"] = {}
    st.session_state["annonce_reference"] = ""
    return vides


def _similarite(texte_a: str, texte_b: str) -> float:
    """Part de mots communs entre deux annonces (1 = mêmes mots)."""
    mots_a = set(re.findall(r"\w{3,}", texte_a.lower()))
    mots_b = set(re.findall(r"\w{3,}", texte_b.lower()))
    return len(mots_a & mots_b) / len(mots_a | mots_b) if mots_a and mots_b else 0.0


def annonce_modifiee() -> None:
    """Rappel du champ « Texte de l'annonce » : si l'utilisateur colle une
    AUTRE offre (et pas une simple correction), les champs restés de l'offre
    précédente sont vidés, et on le lui dit."""
    reference = st.session_state.get("annonce_reference") or ""
    nouvelle = st.session_state.get("f_annonce", "")
    if not reference or not nouvelle.strip() or _similarite(reference, nouvelle) >= SEUIL_MEME_OFFRE:
        return
    vides = _oublier_offre_precedente()
    if vides:
        st.session_state["import_message"] = (
            "info", f"Nouvelle annonce : {', '.join(vides)} de l'offre précédente ont été retirés du formulaire.")


def vider_formulaire() -> None:
    """Rappel du bouton « Nouvelle offre » : repart d'un formulaire vide (le
    ton, la longueur et le CV choisis sont gardés)."""
    for cle in CHAMPS_OFFRE:
        st.session_state[cle] = ""
    for cle in ("derniere_candidature", "valeurs_offre_precedente", "annonce_reference"):
        st.session_state.pop(cle, None)


def importer_depuis_lien() -> None:
    """Rappel du bouton « Importer » : préremplit le formulaire (avant que
    les champs ne soient affichés, comme l'exige Streamlit)."""
    url = st.session_state.get("f_url", "")
    try:
        offre = importer_offre(url)
    except ErreurImport as exc:
        st.session_state["import_message"] = ("error", str(exc))
        return
    except Exception as exc:  # noqa: BLE001 - page inattendue : on n'affiche jamais de plantage
        st.session_state["import_message"] = (
            "error", f"Impossible de lire cette page ({type(exc).__name__}) : colle plutôt le texte de l'annonce.")
        return
    # Nouvelle offre : ce qui reste de l'offre précédente est vidé, puis
    # rempli avec ce que la page indique (ce que tu as tapé toi-même pour
    # cette offre n'est jamais effacé).
    _oublier_offre_precedente(garder=frozenset({"f_url"}))
    st.session_state["f_annonce"] = offre.texte
    nouvelles = {"f_entreprise": offre.entreprise, "f_poste": offre.poste, "f_adresse": offre.adresse}
    for cle, valeur in nouvelles.items():
        if valeur:
            st.session_state[cle] = valeur
    _memoriser_offre({**nouvelles, "f_url": url}, offre.texte, ajouter=False)
    detail = "entreprise, poste et adresse remplis automatiquement" if offre.structuree else "vérifie le texte importé"
    st.session_state["import_message"] = ("success", f"Offre importée ({len(offre.texte)} caractères) : {detail}.")


def afficher_analyse(resultat: ResultatGeneration) -> None:
    if resultat.score is None:
        st.info("Pas d'analyse de correspondance pour cette candidature.")
        return
    col_score, col_detail = st.columns([1, 3])
    with col_score:
        st.metric("Correspondance estimée", f"{resultat.score} %")
        st.progress(resultat.score / 100)
    with col_detail:
        if resultat.points_forts:
            st.markdown("**Tes atouts pour cette offre**")
            st.markdown("\n".join(f"- ✅ {assistant.texte_ia_sur(p)}" for p in resultat.points_forts))
        if resultat.mots_cles_manquants:
            st.markdown("**Ce que l'offre demande et que ton CV ne montre pas**")
            st.markdown("\n".join(f"- ⚠️ {assistant.texte_ia_sur(m)}" for m in resultat.mots_cles_manquants))
            st.caption("À ajouter à ton CV seulement si c'est vrai — sinon, prépare-toi à en parler en entretien.")
    st.caption("Estimation de l'IA, à prendre comme un indicateur.")


def afficher_retouches(session: dict) -> None:
    resultat: ResultatGeneration = session["resultat"]
    production: ResultatCandidature = session["production"]
    eid: str = session["id"]
    # Propositions d'origine de l'IA, gardées telles quelles pendant toute la
    # session : un paragraphe vidé ou une modification du CV décochée reste
    # affiché (et récupérable) après « Mettre à jour les fichiers ».
    paragraphes_origine: list[str] = session.setdefault("paragraphes_origine", list(resultat.paragraphes))
    propositions_cv: dict[str, str] = session.setdefault("propositions_cv", dict(resultat.cv_adaptations))
    ignores_origine: dict[str, str] = session.setdefault("ignores_origine", dict(production.adaptations.ignores))
    st.caption(
        "Modifie librement le texte puis clique sur « Mettre à jour les fichiers » : la lettre et le CV "
        "sont régénérés (Word + PDF sur 1 page) sans rappeler l'IA. Le bouton 🔄 fait réécrire un seul "
        "paragraphe par l'IA. Un paragraphe laissé vide est retiré de la lettre."
    )
    # Valeurs initiales posées une seule fois dans l'état de session, puis
    # champs créés SANS `value=` : on peut ainsi les modifier par programme
    # (bouton 🔄) sans conflit avec Streamlit.
    initiales = {f"ed_objet_{eid}": resultat.objet, f"ed_appel_{eid}": resultat.formule_appel,
                 f"ed_politesse_{eid}": resultat.formule_politesse}
    initiales.update({f"ed_p{i}_{eid}": p for i, p in enumerate(paragraphes_origine)})
    for bid, texte in propositions_cv.items():
        initiales[f"ed_cv_on_{bid}_{eid}"] = bid not in ignores_origine
        initiales[f"ed_cv_txt_{bid}_{eid}"] = texte
    for cle_init, valeur in initiales.items():
        st.session_state.setdefault(cle_init, valeur)

    objet = st.text_input("Objet", key=f"ed_objet_{eid}")
    appel = st.text_input("Formule d'appel", key=f"ed_appel_{eid}")
    consigne = st.text_input("Consigne pour 🔄 (optionnel)", key=f"ed_consigne_{eid}",
                             placeholder="ex : plus court, plus concret, insiste sur Power BI...")
    paragraphes = []
    cles_paragraphes = [f"ed_p{i}_{eid}" for i in range(len(paragraphes_origine))]
    for i, cle in enumerate(cles_paragraphes):
        col_label, col_bouton = st.columns([5, 1], vertical_alignment="bottom")
        with col_label:
            st.markdown(f"**Paragraphe {i + 1}**")
        with col_bouton:
            # Bouton placé AVANT la zone de texte : on peut ainsi remplacer
            # son contenu dans ce même affichage.
            if st.button("🔄 Reformuler", key=f"ed_reformuler_{i}_{eid}", help="Réécriture de ce paragraphe par l'IA"):
                actuels = [st.session_state.get(c, "") for c in cles_paragraphes]
                try:
                    with st.spinner("Réécriture du paragraphe..."):
                        st.session_state[cle] = assistant.reecrire_paragraphe(
                            paragraphes=[p or "(paragraphe vide)" for p in actuels], index=i,
                            annonce=session.get("annonce", ""), cv_texte=texte_cv(session.get("cv_reference")),
                            consigne=consigne,
                        )
                except ErreurGeneration as exc:
                    st.error(str(exc))
        paragraphes.append(st.text_area(f"Paragraphe {i + 1}", height=130, key=cle, label_visibility="collapsed"))
    politesse = st.text_area("Formule de politesse", height=70, key=f"ed_politesse_{eid}")
    longueur = sum(len(p) for p in paragraphes)
    indication = "✅" if longueur <= CORPS_LETTRE_MAX + 150 else "⚠️ un peu long : la mise en page sera resserrée"
    st.caption(f"Corps de la lettre : {longueur} caractères (cible {CORPS_LETTRE_MIN}–{CORPS_LETTRE_MAX}) {indication}")

    st.markdown("**Modifications du CV**")
    blocs_avant = session["blocs_avant"]
    nouvelles_adaptations: dict[str, str] = {}
    visibles = 0
    for bid, texte in propositions_cv.items():
        if " ".join(texte.split()) == " ".join(blocs_avant.get(bid, "").split()):
            continue  # proposition identique au CV d'origine : rien à montrer
        visibles += 1
        with st.container(border=True):
            actif = st.checkbox(f"Appliquer la modification du bloc [{bid}]", key=f"ed_cv_on_{bid}_{eid}")
            raison = production.adaptations.ignores.get(bid)
            if raison is None and not actif and bid not in production.adaptations.appliques:
                raison = ignores_origine.get(bid)
            if raison:
                st.caption(f"⚠️ Non appliquée : {raison}.")
            st.caption("Avant :")
            st.text(blocs_avant.get(bid, "(bloc introuvable dans le CV)"))
            nouveau = st.text_area("Après :", height=90, key=f"ed_cv_txt_{bid}_{eid}")
            if actif:
                nouvelles_adaptations[bid] = nouveau
    if not visibles:
        st.info("Aucune adaptation proposée : le CV collait déjà bien à l'offre.")

    if st.button("♻️ Mettre à jour les fichiers avec mes retouches", type="primary", key=f"maj_{eid}"):
        conserves = [p for p in paragraphes if p.strip()]
        if not conserves:
            st.error("La lettre doit garder au moins un paragraphe.")
            return
        modifie = replace(
            resultat,
            objet=objet,
            formule_appel=appel,
            paragraphes=conserves,
            formule_politesse=politesse,
            cv_adaptations=nouvelles_adaptations,
        )
        try:
            with st.spinner("Régénération des fichiers et mise en page sur 1 page..."):
                nouvelle_production = produire_candidature(
                    resultat=modifie, profil=stockage.charger_profil(),
                    entreprise_adresse=session["entreprise_adresse"], dossier=session["dossier"],
                    cv_reference=session.get("cv_reference"),
                )
        except Exception as exc:  # noqa: BLE001
            afficher_erreur_production(exc)
            return
        maj = entree_historique(modifie, nouvelle_production, session["dossier"], eid)
        maj.pop("date")  # garder la date de création d'origine
        try:
            stockage.mettre_a_jour_historique(eid, maj)
        except OSError as exc:
            st.warning(f"Fichiers mis à jour, mais l'historique n'a pas pu être enregistré : {exc}")
        session["resultat"] = modifie
        session["production"] = nouvelle_production
        st.toast("Fichiers mis à jour ✅")
        st.rerun()


def afficher_resultat() -> None:
    session = st.session_state.get("derniere_candidature")
    if not session:
        return
    resultat: ResultatGeneration = session["resultat"]
    production: ResultatCandidature = session["production"]
    dossier: Path = session["dossier"]
    eid: str = session["id"]

    st.divider()
    if production.erreurs_pdf:
        st.warning(
            "Les fichiers Word sont prêts, mais l'export PDF a échoué : "
            "tu peux télécharger les .docx et les exporter en PDF toi-même."
        )
        with st.expander("Détail de l'erreur PDF"):
            st.text("\n\n".join(production.erreurs_pdf))
    else:
        try:
            dossier_affiche = dossier.relative_to(stockage.RACINE)
        except ValueError:
            dossier_affiche = dossier
        st.success(f"Candidature prête pour **{md(resultat.entreprise)}** dans `{dossier_affiche}`")

    ligne_statut_page("Lettre", production.lettre)
    ligne_statut_page("CV", production.cv)
    details = [f"PDF : {production.methode_pdf}" if production.methode_pdf else "",
               f"IA : {resultat.modele}" if resultat.modele else ""]
    st.caption(" · ".join(d for d in details if d))

    precedentes = stockage.candidatures_precedentes(resultat.entreprise, sauf=eid)
    if precedentes:
        dates = ", ".join(formater_date(e.get("date", ""), avec_heure=False) for e in precedentes[:5])
        st.info(f"ℹ️ Tu as déjà généré {len(precedentes)} candidature(s) pour **{md(resultat.entreprise)}** ({dates}).")

    col_lettre, col_cv = st.columns(2)
    with col_lettre:
        st.markdown("**Lettre de motivation**")
        with st.container(horizontal=True):
            bouton_telechargement(production.chemin_lettre_pdf, "⬇️ PDF", MIME_PDF, f"dl_l_pdf_{eid}")
            bouton_telechargement(production.chemin_lettre_docx, "⬇️ Word", MIME_DOCX, f"dl_l_docx_{eid}")
        apercu_pdf(production.chemin_lettre_pdf)
    with col_cv:
        st.markdown("**CV adapté**")
        with st.container(horizontal=True):
            bouton_telechargement(production.chemin_cv_pdf, "⬇️ PDF", MIME_PDF, f"dl_c_pdf_{eid}")
            bouton_telechargement(production.chemin_cv_docx, "⬇️ Word", MIME_DOCX, f"dl_c_docx_{eid}")
        apercu_pdf(production.chemin_cv_pdf)

    entree = entree_par_id(eid) or {}
    envoyee = False
    with st.container(horizontal=True, vertical_alignment="center"):
        bouton_ouvrir_dossier(dossier, f"ouvrir_{eid}")
        if suivi.statut(entree) in suivi.STATUTS_ENVOYES:
            st.markdown(f"{suivi.badge(suivi.statut(entree))} le {formater_date(entree.get('date_envoi', ''), False)}")
        else:
            envoyee = st.button("📤 Je l'ai envoyée", key=f"envoyee_{eid}",
                                help="Facultatif : note la date d'envoi pour être prévenu quand il sera temps "
                                     "de relancer.")
    if envoyee:
        with signaler_erreur_enregistrement():
            suivi.changer_statut(eid, "envoyee")
            st.toast("Candidature marquée comme envoyée 📤")
            st.rerun()

    sous_onglets = st.tabs(["🎯 Analyse de l'offre", "✉️ E-mail et texte à copier", "✏️ Retouches"])
    with sous_onglets[0]:
        afficher_analyse(resultat)
    with sous_onglets[1]:
        if resultat.email_corps:
            st.markdown("**E-mail d'accompagnement**")
            st.caption("Pense à joindre les deux PDF avant d'envoyer.")
            bloc_mail(resultat.email_objet, resultat.email_corps, session.get("contact", ""))
        else:
            st.info("Pas d'e-mail généré pour cette candidature.")
        st.markdown("**Texte de la lettre**")
        st.caption("Pour les sites qui demandent de coller la lettre dans un champ plutôt que de joindre le PDF.")
        st.code(texte_lettre(resultat, stockage.charger_profil().get("nom", "")), language=None, wrap_lines=True)
    with sous_onglets[2]:
        afficher_retouches(session)


with onglet_candidature:
    profil = stockage.charger_profil()
    cvs = stockage.lister_cvs()
    if not cvs:
        st.warning("Importe d'abord ton CV dans l'onglet « 📎 Mes CV ».")
    elif not ai_client.cle_api_presente():
        if ai_client.fournisseur_actif() == "gemini":
            st.warning(
                "Aucune clé API Gemini configurée. Crée une clé **gratuite** sur "
                "aistudio.google.com/apikey, copie .env.example vers .env, ajoute-la "
                "(GEMINI_API_KEY=...) puis relance l'app."
            )
        else:
            st.warning(
                f"Aucune clé API {ai_client.fournisseur_actif()} configurée. Copie .env.example "
                "vers .env, ajoute ta clé puis relance l'app."
            )
    else:
        a_relancer = suivi.candidatures_a_relancer(stockage.charger_historique())
        if a_relancer:
            st.info(f"🔔 {len(a_relancer)} candidature(s) à relancer : voir l'onglet « 🗂️ Mes candidatures ».")
        manquants = stockage.profil_incomplet(profil)
        if manquants:
            st.info(
                f"ℹ️ Profil incomplet ({', '.join(manquants)}) : l'en-tête de la lettre le sera aussi. "
                "Complète-le dans l'onglet « 👤 Mon profil »."
            )

        col_url, col_import = st.columns([5, 1], vertical_alignment="bottom")
        with col_url:
            st.text_input("🔗 Lien de l'offre (optionnel)", key="f_url",
                          placeholder="https://... (Welcome to the Jungle, HelloWork, site carrière...)")
        with col_import:
            st.button("📥 Importer", on_click=importer_depuis_lien, width="stretch",
                      help="Récupère le texte de l'offre et remplit le formulaire automatiquement.")
        message_import = st.session_state.pop("import_message", None)
        if message_import:
            {"success": st.success, "info": st.info}.get(message_import[0], st.warning)(message_import[1])

        col_a, col_b = st.columns(2)
        with col_a:
            entreprise_saisie = st.text_input("Nom de l'entreprise (optionnel)", key="f_entreprise")
        with col_b:
            poste_saisi = st.text_input("Intitulé du poste (optionnel)", key="f_poste")

        if entreprise_saisie.strip():
            deja = stockage.candidatures_precedentes(entreprise_saisie)
            if deja:
                st.caption(
                    f"ℹ️ Déjà {len(deja)} candidature(s) générée(s) pour cette entreprise "
                    f"(dernière le {formater_date(deja[0].get('date', ''))})."
                )

        annonce = st.text_area("Texte de l'annonce", height=260, key="f_annonce", on_change=annonce_modifiee,
                               placeholder="Colle ici le texte complet de l'offre (missions, profil recherché...)")

        noms_cvs = [cv.nom for cv in cvs]
        cv_choisi = cvs[0]
        if len(cvs) > 1:
            nom_choisi = st.selectbox("CV de référence", noms_cvs, key="f_cv")
            cv_choisi = cvs[noms_cvs.index(nom_choisi)] if nom_choisi in noms_cvs else cvs[0]

        with st.expander("⚙️ Options : adresse, e-mail du recruteur, ton, longueur, remarques"):
            col_c, col_d = st.columns(2)
            with col_c:
                entreprise_adresse = st.text_input(
                    "Adresse de l'entreprise", key="f_adresse",
                    help="Ex : « 5 place de la Pyramide, 92800 Puteaux » (présentée sur deux lignes dans la lettre).",
                )
                ton = st.selectbox("Ton de la lettre", list(TONS), key="f_ton")
            with col_d:
                contact = st.text_input("E-mail du recruteur", key="f_contact",
                                        help="Facultatif : prérempli dans l'e-mail d'accompagnement et les relances.")
                longueur = st.selectbox("Longueur de la lettre", list(LONGUEURS), key="f_longueur")
            remarques = st.text_input("Remarques pour l'IA", key="f_remarques",
                                      help="Ex : « mets plus en avant mes compétences en Python et SQL »")

        with st.container(horizontal=True):
            generer = st.button("✨ Générer la candidature (PDF direct)", type="primary")
            st.button("🧹 Nouvelle offre", on_click=vider_formulaire,
                      help="Vide le formulaire (lien, annonce, entreprise, poste, adresse, e-mail du recruteur, "
                           "remarques) pour passer à l'offre suivante. Ton, longueur et CV choisis sont gardés.")
        if generer:
            with st.status("Génération de ta candidature...", expanded=True) as etat:
                try:
                    blocs = extraire_blocs(cv_choisi.chemin)
                    etat.write(f"✍️ Rédaction par l'IA ({ai_client.modele_configure()})...")
                    resultat = generer_candidature(
                        blocs_cv=blocs,
                        texte_annonce=annonce,
                        contexte_academique=profil.get("contexte_academique", ""),
                        entreprise_indiquee=entreprise_saisie,
                        poste_indique=poste_saisi,
                        consignes_supplementaires=consignes_redaction(ton, longueur, remarques),
                    )
                    etat.write(f"✅ Contenu rédigé ({resultat.modele})")
                    if not resultat.entreprise:
                        resultat.entreprise = "Entreprise"
                    # Sous-dossier propre à chaque génération (poste + horodatage) :
                    # sans ça, deux candidatures pour la même entreprise
                    # écraseraient silencieusement les mêmes fichiers.
                    horodatage = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                    poste_slug = stockage.slugifier_nom_fichier(resultat.poste, stockage.LONGUEUR_MAX_SLUG_POSTE)
                    sous_dossier = f"{poste_slug}_{horodatage}" if poste_slug else horodatage
                    dossier = stockage.dossier_candidature(resultat.entreprise, sous_dossier=sous_dossier)
                    identifiant = f"{horodatage}|{stockage.slugifier_nom_fichier(resultat.entreprise)}"
                    production = produire_candidature(
                        resultat=resultat, profil=profil, entreprise_adresse=entreprise_adresse,
                        dossier=dossier, cv_reference=cv_choisi.chemin, progression=etat.write,
                    )
                except ErreurGeneration as exc:
                    etat.update(label="La génération a échoué", state="error", expanded=True)
                    st.error(str(exc))
                except Exception as exc:  # noqa: BLE001
                    etat.update(label="La création des fichiers a échoué", state="error", expanded=True)
                    afficher_erreur_production(exc)
                else:
                    entree = entree_historique(resultat, production, dossier, identifiant)
                    entree.update({
                        "annonce": annonce.strip(),
                        "url_offre": st.session_state.get("f_url", "").strip(),
                        "contact": contact.strip(),
                        "cv_reference": cv_choisi.nom,
                    })
                    try:
                        stockage.ajouter_historique(entree)
                    except OSError as exc:
                        st.warning(f"Candidature créée, mais pas ajoutée à « Mes candidatures » : {exc}")
                    _memoriser_offre({"f_entreprise": entreprise_saisie, "f_poste": poste_saisi,
                                      "f_adresse": entreprise_adresse, "f_contact": contact,
                                      "f_url": st.session_state.get("f_url", "")}, annonce, ajouter=True)
                    st.session_state["derniere_candidature"] = {
                        "id": identifiant,
                        "resultat": resultat,
                        "production": production,
                        "dossier": dossier,
                        "entreprise_adresse": entreprise_adresse,
                        "contact": contact.strip(),
                        "annonce": annonce.strip(),
                        "cv_reference": cv_choisi.chemin,
                        "blocs_avant": {b.id: b.texte for b in blocs},
                    }
                    etat.update(label="Candidature prête ✅", state="complete", expanded=False)

        afficher_resultat()

# ----------------------------------------------------------------------------
# Onglet : Mes candidatures (historique + suivi facultatif)
# ----------------------------------------------------------------------------


def changer_statut_depuis_liste(identifiant: str, cle_widget: str) -> None:
    libelles = {suivi.libelle(c): c for c in suivi.STATUTS}
    try:
        suivi.changer_statut(identifiant, libelles.get(st.session_state[cle_widget], ""))
    except OSError as exc:
        st.session_state["erreur_suivi"] = f"Statut non enregistré : {exc}"


def afficher_relances(relances: list[suivi.Relance], profil: dict) -> None:
    with st.expander(f"🔔 À relancer ({len(relances)})", expanded=True):
        st.caption(
            f"Candidatures envoyées sans réponse depuis plus de {suivi.DELAI_RELANCE_JOURS} jours "
            f"(ou {suivi.DELAI_DEUXIEME_RELANCE_JOURS} jours après une première relance)."
        )
        for relance in relances:
            entree = relance.entree
            eid = stockage.identifiant_entree(entree)
            cle_mail = f"relance_mail_{eid}"
            with st.container(border=True):
                st.markdown(
                    f"**{md(entree.get('entreprise', '?'))}** — {md(entree.get('poste') or 'poste non précisé')} · "
                    f"envoyée il y a {relance.jours} jours" + (" · déjà relancée une fois" if relance.deuxieme else "")
                )
                with st.container(horizontal=True):
                    rediger = st.button("✉️ Rédiger la relance", key=f"rel_gen_{eid}")
                    relancee = st.button("✔️ Marquer comme relancée", key=f"rel_ok_{eid}")
                    ignorer = st.button("🙈 Ignorer", key=f"rel_ign_{eid}",
                                        help="Ne plus proposer de relance pour celle-ci.")
                if relancee or ignorer:
                    with signaler_erreur_enregistrement():
                        if relancee:
                            suivi.changer_statut(eid, "relancee")
                        else:
                            stockage.mettre_a_jour_historique(eid, {"relance_ignoree": True})
                        st.session_state.pop(cle_mail, None)
                        st.rerun()
                if rediger:
                    try:
                        with st.spinner("Rédaction de la relance..."):
                            st.session_state[cle_mail] = assistant.rediger_relance(
                                entreprise=entree.get("entreprise", ""), poste=entree.get("poste", ""),
                                jours=relance.jours, deuxieme=relance.deuxieme,
                                contexte=contexte_candidature(entree), profil=profil,
                            )
                    except ErreurGeneration as exc:
                        st.error(str(exc))
                mail = st.session_state.get(cle_mail)
                if mail:
                    bloc_mail(mail.objet, mail.corps, entree.get("contact", ""))


def afficher_tableau_de_bord(historique: list[dict]) -> None:
    stats = suivi.statistiques(historique)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Candidatures", stats.total)
    if any(suivi.statut(e) for e in historique):  # suivi facultatif : ces chiffres seulement s'il est utilisé
        c2.metric("Envoyées", stats.envoyees, help="Statut « Envoyée » ou suivant.")
        taux = f"{stats.taux_reponse:.0%}" if stats.taux_reponse is not None else "—"
        c3.metric("Réponses", stats.reponses, help=f"Taux de réponse : {taux}")
        c4.metric("Entretiens", stats.entretiens)
    with st.expander("📈 Activité des 12 dernières semaines"):
        import pandas as pd

        donnees = pd.DataFrame(
            {"Candidatures": list(stats.par_semaine.values())},
            index=[datetime.fromisoformat(s).strftime("%d/%m") for s in stats.par_semaine],
        )
        st.bar_chart(donnees, height=220)
        if stats.envoyees:
            repartition = ", ".join(f"{suivi.libelle(c)} : {n}" for c, n in stats.par_statut.most_common() if n)
            st.caption(repartition)
        else:
            st.caption("Astuce : indique le statut de tes candidatures (facultatif) pour suivre ton taux de réponse.")


def afficher_carte(entree: dict, rang: int, profil: dict) -> None:
    eid = stockage.identifiant_entree(entree)
    cle = f"{rang}_{eid}"  # rang inclus : clés uniques même si deux anciennes entrées se ressemblent
    cle_statut = f"h_statut_{cle}"
    with st.container(border=True):
        col_titre, col_statut, col_suppr = st.columns([6, 2, 1], vertical_alignment="center")
        with col_titre:
            badges = []
            if suivi.statut(entree):  # le statut par défaut « Générée » n'a pas besoin de badge
                badges.append(suivi.badge(suivi.statut(entree)))
            if isinstance(entree.get("score"), int):
                badges.append(f":blue-badge[🎯 {entree['score']} %]")
            st.markdown(f"**{md(entree.get('entreprise', '?'))}** — {md(entree.get('poste') or 'poste non précisé')}"
                        f" {' '.join(badges)}")
            infos = [formater_date(entree.get("date", ""))]
            if entree.get("date_envoi"):
                infos.append(f"envoyée le {formater_date(entree['date_envoi'], False)}")
            if entree.get("methode_pdf"):
                infos.append(f"PDF via {entree['methode_pdf']}")
            if entree.get("cv_reference"):
                infos.append(f"CV : {entree['cv_reference']}")
            st.caption(" · ".join(infos))
        with col_statut:
            options = [suivi.libelle(c) for c in suivi.STATUTS]
            # Valeur posée AVANT la création du champ (et pas d'`index=`) : le
            # statut affiché suit toujours le statut enregistré, même s'il a
            # été changé ailleurs (relance, « Je l'ai envoyée »...).
            libelle_actuel = suivi.libelle(suivi.statut(entree))
            if st.session_state.get(cle_statut) != libelle_actuel:
                st.session_state[cle_statut] = libelle_actuel
            st.selectbox("Statut", options, key=cle_statut, label_visibility="collapsed",
                         on_change=changer_statut_depuis_liste, args=(eid, cle_statut),
                         help="Facultatif : suis l'avancement de ta candidature.")
        with col_suppr:
            with st.popover("🗑️", help="Retirer de la liste"):
                st.caption("Retirer cette candidature de la liste ? Les fichiers restent dans outputs/.")
                if st.button("Oui, retirer", key=f"h_suppr_{cle}"):
                    with signaler_erreur_enregistrement():
                        stockage.supprimer_historique(eid)
                        st.rerun()

        fichiers = [
            ("Lettre PDF", stockage.resoudre_chemin(entree.get("lettre_pdf")), MIME_PDF, "l_pdf"),
            ("Lettre Word", stockage.resoudre_chemin(entree.get("lettre_docx") or entree.get("lettre")), MIME_DOCX,
             "l_docx"),
            ("CV PDF", stockage.resoudre_chemin(entree.get("cv_pdf")), MIME_PDF, "c_pdf"),
            ("CV Word", stockage.resoudre_chemin(entree.get("cv_docx") or entree.get("cv")), MIME_DOCX, "c_docx"),
        ]
        dossier_entree = stockage.resoudre_chemin(entree.get("dossier"))
        if dossier_entree is None and fichiers[1][1] is not None:
            dossier_entree = fichiers[1][1].parent
        presents = 0
        with st.container(horizontal=True, vertical_alignment="center"):
            for libelle_fichier, chemin, mime, suffixe in fichiers:
                presents += bouton_telechargement(chemin, f"⬇️ {libelle_fichier}", mime, f"h_{suffixe}_{cle}")
            bouton_ouvrir_dossier(dossier_entree, f"h_ouvrir_{cle}")
            preparer = st.button("🎤 Préparer l'entretien", key=f"h_entretien_{cle}",
                                 help="Fiche avec pitch, questions probables et questions à poser (IA).")
        if preparer:
            titre = f"Entretien — {entree.get('entreprise', '')} ({entree.get('poste') or 'alternance'})"
            try:
                with st.spinner("Préparation de la fiche d'entretien..."):
                    fiche = assistant.preparer_entretien(
                        entreprise=entree.get("entreprise", ""), poste=entree.get("poste", ""),
                        contexte=contexte_candidature(entree), cv_texte=texte_cv(cv_de_entree(entree)),
                    )
                modifications = {"fiche_entretien": fiche.en_markdown(titre)}
                if dossier_autorise(dossier_entree):
                    chemin = assistant.enregistrer_fiche_docx(
                        fiche, titre, dossier_entree / "Preparation_entretien.docx"
                    )
                    modifications["fiche_entretien_docx"] = stockage.chemin_relatif(chemin)
                stockage.mettre_a_jour_historique(eid, modifications)
                entree.update(modifications)
            except (ErreurGeneration, OSError) as exc:
                st.error(str(exc))
        if not presents:
            st.caption("Fichiers introuvables (déplacés ou supprimés).")

        if entree.get("fiche_entretien"):
            with st.expander("🎤 Fiche de préparation d'entretien"):
                st.markdown(entree["fiche_entretien"])
                bouton_telechargement(stockage.resoudre_chemin(entree.get("fiche_entretien_docx")),
                                      "⬇️ Version Word imprimable", MIME_DOCX, f"h_fiche_{cle}")
        if entree.get("email_corps"):
            with st.expander("✉️ E-mail d'accompagnement"):
                bloc_mail(entree.get("email_objet", ""), entree["email_corps"], entree.get("contact", ""))
        with st.expander("📝 Notes et contact (facultatif)"):
            with st.form(f"h_notes_form_{cle}", border=False):
                n1, n2 = st.columns(2)
                with n1:
                    contact = st.text_input("E-mail du recruteur", value=entree.get("contact", ""))
                    envoi_actuel = suivi.date_envoi(entree)
                    date_choisie = st.date_input("Date d'envoi", value=envoi_actuel, format="DD/MM/YYYY")
                with n2:
                    url = st.text_input("Lien de l'offre", value=entree.get("url_offre", ""))
                    notes = st.text_area("Notes", value=entree.get("notes", ""), height=90,
                                         placeholder="ex : contact RH, date d'entretien, impressions...")
                if st.form_submit_button("💾 Enregistrer"):
                    modifications = {
                        "contact": contact.strip(),
                        "url_offre": url.strip(),
                        "notes": notes.strip(),
                        "date_envoi": date_choisie.isoformat() if isinstance(date_choisie, date) else "",
                    }
                    if modifications["date_envoi"] and not suivi.statut(entree):
                        modifications["statut"] = "envoyee"  # une date d'envoi = candidature envoyée
                    with signaler_erreur_enregistrement():
                        stockage.mettre_a_jour_historique(eid, modifications)
                        st.toast("Notes enregistrées 💾")
                        st.rerun()
            if entree.get("url_offre", "").startswith(("http://", "https://")):
                st.link_button("🔗 Voir l'offre", entree["url_offre"])


with onglet_suivi:
    erreur_suivi = st.session_state.pop("erreur_suivi", None)
    if erreur_suivi:
        st.error(erreur_suivi)
    historique_complet = stockage.charger_historique()
    profil = stockage.charger_profil()
    if not historique_complet:
        st.info("Aucune candidature générée avec l'app pour le moment.")
    else:
        afficher_tableau_de_bord(historique_complet)
        relances = suivi.candidatures_a_relancer(historique_complet)
        if relances:
            afficher_relances(relances, profil)

        f1, f2, f3 = st.columns([3, 3, 2])
        with f1:
            recherche = st.text_input("🔎 Rechercher (entreprise ou poste)", key="h_recherche")
        with f2:
            filtre_statuts = st.multiselect("Statut", [suivi.libelle(c) for c in suivi.STATUTS], key="h_filtre",
                                            placeholder="Tous les statuts")
        with f3:
            tri = st.selectbox("Trier par", ["Plus récentes", "Plus anciennes", "Entreprise (A→Z)",
                                             "Meilleure correspondance"], key="h_tri")
        historique = historique_complet
        if recherche.strip():
            cible = stockage.normaliser_nom(recherche)
            historique = [e for e in historique
                          if cible in stockage.normaliser_nom(f"{e.get('entreprise', '')} {e.get('poste', '')}")]
        if filtre_statuts:
            historique = [e for e in historique if suivi.libelle(suivi.statut(e)) in filtre_statuts]
        if tri == "Plus anciennes":
            historique = list(reversed(historique))
        elif tri == "Entreprise (A→Z)":
            historique = sorted(historique, key=lambda e: stockage.normaliser_nom(e.get("entreprise", "")))
        elif tri == "Meilleure correspondance":
            historique = sorted(historique, key=lambda e: -(e.get("score") if isinstance(e.get("score"), int) else -1))

        nb_affiches = st.session_state.get("h_nb_affiches", TAILLE_PAGE_HISTORIQUE)
        col_nombre, col_export = st.columns([3, 1], vertical_alignment="center")
        col_nombre.caption(f"{len(historique)} candidature(s)")
        with col_export:
            liste_exportee = historique  # la liste telle qu'affichée (recherche, filtre et tri compris)
            st.download_button(
                "⬇️ Exporter pour Excel", data=suivi.exporter_csv(liste_exportee),
                file_name=f"candidatures_{date.today().isoformat()}.csv", mime="text/csv",
                help="Fichier .csv qui s'ouvre dans Excel ou LibreOffice Calc (recherche et filtre appliqués).",
                key="h_export_csv", width="stretch",
            )
        for rang, entree in enumerate(historique[:nb_affiches]):
            afficher_carte(entree, rang, profil)
        if len(historique) > nb_affiches:
            if st.button(f"Afficher {min(TAILLE_PAGE_HISTORIQUE, len(historique) - nb_affiches)} de plus"):
                st.session_state["h_nb_affiches"] = nb_affiches + TAILLE_PAGE_HISTORIQUE
                st.rerun()

# ----------------------------------------------------------------------------
# Onglet : Mes CV
# ----------------------------------------------------------------------------


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


with onglet_cv:
    st.caption(
        "Tes CV au format Word (.docx) restent la référence permanente : chaque candidature part d'une "
        "copie, ils ne sont jamais modifiés."
    )
    st.subheader("CV principal")
    if stockage.cv_present():
        profil_actuel = stockage.charger_profil()
        nom_original = profil_actuel.get("_cv_nom_original", "cv_original.docx")
        importe_le = formater_date(profil_actuel.get("_cv_importe_le", ""))
        st.success(f"CV enregistré : **{md(nom_original)}**" + (f" (importé le {importe_le})." if importe_le else "."))
    else:
        st.warning("Aucun CV importé pour le moment.")
    fichier = st.file_uploader("Importer / remplacer le CV principal (.docx)", type=["docx"], key="cv_principal")
    if fichier is not None:
        signature = hashlib.sha256(fichier.getvalue()).hexdigest()  # chaque fichier n'est traité qu'une fois
        if st.session_state.get("cv_importe") != signature:
            contenu = lire_docx_importe(fichier)
            if contenu is not None:
                with signaler_erreur_enregistrement():
                    stockage.enregistrer_cv(contenu, fichier.name)
                    st.session_state["cv_importe"] = signature
                    st.session_state.pop("verif_cv", None)
                    st.success(f"CV « {fichier.name} » enregistré comme CV principal.")

    with st.expander("➕ CV supplémentaires (facultatif) — ex : un CV « Data » et un CV « Marketing »"):
        st.caption("Au moment de générer une candidature, tu choisiras le CV de départ le plus adapté.")
        with st.form("form_cv_supp", clear_on_submit=True):
            nom_supp = st.text_input("Nom du CV", placeholder="ex : CV Marketing")
            fichier_supp = st.file_uploader("Fichier .docx", type=["docx"])
            if st.form_submit_button("Ajouter ce CV"):
                if not fichier_supp or not stockage.nom_cv_valide(nom_supp):
                    st.error("Indique un nom et choisis un fichier .docx.")
                else:
                    contenu = lire_docx_importe(fichier_supp)
                    if contenu is not None:
                        with signaler_erreur_enregistrement():
                            stockage.ajouter_cv(contenu, nom_supp)
                            st.success(f"CV « {stockage.nom_cv_valide(nom_supp)} » ajouté.")
        for cv in stockage.lister_cvs():
            if cv.principal:
                continue
            c1, c2 = st.columns([5, 1], vertical_alignment="center")
            c1.markdown(f"📄 {md(cv.nom)}")
            with c2.popover("🗑️ Supprimer", help="Supprimer ce CV supplémentaire"):
                st.caption("Supprimer ce CV ? (Une copie reste dans la sauvegarde automatique du jour.)")
                if st.button("Oui, supprimer", key=f"cv_suppr_{cv.nom}"):
                    with signaler_erreur_enregistrement():
                        stockage.supprimer_cv(cv.nom)
                        st.rerun()

    cvs = stockage.lister_cvs()
    if cvs:
        st.subheader("Vérifier un CV")
        noms = [cv.nom for cv in cvs]
        nom_verif = st.selectbox("CV à vérifier", noms, key="cv_verif_choix") if len(cvs) > 1 else noms[0]
        cv_verif = cvs[noms.index(nom_verif)] if nom_verif in noms else cvs[0]
        try:
            blocs = blocs_cv(cv_verif.chemin)
        except Exception:  # noqa: BLE001 - CV supprimé ou illisible entre-temps
            blocs = []
        with st.expander(f"Voir le texte détecté ({len(blocs)} blocs)"):
            if not blocs:
                st.warning(
                    "Aucun texte détecté. Le CV utilise peut-être des zones de texte ou des images plutôt "
                    "que des paragraphes Word standards (voir la limite connue dans le README)."
                )
            st.caption("🔒 = bloc jamais modifié par l'IA (coordonnées, liens, titres de section).")
            for b in blocs:
                st.text(f"{'' if b.modifiable else '🔒 '}[{b.id}] {b.texte}")
        st.caption(
            "Chaque CV généré est automatiquement ajusté pour tenir sur une seule page. Ce test vérifie le CV "
            "tel quel et mémorise le réglage pour accélérer les prochaines candidatures."
        )
        if st.button("🧪 Vérifier que ce CV tient sur une page"):
            try:
                with st.spinner("Conversion en PDF et vérification..."):
                    st.session_state["verif_cv"] = (
                        cv_verif.nom,
                        verifier_cv_reference(stockage.DOSSIER_OUTPUTS / "_verification_cv",
                                              cv_reference=cv_verif.chemin),
                    )
            except ErreurConversionPDF as exc:
                st.error(str(exc))
        verif_session = st.session_state.get("verif_cv")
        if verif_session and verif_session[0] == cv_verif.nom:
            verif = verif_session[1]
            if verif.une_page and verif.niveau == 0:
                st.success(f"✅ Ce CV tient sur une page tel quel (PDF via {verif.methode}).")
            elif verif.une_page:
                st.info(
                    f"✅ Ce CV tient sur une page avec un léger resserrement ({verif.description}), "
                    f"appliqué automatiquement à chaque candidature (PDF via {verif.methode})."
                )
            else:
                st.warning(
                    f"⚠️ Même resserré au maximum, ce CV fait {verif.pages} pages (environ "
                    f"{lignes_en_trop_estimees(verif)} ligne(s) de trop) : raccourcis-le un peu."
                )
            apercu_pdf(verif.chemin_pdf, largeur=480)

    st.info(
        "⚠️ Limite connue : seuls les paragraphes et tableaux Word « standards » sont détectés. Le texte "
        "dans des zones de texte, images ou SmartArt n'est pas modifié. Relis toujours le CV généré."
    )

# ----------------------------------------------------------------------------
# Onglet : Mon profil
# ----------------------------------------------------------------------------
with onglet_profil:
    st.caption(
        "Ces informations servent d'en-tête à chaque lettre de motivation générée. "
        "Elles restent enregistrées en local dans data/profil.json."
    )
    profil = stockage.charger_profil()

    with st.form("form_profil"):
        col1, col2 = st.columns(2)
        with col1:
            nom = st.text_input("Nom complet", value=profil.get("nom", ""))
            adresse = st.text_input("Adresse", value=profil.get("adresse", ""))
            code_postal = st.text_input("Code postal", value=profil.get("code_postal", ""))
            ville = st.text_input("Ville", value=profil.get("ville", ""))
        with col2:
            telephone = st.text_input("Téléphone", value=profil.get("telephone", ""))
            email = st.text_input("Email", value=profil.get("email", ""))
            linkedin = st.text_input("LinkedIn (optionnel)", value=profil.get("linkedin", ""))
            github = st.text_input("GitHub (optionnel)", value=profil.get("github", ""))

        contexte_academique = st.text_area(
            "Contexte académique / recherche actuelle",
            value=profil.get("contexte_academique", ""),
            help="Utilisé par l'IA pour situer ta candidature (formation, rythme, type de contrat recherché...).",
            height=100,
        )

        if st.form_submit_button("💾 Enregistrer mon profil"):
            with signaler_erreur_enregistrement():
                stockage.enregistrer_profil({
                    **profil,
                    "nom": nom.strip(),
                    "adresse": adresse.strip(),
                    "code_postal": code_postal.strip(),
                    "ville": ville.strip(),
                    "telephone": telephone.strip(),
                    "email": email.strip(),
                    "linkedin": linkedin.strip(),
                    "github": github.strip(),
                    "contexte_academique": contexte_academique.strip(),
                })
                st.success("Profil enregistré.")

    st.subheader("💾 Sauvegarde de mes données")
    st.caption(
        f"Une sauvegarde automatique (profil, historique, CV) est faite chaque jour dans le dossier "
        f"« sauvegardes » du projet ({stockage.SAUVEGARDES_A_GARDER} dernières conservées). Pour une copie hors "
        "de ton PC (ex : Google Drive), télécharge-la ici."
    )
    nom_archive = f"sauvegarde_candidatures_{date.today().isoformat()}.zip"
    if _streamlit_recent():
        st.download_button("⬇️ Télécharger une sauvegarde", data=stockage.exporter_donnees, file_name=nom_archive,
                           mime="application/zip", on_click="ignore")
    else:
        st.download_button("⬇️ Télécharger une sauvegarde", data=stockage.exporter_donnees(), file_name=nom_archive,
                           mime="application/zip")
    with st.expander("♻️ Restaurer une sauvegarde"):
        st.caption("Remplace tes données actuelles par celles de la sauvegarde (l'état actuel est sauvegardé avant).")
        archive = st.file_uploader("Fichier de sauvegarde (.zip)", type=["zip"], key="restauration")
        if archive is not None and st.button("Restaurer cette sauvegarde", type="primary"):
            try:
                restaures = stockage.restaurer_sauvegarde(archive.getvalue())
            except (ValueError, OSError) as exc:
                st.error(str(exc))
            else:
                for cle_session in list(st.session_state):
                    if cle_session in ("derniere_candidature", "verif_cv") or cle_session.startswith("relance_mail_"):
                        del st.session_state[cle_session]
                st.success(f"Restauré : {', '.join(restaures)}.")
