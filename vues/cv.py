"""Page « Mes CV » : le CV principal, les CV supplémentaires et la vérification sur une page."""

from __future__ import annotations

import hashlib
import io

import streamlit as st

import interface as ui
import stockage
from candidature import verifier_cv_reference
from mise_en_page import lignes_en_trop_estimees
from pdf_export import ErreurConversionPDF

md = ui.md


def _docx_valide(contenu: bytes) -> bool:
    try:
        from docx import Document

        Document(io.BytesIO(contenu))
    except Exception:  # noqa: BLE001
        return False
    return True


def cv_principal_importe() -> None:
    """Rappel du champ d'import : le CV est enregistré AVANT l'affichage de la
    page, qui montre donc tout de suite le nouveau nom."""
    fichier = st.session_state.get("cv_principal_fichier")
    if fichier is None:
        return
    contenu = fichier.getvalue()
    signature = hashlib.sha256(contenu).hexdigest()  # chaque fichier n'est traité qu'une fois
    if st.session_state.get("cv_importe") == signature:
        return
    if not _docx_valide(contenu):
        st.session_state["cv_message"] = (
            "error", "Ce fichier n'est pas un document Word (.docx) valide : il n'a pas été enregistré.")
        return
    try:
        stockage.enregistrer_cv(contenu, fichier.name)
    except OSError as exc:
        st.session_state["cv_message"] = ("error", f"Enregistrement impossible pour le moment : {exc}")
        return
    st.session_state["cv_importe"] = signature
    st.session_state.pop("verif_cv", None)
    st.session_state["cv_message"] = ("success", f"« {fichier.name} » est maintenant ton CV principal.")


def afficher_message() -> None:
    message = st.session_state.pop("cv_message", None)
    if message:
        nature, texte = message
        if nature == "success":
            st.success(texte, icon=":material/check_circle:")
        else:
            st.error(texte, icon=":material/error:")


def champ_import(libelle: str) -> None:
    st.file_uploader(libelle, type=["docx"], key="cv_principal_fichier", on_change=cv_principal_importe)
    afficher_message()


def afficher_cv_principal(profil: dict) -> None:
    st.subheader("CV principal", anchor=False)
    if stockage.cv_present():
        nom_original = profil.get("_cv_nom_original", "cv_original.docx")
        importe_le = ui.formater_date(profil.get("_cv_importe_le", ""), avec_heure=False)
        st.markdown(f":material/description: **{md(nom_original)}**"
                    + (f"  \n:gray[Importé le {importe_le}]" if importe_le else ""))
        champ_import("Remplacer le CV principal (.docx)")
    else:
        st.caption("Aucun CV principal pour le moment.")
        champ_import("Importer le CV principal (.docx)")


def afficher_autres_cv(cvs: list[stockage.CVReference]) -> None:
    st.subheader("Autres CV", anchor=False)
    st.caption("Facultatif : un CV par type de poste (Data, Marketing...). Tu choisis le CV de départ au moment de "
               "générer une candidature.")
    for cv in cvs:
        if cv.principal:
            continue
        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            st.markdown(f":material/description: {md(cv.nom)}")
            with st.popover("Supprimer", icon=":material/delete:", type="tertiary"):
                st.caption("Supprimer ce CV ? Une copie reste dans la sauvegarde automatique du jour.")
                if st.button("Oui, supprimer", key=f"btn_cv_suppr_{ui.cle_css(cv.nom)}", type="primary"):
                    with ui.signaler_erreur_enregistrement():
                        stockage.supprimer_cv(cv.nom)
                        st.rerun()
    with st.expander("Ajouter un CV", icon=":material/add:"):
        with st.form("form_cv_supp", clear_on_submit=True, border=False):
            nom_supp = st.text_input("Nom du CV", placeholder="CV Marketing")
            fichier_supp = st.file_uploader("Fichier Word (.docx)", type=["docx"])
            if st.form_submit_button("Ajouter ce CV", icon=":material/add:"):
                if not fichier_supp or not stockage.nom_cv_valide(nom_supp):
                    st.error("Indique un nom et choisis un fichier .docx.")
                else:
                    contenu = ui.lire_docx_importe(fichier_supp)
                    if contenu is not None:
                        with ui.signaler_erreur_enregistrement():
                            stockage.ajouter_cv(contenu, nom_supp)
                            st.success(f"CV « {stockage.nom_cv_valide(nom_supp)} » ajouté.",
                                       icon=":material/check_circle:")


