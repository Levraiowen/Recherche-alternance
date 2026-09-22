"""
App de génération de candidatures (lettre de motivation + CV adapté) pour
les alternances. Lancement : streamlit run app.py
"""

import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv()

import ai_client  # noqa: E402
import stockage  # noqa: E402
from ai_client import ErreurGeneration, generer_candidature  # noqa: E402
from cv_editor import appliquer_adaptations, extraire_blocs  # noqa: E402
from lettre_generator import generer_lettre  # noqa: E402
from pdf_export import ErreurConversionPDF, convertir_en_pdf  # noqa: E402
from version import VERSION  # noqa: E402

MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_PDF = "application/pdf"


def _bouton_si_present(chemin_str: str | None, libelle: str, mime: str, cle: str) -> bool:
    """Affiche un bouton de téléchargement si le fichier existe encore sur le disque."""
    if not chemin_str:
        return False
    chemin = Path(chemin_str)
    if not chemin.exists():
        return False
    st.download_button(libelle, data=chemin.read_bytes(), file_name=chemin.name, mime=mime, key=cle)
    return True

st.set_page_config(page_title="Candidatures alternance", page_icon="📄", layout="wide")

# Fermeture demandée lors d'un tour précédent (voir bouton plus bas) : on
# affiche UNIQUEMENT ce message (rien d'autre du script ne s'exécute en
# dessous), puis on arrête le serveur. Un site ne peut pas forcer la
# fermeture d'un onglet que le navigateur a ouvert lui-même (restriction de
# sécurité identique sur tous les navigateurs, rien à voir avec cette app) :
# la tentative window.close() ci-dessous marche parfois, mais pas toujours —
# d'où le message explicite en secours, pour que ce soit sans ambiguïté.
if st.session_state.get("fermeture_demandee"):
    st.title("👋 Application fermée")
    st.success(
        "Le serveur est arrêté proprement (la fenêtre noire s'est refermée toute "
        "seule). Il ne reste plus que cet onglet : tu peux le fermer, il ne sert "
        "plus à rien."
    )
    components.html("<script>window.close();</script>", height=0)
    time.sleep(0.6)
    os._exit(0)

col_titre, col_fermer = st.columns([6, 1])
with col_titre:
    st.title("📄 Générateur de candidatures — alternance")
with col_fermer:
    st.write("")
    st.write("")
    if st.button(
        "🛑 Fermer l'app",
        help="Ferme proprement l'application (et la fenêtre noire associée), sans repasser par le terminal.",
    ):
        st.session_state["fermeture_demandee"] = True
        st.rerun()

st.caption(
    f"🔧 Version du code : **{VERSION}** — si tu ne vois pas la dernière version "
    "après une mise à jour, arrête complètement l'app (Ctrl+C dans le terminal) "
    "et relance `streamlit run app.py` (un simple rechargement du navigateur ne suffit pas)."
)

onglet_profil, onglet_cv, onglet_candidature, onglet_historique = st.tabs(
    ["👤 Mon profil", "📎 Mon CV", "✉️ Nouvelle candidature", "🕓 Historique"]
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
            help="Utilisé par l'IA pour situer ta candidature (formation, type de contrat recherché...).",
            height=100,
        )

        if st.form_submit_button("💾 Enregistrer mon profil"):
            nouveau_profil = {
                **profil,
                "nom": nom,
                "adresse": adresse,
                "code_postal": code_postal,
                "ville": ville,
                "telephone": telephone,
                "email": email,
                "linkedin": linkedin,
                "github": github,
                "contexte_academique": contexte_academique,
            }
            stockage.enregistrer_profil(nouveau_profil)
            st.success("Profil enregistré.")

