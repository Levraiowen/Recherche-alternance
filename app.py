"""
App de génération de candidatures (lettre de motivation et CV adapté) pour
les alternances. Lancement : streamlit run app.py (ou double-clic sur
Lancer.bat sous Windows).

Ce fichier pose le cadre commun à toutes les pages (thème, logo,
navigation, pied de page) ; chaque page est dans le dossier vues/.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent
sys.path.insert(0, str(RACINE / "src"))

import streamlit as st  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(RACINE / ".env")

from version import VERSION  # noqa: E402

ICONE = RACINE / "static" / "icone.png"
st.set_page_config(page_title="Candidatures alternance",
                   page_icon=str(ICONE) if ICONE.exists() else ":material/description:", layout="wide")


def _version_installee() -> str:
    """Version écrite sur le disque (src/version.py), relue à chaque affichage."""
    try:
        texte = (RACINE / "src" / "version.py").read_text(encoding="utf-8")
    except OSError:
        return VERSION
    for ligne in texte.splitlines():
        if ligne.startswith("VERSION"):
            return ligne.split("=", 1)[1].strip().strip("\"'")
    return VERSION


def _fermer_le_serveur() -> None:
    time.sleep(0.6)
    os._exit(0)


# Fichiers mis à jour pendant que l'app tournait : les modules déjà chargés en
# mémoire sont encore les anciens, et les mélanger avec le nouveau code
# provoquerait des erreurs incompréhensibles. On demande simplement de relancer.
if _version_installee() != VERSION:
    st.title("Mise à jour installée", anchor=False)
    st.info(
        f"Une nouvelle version de l'app ({_version_installee()}) a été installée pendant qu'elle tournait "
        f"(version chargée : {VERSION}). Ferme l'app avec le bouton ci-dessous, puis relance-la avec ton "
        "raccourci habituel.",
        icon=":material/system_update:",
    )
    if st.button("Fermer l'app", icon=":material/power_settings_new:"):
        st.success("Application fermée. Tu peux fermer cet onglet et relancer l'app.")
        _fermer_le_serveur()
    st.stop()

import ai_client  # noqa: E402
import interface as ui  # noqa: E402
import stockage  # noqa: E402

# Fermeture demandée lors d'un tour précédent : on affiche UNIQUEMENT ce
# message, puis on arrête le serveur. Un site ne peut pas forcer la fermeture
# d'un onglet que le navigateur a ouvert lui-même (restriction de sécurité de
# tous les navigateurs) : d'où le message explicite.
if st.session_state.get("fermeture_demandee"):
    ui.injecter_style()
    st.title("Application fermée", anchor=False)
    st.success("Le serveur est arrêté proprement (la fenêtre noire s'est refermée toute seule). Tu peux fermer "
               "cet onglet.", icon=":material/check_circle:")
    _fermer_le_serveur()

# Streamlit oublie la valeur d'un champ dès que sa page n'est plus affichée.
# On la recopie à chaque affichage : l'annonce en cours, les retouches de la
# lettre et les filtres sont retrouvés intacts après un détour par une autre
# page. (Uniquement des champs de saisie : la valeur d'un bouton ou d'un
# fichier importé ne peut pas être recopiée.)
CHAMPS_A_GARDER = ("f_", "ed_", "h_recherche", "h_filtre", "h_tri", "r_periode", "r_plage", "cv_verif_choix")
for cle in list(st.session_state):
    if isinstance(cle, str) and cle.startswith(CHAMPS_A_GARDER):
        try:
            st.session_state[cle] = st.session_state[cle]
        except Exception:  # noqa: BLE001 - champ qui n'accepte pas d'être recopié : on le laisse tel quel
            pass

# Sauvegarde automatique des données (une fois par jour, au premier affichage).
if "sauvegarde_auto" not in st.session_state:
    st.session_state["sauvegarde_auto"] = stockage.sauvegarde_automatique()

ui.injecter_style()
theme = getattr(st.context, "theme", None)
sombre = getattr(theme, "type", None) == "dark"
st.logo(str(RACINE / "static" / ("logo_sombre.svg" if sombre else "logo.svg")), size="large")

pages = [
    st.Page("vues/nouvelle_candidature.py", title="Nouvelle candidature", icon=":material/edit_document:",
            default=True),  # page d'accueil : adresse racine (http://127.0.0.1:8501)
    st.Page("vues/candidatures.py", title="Mes candidatures", icon=":material/inbox:", url_path="candidatures"),
    st.Page("vues/cv.py", title="Mes CV", icon=":material/description:", url_path="cv"),
    st.Page("vues/profil.py", title="Profil", icon=":material/person:", url_path="profil"),
]
st.navigation(pages, position="top").run()

with st.container(key="pied", horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
    fournisseur = {"gemini": "Gemini", "anthropic": "Claude"}.get(ai_client.fournisseur_actif(),
                                                                 ai_client.fournisseur_actif())
    st.caption(f"Version {VERSION}. Rédaction par {fournisseur} ({ai_client.modele_configure()}).")
    if st.button("Fermer l'app", key="btn_fermer_app", type="tertiary", icon=":material/power_settings_new:",
                 help="Arrête proprement l'application (et la fenêtre noire associée)."):
        st.session_state["fermeture_demandee"] = True
        st.rerun()