def afficher_verification(cvs: list[stockage.CVReference]) -> None:
    st.subheader("Vérifier un CV", anchor=False)
    st.caption("Chaque CV généré est ajusté automatiquement pour tenir sur une page. Ce test vérifie le CV tel quel "
               "et mémorise le réglage pour accélérer les prochaines candidatures.")
    noms = [cv.nom for cv in cvs]
    if st.session_state.get("cv_verif_choix") not in noms:
        st.session_state.pop("cv_verif_choix", None)  # CV supprimé entre-temps
    with st.container(horizontal=True, vertical_alignment="bottom", gap="small"):
        if len(cvs) > 1:
            nom_verif = st.selectbox("CV à vérifier", noms, key="cv_verif_choix")
        else:
            nom_verif = noms[0]
        verifier = st.button("Vérifier qu'il tient sur une page", icon=":material/fact_check:", key="btn_verifier")
    cv_verif = cvs[noms.index(nom_verif)] if nom_verif in noms else cvs[0]
    if verifier:
        try:
            with st.spinner("Conversion en PDF et vérification..."):
                st.session_state["verif_cv"] = (
                    cv_verif.nom,
                    verifier_cv_reference(stockage.DOSSIER_OUTPUTS / "_verification_cv", cv_reference=cv_verif.chemin),
                )
        except ErreurConversionPDF as exc:
            st.error(str(exc))
    verif_session = st.session_state.get("verif_cv")
    if verif_session and verif_session[0] == cv_verif.nom:
        verif = verif_session[1]
        if verif.une_page and verif.niveau == 0:
            st.success(f"Ce CV tient sur une page tel quel (PDF créé avec {verif.methode}).",
                       icon=":material/check_circle:")
        elif verif.une_page:
            st.info(f"Ce CV tient sur une page avec un léger resserrement ({verif.description}), appliqué "
                    f"automatiquement à chaque candidature (PDF créé avec {verif.methode}).",
                    icon=":material/check_circle:")
        else:
            st.warning(f"Même resserré au maximum, ce CV fait {verif.pages} pages (environ "
                       f"{lignes_en_trop_estimees(verif)} ligne(s) de trop) : raccourcis-le un peu.",
                       icon=":material/warning:")
        col_apercu, _ = st.columns([4, 1])
        with col_apercu:
            ui.feuille(verif.chemin_pdf, "verification", legende=f"{cv_verif.nom}, tel que l'app le voit",
                       largeur=480)

    try:
        blocs = ui.blocs_cv(cv_verif.chemin)
    except Exception:  # noqa: BLE001 - CV supprimé ou illisible entre-temps
        blocs = []
    with st.expander(f"Texte détecté dans le CV ({len(blocs)} blocs)", icon=":material/text_snippet:"):
        if not blocs:
            st.warning("Aucun texte détecté. Le CV utilise peut-être des zones de texte ou des images plutôt que des "
                       "paragraphes Word standards.", icon=":material/warning:")
        st.caption(":material/lock: bloc jamais modifié par l'IA (coordonnées, liens, titres de section).")
        st.text("\n".join(f"{'' if b.modifiable else '[verrouillé] '}[{b.id}] {b.texte}" for b in blocs))


# ----------------------------------------------------------------------------
# Page
# ----------------------------------------------------------------------------

profil = stockage.charger_profil()
cvs = stockage.lister_cvs()
ui.entete("Mes CV", "Tes CV Word servent de base à chaque candidature. Ils ne sont jamais modifiés : chaque "
          "candidature part d'une copie.", profil)

if not cvs:
    _, col_centre, _ = st.columns([1, 2, 1])
    with col_centre:
        ui.etat_vide("cv", "Importe ton CV pour commencer",
                     "Un fichier Word (.docx) avec des paragraphes standards. L'app l'adapte à chaque offre sans "
                     "jamais toucher à l'original.")
        champ_import("CV principal (.docx)")
else:
    col_cvs, col_verif = st.columns([5, 6], gap="large")
    with col_cvs:
        afficher_cv_principal(profil)
        afficher_autres_cv(cvs)
    with col_verif:
        afficher_verification(cvs)
    st.caption(":material/info: Limite connue : seuls les paragraphes et tableaux Word standards sont lus. Le texte "
               "placé dans des zones de texte, des images ou des SmartArt n'est pas adapté. Relis toujours le CV "
               "généré.")