# ----------------------------------------------------------------------------
# Onglet : Mon CV
# ----------------------------------------------------------------------------
with onglet_cv:
    st.caption(
        "Importe ton CV au format Word (.docx). Il est conservé comme référence "
        "permanente : chaque candidature part d'une copie de ce fichier, jamais "
        "modifiée directement."
    )

    if stockage.cv_present():
        profil_actuel = stockage.charger_profil()
        nom_original = profil_actuel.get("_cv_nom_original", "CV")
        importe_le = profil_actuel.get("_cv_importe_le", "")
        st.success(f"CV enregistré : **{nom_original}** (importé le {importe_le}).")
    else:
        st.warning("Aucun CV importé pour le moment.")

    fichier = st.file_uploader(
        "Remplacer / importer le CV (.docx uniquement)", type=["docx"]
    )
    if fichier is not None:
        stockage.enregistrer_cv(fichier.getvalue(), fichier.name)
        st.success(f"CV « {fichier.name} » enregistré comme nouvelle référence.")
        st.rerun()

    if stockage.cv_present():
        blocs = extraire_blocs(stockage.FICHIER_CV)
        with st.expander(f"Voir le texte détecté dans le CV ({len(blocs)} blocs)"):
            if not blocs:
                st.warning(
                    "Aucun texte détecté. Le CV utilise peut-être des zones de texte "
                    "ou des images plutôt que des paragraphes Word standards "
                    "(voir la limite connue dans le README)."
                )
            for b in blocs:
                st.text(f"[{b.id}] {b.texte}")

    st.info(
        "⚠️ Limite connue : seuls les paragraphes et tableaux Word « standards » "
        "sont détectés. Le texte dans des zones de texte, images ou SmartArt "
        "n'est pas modifié. Relis toujours le CV généré avant de l'envoyer."
    )

