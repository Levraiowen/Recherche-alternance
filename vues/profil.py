"""Page « Profil » : les coordonnées de l'en-tête des lettres, les sauvegardes et l'IA utilisée."""

from __future__ import annotations

from datetime import date

import streamlit as st

import ai_client
import interface as ui
import stockage
from lettre_generator import formater_telephone

NOMS_FOURNISSEURS = {"gemini": "Gemini (Google)", "anthropic": "Claude (Anthropic)"}


def apercu_entete(profil: dict) -> None:
    """Haut d'une lettre, avec les informations enregistrées, sur une vraie feuille."""
    e = ui.echapper_html
    cp_ville = " ".join(p for p in (profil.get("code_postal", ""), profil.get("ville", "")) if p.strip())
    lignes = [profil.get("adresse", ""), cp_ville, formater_telephone(profil.get("telephone", "")),
              profil.get("email", "")]
    expediteur = "".join(f"<p>{e(ligne)}</p>" for ligne in lignes if ligne.strip())
    nom = e(profil.get("nom", "").strip()) or '<span class="vide">Ton nom</span>'
    corps = "".join(f'<i class="trait" style="width:{largeur}%"></i>' for largeur in (100, 96, 100, 88, 100, 62))
    ui.html(
        '<div class="mini-lettre">'
        f'<p class="nom">{nom}</p>{expediteur or "<p class=vide>Adresse, téléphone et e-mail</p>"}'
        '<div class="ecart"></div><p class="droite nom">Entreprise</p><p class="droite">Service recrutement</p>'
        f'<div class="ecart"></div><p class="droite">{e(ui.ligne_date(profil))}</p>'
        '<div class="ecart"></div><p class="objet">Objet : Candidature pour un poste en alternance</p>'
        f'<div class="ecart"></div><p>Madame, Monsieur,</p>{corps}</div>'
    )


def formulaire(profil: dict) -> None:
    with st.form("form_profil", border=False):
        st.subheader("Coordonnées", anchor=False)
        nom = st.text_input("Nom complet", value=profil.get("nom", ""))
        adresse = st.text_input("Adresse", value=profil.get("adresse", ""), placeholder="12 rue des Lilas")
        c1, c2 = st.columns([1, 2])
        with c1:
            code_postal = st.text_input("Code postal", value=profil.get("code_postal", ""))
        with c2:
            ville = st.text_input("Ville", value=profil.get("ville", ""))
        c3, c4 = st.columns(2)
        with c3:
            telephone = st.text_input("Téléphone", value=profil.get("telephone", ""))
            linkedin = st.text_input("LinkedIn (facultatif)", value=profil.get("linkedin", ""))
        with c4:
            email = st.text_input("E-mail", value=profil.get("email", ""))
            github = st.text_input("GitHub (facultatif)", value=profil.get("github", ""))
        st.subheader("Ta recherche", anchor=False)
        contexte_academique = st.text_area(
            "Formation et contrat recherché", value=profil.get("contexte_academique", ""), height=110,
            help="L'IA s'en sert pour situer ta candidature : formation, rythme de l'alternance, date de début...",
        )
        if st.form_submit_button("Enregistrer mon profil", type="primary", icon=":material/save:"):
            with ui.signaler_erreur_enregistrement():
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
                st.toast("Profil enregistré", icon=":material/check_circle:")


def sauvegardes() -> None:
    st.subheader("Sauvegardes", anchor=False)
    st.caption(f"Ton profil, tes candidatures et tes CV sont copiés chaque jour dans le dossier « sauvegardes » "
               f"({stockage.SAUVEGARDES_A_GARDER} dernières copies gardées). Pour une copie hors de ton ordinateur "
               "(Google Drive, clé USB...), télécharge-la.")
    st.download_button("Télécharger une sauvegarde", data=stockage.exporter_donnees, key="dl_sauvegarde",
                       file_name=f"sauvegarde_candidatures_{date.today().isoformat()}.zip", mime="application/zip",
                       on_click="ignore", icon=":material/download:")
    with st.expander("Restaurer une sauvegarde", icon=":material/settings_backup_restore:"):
        st.caption("Remplace tes données actuelles par celles de la sauvegarde. L'état actuel est sauvegardé juste "
                   "avant.")
        archive = st.file_uploader("Fichier de sauvegarde (.zip)", type=["zip"], key="restauration")
        if archive is not None and st.button("Restaurer cette sauvegarde", type="primary", key="btn_restaurer"):
            try:
                restaures = stockage.restaurer_sauvegarde(archive.getvalue())
            except (ValueError, OSError) as exc:
                st.error(str(exc))
            else:
                for cle_session in list(st.session_state):
                    if (cle_session in ("derniere_candidature", "verif_cv", "candidature_ouverte")
                            or str(cle_session).startswith("relance_mail_")):
                        del st.session_state[cle_session]
                st.success(f"Restauré : {', '.join(restaures)}.", icon=":material/check_circle:")


def redaction() -> None:
    st.subheader("Rédaction", anchor=False)
    fournisseur = ai_client.fournisseur_actif()
    ui.faits([
        ("Service d'IA", NOMS_FOURNISSEURS.get(fournisseur, fournisseur)),
        ("Modèle", ai_client.modele_configure()),
        ("Clé", "configurée" if ai_client.cle_api_presente() else "absente"),
    ])
    st.caption("Le service et le modèle se règlent dans le fichier .env (modèle : .env.example). La clé n'est jamais "
               "affichée dans l'app.")


# ----------------------------------------------------------------------------
# Page
# ----------------------------------------------------------------------------

ui.entete("Profil", "Tes coordonnées forment l'en-tête de chaque lettre. Elles restent sur ton ordinateur, dans "
          "data/profil.json.", stockage.charger_profil())

col_formulaire, col_cote = st.columns([6, 4], gap="large")
with col_formulaire:
    formulaire(stockage.charger_profil())
with col_cote:
    st.caption("En-tête de tes lettres")
    apercu_entete(stockage.charger_profil())  # relu : montre tout de suite ce qui vient d'être enregistré
    st.space("medium")
    sauvegardes()
    st.space("small")
    redaction()