# ----------------------------------------------------------------------------
# Onglet : Nouvelle candidature
# ----------------------------------------------------------------------------
with onglet_candidature:
    if not stockage.cv_present():
        st.warning("Importe d'abord ton CV dans l'onglet « 📎 Mon CV ».")
    elif not ai_client.cle_api_presente():
        fournisseur = ai_client.fournisseur_actif()
        if fournisseur == "gemini":
            st.warning(
                "Aucune clé API Gemini configurée. Crée une clé **gratuite** sur "
                "aistudio.google.com/apikey, copie .env.example vers .env, ajoute-la "
                "(GEMINI_API_KEY=...) puis relance l'app."
            )
        else:
            st.warning(
                f"Aucune clé API {fournisseur} configurée. Copie .env.example vers "
                ".env, ajoute ta clé puis relance l'app."
            )
    else:
        st.caption(f"Génération via : **{ai_client.fournisseur_actif()}**")
        profil = stockage.charger_profil()

        col_a, col_b = st.columns(2)
        with col_a:
            entreprise_saisie = st.text_input("Nom de l'entreprise (optionnel)")
            poste_saisi = st.text_input("Intitulé du poste (optionnel)")
        with col_b:
            entreprise_adresse = st.text_input("Adresse de l'entreprise (optionnel)")
            consignes = st.text_input(
                "Remarques pour l'IA (optionnel)",
                help="Ex : « mets plus en avant mes compétences en Python et SQL »",
            )

        annonce = st.text_area("Colle le texte de l'annonce ici", height=280)

        if st.button("✨ Générer la candidature (PDF direct)", type="primary"):
            blocs = extraire_blocs(stockage.FICHIER_CV)
            try:
                with st.spinner("Génération du contenu (IA)..."):
                    resultat = generer_candidature(
                        blocs_cv=blocs,
                        texte_annonce=annonce,
                        contexte_academique=profil.get("contexte_academique", ""),
                        entreprise_indiquee=entreprise_saisie,
                        poste_indique=poste_saisi,
                        consignes_supplementaires=consignes,
                    )
            except ErreurGeneration as exc:
                st.error(str(exc))
            else:
                nom_personne = (profil.get("nom", "").strip().replace(" ", "_")) or "Candidat"
                entreprise_finale = resultat.entreprise or entreprise_saisie or "Entreprise"
                poste_finale = resultat.poste or poste_saisi or ""
                slug = stockage.slugifier_nom_fichier(entreprise_finale) or "Entreprise"

                # Sous-dossier propre à cette génération (horodatage, +poste si
                # connu) : sans ça, deux candidatures pour la même entreprise
                # (deux postes différents, ou deux essais successifs après
                # avoir ajusté les remarques pour l'IA) écraseraient
                # silencieusement les mêmes fichiers sur le disque — et donc
                # aussi l'entrée précédente dans l'historique, qui pointerait
                # alors vers le contenu de la nouvelle génération.
                horodatage = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
                poste_slug = stockage.slugifier_nom_fichier(poste_finale)
                sous_dossier = f"{poste_slug}_{horodatage}" if poste_slug else horodatage
                dossier = stockage.dossier_candidature(entreprise_finale, sous_dossier=sous_dossier)

                chemin_lettre = dossier / f"Lettre_Motivation_{nom_personne}_({slug}).docx"
                chemin_cv = dossier / f"CV_{nom_personne}_({slug}).docx"

                with st.spinner("Création des fichiers Word puis export en PDF..."):
                    generer_lettre(
                        resultat=resultat,
                        profil=profil,
                        entreprise_adresse=entreprise_adresse,
                        chemin_sortie=chemin_lettre,
                    )
                    blocs_appliques = appliquer_adaptations(
                        stockage.FICHIER_CV, chemin_cv, resultat.cv_adaptations
                    )

                    pdf_lettre = pdf_cv = None
                    erreur_pdf = None
                    try:
                        pdf_lettre = convertir_en_pdf(chemin_lettre)
                        pdf_cv = convertir_en_pdf(chemin_cv)
                    except ErreurConversionPDF as exc:
                        erreur_pdf = str(exc)

                stockage.ajouter_historique(
                    {
                        "date": datetime.now().isoformat(timespec="seconds"),
                        "entreprise": entreprise_finale,
                        "poste": resultat.poste or poste_saisi,
                        "lettre_docx": str(chemin_lettre),
                        "cv_docx": str(chemin_cv),
                        "lettre_pdf": str(pdf_lettre) if pdf_lettre else None,
                        "cv_pdf": str(pdf_cv) if pdf_cv else None,
                    }
                )
                st.session_state["brouillon_resultat"] = resultat
                st.session_state["brouillon_blocs"] = {b.id: b.texte for b in blocs}
                st.session_state["brouillon_appliques"] = set(blocs_appliques)
                st.session_state["derniers_fichiers"] = {
                    "lettre_docx": chemin_lettre,
                    "cv_docx": chemin_cv,
                    "lettre_pdf": pdf_lettre,
                    "cv_pdf": pdf_cv,
                }
                st.session_state["derniere_erreur_pdf"] = erreur_pdf
                st.session_state["dernier_dossier"] = dossier

        # Résultat affiché immédiatement après le clic (et conservé tant que
        # l'onglet reste ouvert) : plus d'étape de validation séparée, les
        # fichiers PDF/Word sont déjà créés dès que ce qui suit s'affiche.
        derniers_fichiers = st.session_state.get("derniers_fichiers")
        if derniers_fichiers:
            erreur_pdf = st.session_state.get("derniere_erreur_pdf")
            if erreur_pdf:
                st.warning(erreur_pdf)
            else:
                dossier_genere = st.session_state.get("dernier_dossier")
                try:
                    dossier_affiche = dossier_genere.relative_to(stockage.RACINE)
                except (AttributeError, ValueError):
                    dossier_affiche = dossier_genere or ""
                st.success(f"Fichiers PDF et Word créés dans {dossier_affiche}/")

            c1, c2 = st.columns(2)
            with c1:
                st.markdown("**Lettre de motivation**")
                if derniers_fichiers["lettre_pdf"]:
                    p = derniers_fichiers["lettre_pdf"]
                    st.download_button("⬇️ PDF", data=p.read_bytes(), file_name=p.name, mime=MIME_PDF)
                d = derniers_fichiers["lettre_docx"]
                st.download_button(
                    "⬇️ Word (.docx)", data=d.read_bytes(), file_name=d.name, mime=MIME_DOCX
                )
            with c2:
                st.markdown("**CV adapté**")
                if derniers_fichiers["cv_pdf"]:
                    p = derniers_fichiers["cv_pdf"]
                    st.download_button("⬇️ PDF", data=p.read_bytes(), file_name=p.name, mime=MIME_PDF)
                d = derniers_fichiers["cv_docx"]
                st.download_button(
                    "⬇️ Word (.docx)", data=d.read_bytes(), file_name=d.name, mime=MIME_DOCX
                )

        resultat = st.session_state.get("brouillon_resultat")
        if resultat is not None:
            st.divider()
            st.subheader("Contenu généré — relis avant d'envoyer ta candidature")
            with st.container(border=True):
                st.markdown(f"**Objet : {resultat.objet}**")
                st.write("")
                st.write(resultat.formule_appel)
                for paragraphe in resultat.paragraphes:
                    st.write(paragraphe)
                st.write(resultat.formule_politesse)

            st.subheader("Modifications appliquées au CV")
            if not resultat.cv_adaptations:
                st.info("Aucune adaptation appliquée : le CV collait déjà bien à l'offre.")
            else:
                blocs_avant = st.session_state.get("brouillon_blocs", {})
                blocs_appliques = st.session_state.get("brouillon_appliques", set())
                for identifiant, nouveau_texte in resultat.cv_adaptations.items():
                    if identifiant not in blocs_appliques:
                        # Arrive seulement si l'IA a renvoyé un identifiant de
                        # bloc qui ne correspond à aucun paragraphe du CV
                        # (rare) : le signaler clairement plutôt que de
                        # laisser croire que ce changement est dans le fichier
                        # final alors qu'il ne l'est pas.
                        st.warning(
                            f"⚠️ Changement proposé pour [{identifiant}] mais ce bloc est "
                            "introuvable dans le CV : il n'apparaît PAS dans le fichier final."
                        )
                        continue
                    c1, c2 = st.columns(2)
                    with c1:
                        st.caption(f"Avant [{identifiant}]")
                        st.text(blocs_avant.get(identifiant, "(bloc introuvable)"))
                    with c2:
                        st.caption("Après")
                        st.text(nouveau_texte)

# ----------------------------------------------------------------------------
# Onglet : Historique
# ----------------------------------------------------------------------------
with onglet_historique:
    historique = stockage.charger_historique()
    if not historique:
        st.info("Aucune candidature générée avec l'app pour le moment.")

    for index, entree in enumerate(historique):
        with st.container(border=True):
            col_titre, col_suppr = st.columns([6, 1])
            with col_titre:
                st.markdown(f"**{entree['entreprise']}** — {entree.get('poste') or 'poste non précisé'}")
                st.caption(entree["date"])
            with col_suppr:
                if st.button(
                    "🗑️",
                    key=f"h_suppr_{index}_{entree['date']}",
                    help="Retire cette candidature de la liste (les fichiers PDF/Word restent sur le disque, dans outputs/).",
                ):
                    stockage.supprimer_historique(index)
                    st.rerun()
            cle_base = f"{entree['date']}_{entree['entreprise']}"

            c1, c2 = st.columns(2)
            with c1:
                st.caption("Lettre de motivation")
                trouve_pdf = _bouton_si_present(
                    entree.get("lettre_pdf"), "⬇️ PDF", MIME_PDF, f"h_lettre_pdf_{cle_base}"
                )
                trouve_docx = _bouton_si_present(
                    entree.get("lettre_docx") or entree.get("lettre"),
                    "⬇️ Word (.docx)",
                    MIME_DOCX,
                    f"h_lettre_docx_{cle_base}",
                )
                if not trouve_pdf and not trouve_docx:
                    st.caption("Fichiers introuvables (déplacés ou supprimés).")
            with c2:
                st.caption("CV adapté")
                trouve_pdf = _bouton_si_present(
                    entree.get("cv_pdf"), "⬇️ PDF", MIME_PDF, f"h_cv_pdf_{cle_base}"
                )
                trouve_docx = _bouton_si_present(
                    entree.get("cv_docx") or entree.get("cv"),
                    "⬇️ Word (.docx)",
                    MIME_DOCX,
                    f"h_cv_docx_{cle_base}",
                )
                if not trouve_pdf and not trouve_docx:
                    st.caption("Fichiers introuvables (déplacés ou supprimés).")
