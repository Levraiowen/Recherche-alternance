"""Page « Mes candidatures » : la liste à gauche, la fiche détaillée à droite.

Le suivi (statut, dates, relances) reste FACULTATIF : sans lui, la page sert
simplement à retrouver les fichiers de chaque candidature.
"""

from __future__ import annotations

from datetime import date, timedelta

import streamlit as st

import assistant
import interface as ui
import rapport
import stockage
import suivi
from ai_client import ErreurGeneration

TAILLE_PAGE = 20
TRIS = ("Plus récentes", "Plus anciennes", "Entreprise (A à Z)", "Meilleure correspondance")
md = ui.md


# ----------------------------------------------------------------------------
# Rappels des boutons
# ----------------------------------------------------------------------------


def ouvrir(identifiant: str) -> None:
    st.session_state["candidature_ouverte"] = identifiant


def fermer() -> None:
    st.session_state.pop("candidature_ouverte", None)


def changer_statut_depuis_fiche(identifiant: str, cle_widget: str) -> None:
    try:
        suivi.changer_statut(identifiant, st.session_state[cle_widget])
    except OSError as exc:
        st.session_state["erreur_suivi"] = f"Statut non enregistré : {exc}"


# ----------------------------------------------------------------------------
# Liste
# ----------------------------------------------------------------------------


def filtrer(historique: list[dict], recherche: str, statuts: list[str] | None, tri: str) -> list[dict]:
    liste = historique
    if recherche.strip():
        cible = stockage.normaliser_nom(recherche)
        liste = [e for e in liste
                 if cible in stockage.normaliser_nom(f"{e.get('entreprise', '')} {e.get('poste', '')}")]
    if statuts:
        liste = [e for e in liste if suivi.statut(e) in statuts]
    if tri == "Plus anciennes":
        liste = list(reversed(liste))
    elif tri == "Entreprise (A à Z)":
        liste = sorted(liste, key=lambda e: stockage.normaliser_nom(e.get("entreprise", "")))
    elif tri == "Meilleure correspondance":
        liste = sorted(liste, key=lambda e: -(e["score"] if isinstance(e.get("score"), int) else -1))
    return liste


def afficher_ligne(entree: dict, ouverte: bool) -> None:
    eid = stockage.identifiant_entree(entree)
    cle = ui.cle_css(eid)
    with st.container(key=f"ligne_{'sel_' if ouverte else ''}{cle}"):
        col_nom, col_etat = st.columns([3, 1.35], vertical_alignment="top", gap="small")
        with col_nom:
            st.button(md(entree.get("entreprise") or "Entreprise"), key=f"sel_{cle}", type="tertiary",
                      on_click=ouvrir, args=(eid,), help="Ouvrir la fiche de cette candidature")
            ui.html(f'<p class="ligne-poste">{ui.echapper_html(entree.get("poste") or "Poste non précisé")}</p>')
        with col_etat:
            st.markdown(suivi.badge(suivi.statut(entree)), text_alignment="right")
            st.caption(ui.date_relative(entree.get("date", "")), text_alignment="right")


# ----------------------------------------------------------------------------
# Relances
# ----------------------------------------------------------------------------


def afficher_relances(relances: list[suivi.Relance], profil: dict) -> None:
    nombre = len(relances)
    with st.container(key="panneau_relances"):
        st.markdown(f"**:material/notifications_active: {nombre} candidature{'s' if nombre > 1 else ''} "
                    f"à relancer**")
        st.caption(f"Envoyées sans réponse depuis plus de {suivi.DELAI_RELANCE_JOURS} jours (ou "
                   f"{suivi.DELAI_DEUXIEME_RELANCE_JOURS} jours après une première relance). Un message court et "
                   "poli montre ta motivation.")
        for relance in relances:
            entree = relance.entree
            eid = stockage.identifiant_entree(entree)
            cle = ui.cle_css(eid)
            cle_mail = f"relance_mail_{eid}"
            col_texte, col_actions = st.columns([1.5, 2], vertical_alignment="center")
            with col_texte:
                detail = f"envoyée il y a {relance.jours} jours"
                if relance.deuxieme:
                    detail += ", déjà relancée une fois"
                st.markdown(f"**{md(entree.get('entreprise') or 'Entreprise')}**  \n"
                            f":gray[{md(entree.get('poste') or 'Poste non précisé')}, {detail}]")
            with col_actions:
                with st.container(horizontal=True, horizontal_alignment="right", gap="small"):
                    rediger = st.button("Rédiger la relance", key=f"btn_rel_gen_{cle}", icon=":material/edit_note:")
                    relancee = st.button("Marquer comme relancée", key=f"btn_rel_ok_{cle}", type="tertiary",
                                         icon=":material/done:")
                    ignorer = st.button("Ignorer", key=f"btn_rel_ign_{cle}", type="tertiary",
                                        help="Ne plus proposer de relance pour cette candidature.")
            if relancee or ignorer:
                with ui.signaler_erreur_enregistrement():
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
                            contexte=ui.contexte_candidature(entree), profil=profil,
                            langue=entree.get("langue") or "fr",
                        )
                except ErreurGeneration as exc:
                    st.error(str(exc))
            mail = st.session_state.get(cle_mail)
            if mail:
                ui.bloc_mail(mail.objet, mail.corps, entree.get("contact", ""))


# ----------------------------------------------------------------------------
# Fiche d'une candidature
# ----------------------------------------------------------------------------


def preparer_fiche_entretien(entree: dict, eid: str, dossier) -> None:
    anglais = entree.get("langue") == "en"
    entreprise, poste = entree.get("entreprise", ""), entree.get("poste", "")
    titre = (f"Interview at {entreprise} ({poste or 'work-study'})" if anglais
             else f"Entretien chez {entreprise} ({poste or 'alternance'})")
    try:
        with st.spinner("Préparation de la fiche d'entretien..."):
            fiche = assistant.preparer_entretien(
                entreprise=entreprise, poste=poste, contexte=ui.contexte_candidature(entree),
                cv_texte=ui.texte_cv(ui.cv_de_entree(entree)), langue=entree.get("langue") or "fr",
            )
        modifications = {"fiche_entretien": fiche.en_markdown(titre)}
        if ui.dossier_autorise(dossier):
            chemin = assistant.enregistrer_fiche_docx(fiche, titre, dossier / "Preparation_entretien.docx")
            modifications["fiche_entretien_docx"] = stockage.chemin_relatif(chemin)
        stockage.mettre_a_jour_historique(eid, modifications)
    except (ErreurGeneration, OSError) as exc:
        st.error(str(exc))
        return
    st.rerun()


def afficher_notes(entree: dict, eid: str, cle: str) -> None:
    with st.form(f"form_notes_{cle}", border=False):
        n1, n2 = st.columns(2)
        with n1:
            contact = st.text_input("E-mail du recruteur", value=entree.get("contact", ""))
        with n2:
            date_choisie = st.date_input("Date d'envoi", value=suivi.date_envoi(entree), format="DD/MM/YYYY")
        url = st.text_input("Lien de l'offre", value=entree.get("url_offre", ""))
        notes = st.text_area("Notes", value=entree.get("notes", ""), height=110,
                             placeholder="Contact RH, date d'entretien, impressions…")
        if st.form_submit_button("Enregistrer", icon=":material/save:"):
            modifications = {
                "contact": contact.strip(),
                "url_offre": url.strip(),
                "notes": notes.strip(),
                "date_envoi": date_choisie.isoformat() if isinstance(date_choisie, date) else "",
            }
            if modifications["date_envoi"] and not suivi.statut(entree):
                modifications["statut"] = "envoyee"  # une date d'envoi = candidature envoyée
            with ui.signaler_erreur_enregistrement():
                stockage.mettre_a_jour_historique(eid, modifications)
                st.toast("Notes enregistrées", icon=":material/save:")
                st.rerun()


def afficher_fiche(entree: dict) -> None:
    eid = stockage.identifiant_entree(entree)
    cle = ui.cle_css(eid)
    cle_statut = f"h_statut_{cle}"

    st.button("Vue d'ensemble", key="btn_fermer_fiche", type="tertiary", icon=":material/arrow_back:",
              on_click=fermer, help="Fermer la fiche et revenir à la vue d'ensemble")
    col_titre, col_statut = st.columns([3, 1.35], vertical_alignment="bottom")
    with col_titre:
        st.subheader(md(entree.get("entreprise") or "Entreprise"), anchor=False)
        st.caption(md(entree.get("poste") or "Poste non précisé"))
    with col_statut:
        # Valeur posée AVANT la création du champ (et pas d'`index=`) : le
        # statut affiché suit toujours le statut enregistré, même s'il a été
        # changé ailleurs (relance, « Je l'ai envoyée »...).
        actuel = suivi.statut(entree)
        if st.session_state.get(cle_statut) != actuel:
            st.session_state[cle_statut] = actuel
        st.selectbox("Statut", list(suivi.STATUTS), format_func=suivi.libelle, key=cle_statut,
                     on_change=changer_statut_depuis_fiche, args=(eid, cle_statut),
                     help="Facultatif : suis l'avancement de ta candidature.")

    faits = [("Préparée le", ui.formater_date(entree.get("date", ""), avec_heure=False))]
    if entree.get("date_envoi"):
        faits.append(("Envoyée le", ui.formater_date(entree["date_envoi"], avec_heure=False)))
    if entree.get("date_reponse"):
        delai = suivi.delai_reponse(entree)
        reponse = ui.formater_date(entree["date_reponse"], avec_heure=False)
        faits.append(("Réponse", reponse + (f", après {delai} jours" if delai is not None else "")))
    if isinstance(entree.get("score"), int):
        faits.append(("Correspondance", f"{entree['score']}\u00a0%"))
    faits.append(("Source", suivi.source_offre(entree)))
    if entree.get("langue") == "en":
        faits.append(("Langue", "Anglais"))
    if entree.get("cv_reference"):
        faits.append(("CV de départ", entree["cv_reference"]))
    ui.faits(faits)

    lettre_pdf = stockage.resoudre_chemin(entree.get("lettre_pdf"))
    cv_pdf = stockage.resoudre_chemin(entree.get("cv_pdf"))
    lettre_docx = stockage.resoudre_chemin(entree.get("lettre_docx") or entree.get("lettre"))
    cv_docx = stockage.resoudre_chemin(entree.get("cv_docx") or entree.get("cv"))
    dossier = stockage.resoudre_chemin(entree.get("dossier"))
    if dossier is None and lettre_docx is not None:
        dossier = lettre_docx.parent
    documents = (("Lettre", lettre_pdf, lettre_docx, "l"), ("CV adapté", cv_pdf, cv_docx, "c"))
    if any(ui.fichier_autorise(chemin) for _, pdf, docx, _ in documents for chemin in (pdf, docx)):
        colonnes = st.columns([1, 1, 0.45], gap="medium")
        for colonne, (nom_doc, pdf, docx, suffixe) in zip(colonnes, documents, strict=False):
            with colonne:
                if ui.fichier_autorise(pdf):
                    ui.feuille(pdf, f"h{suffixe}_{cle}", legende=nom_doc, largeur=360)
                else:
                    st.caption(nom_doc)
                with st.container(horizontal=True, gap="small"):
                    ui.bouton_telechargement(pdf, "PDF", ui.MIME_PDF, f"dl_h{suffixe}_pdf_{cle}",
                                             icon=":material/download:")
                    ui.bouton_telechargement(docx, "Word", ui.MIME_DOCX, f"dl_h{suffixe}_docx_{cle}",
                                             icon=":material/download:")
    else:
        st.caption("Fichiers introuvables : ils ont été déplacés ou supprimés du dossier outputs.")

    with st.container(horizontal=True, gap="small", vertical_alignment="center"):
        ui.bouton_ouvrir_dossier(dossier, f"btn_dossier_{cle}")
        url = entree.get("url_offre", "")
        if url.startswith(("http://", "https://")):
            st.link_button("Voir l'offre", url, icon=":material/open_in_new:")
        with st.popover("Retirer", icon=":material/delete:", type="tertiary"):
            st.caption("Retirer cette candidature de la liste ? Ses fichiers restent dans le dossier outputs.")
            if st.button("Oui, retirer", key=f"btn_retirer_{cle}", type="primary"):
                with ui.signaler_erreur_enregistrement():
                    stockage.supprimer_historique(eid)
                    fermer()
                    st.rerun()

    onglet_mail, onglet_notes, onglet_entretien = st.tabs(
        [":material/mail: E-mail", ":material/sticky_note_2: Notes", ":material/forum: Entretien"])
    with onglet_mail:
        if entree.get("email_corps"):
            st.caption("Pense à joindre la lettre et le CV en PDF avant d'envoyer.")
            ui.bloc_mail(entree.get("email_objet", ""), entree["email_corps"], entree.get("contact", ""))
        else:
            st.caption("Pas d'e-mail d'accompagnement pour cette candidature.")
    with onglet_notes:
        afficher_notes(entree, eid, cle)
    with onglet_entretien:
        if entree.get("fiche_entretien"):
            st.markdown(entree["fiche_entretien"])
            with st.container(horizontal=True, gap="small"):
                ui.bouton_telechargement(stockage.resoudre_chemin(entree.get("fiche_entretien_docx")),
                                         "Version Word imprimable", ui.MIME_DOCX, f"dl_fiche_{cle}",
                                         icon=":material/download:")
                preparer = st.button("Refaire la fiche", key=f"btn_entretien_{cle}", type="tertiary",
                                     icon=":material/autorenew:")
        else:
            st.caption("Une fiche pour arriver préparé : un pitch de présentation, les questions probables avec des "
                       "pistes de réponse tirées de ton CV, et des questions à poser au recruteur.")
            preparer = st.button("Préparer l'entretien", key=f"btn_entretien_{cle}", icon=":material/forum:")
        if preparer:
            preparer_fiche_entretien(entree, eid, dossier)


# ----------------------------------------------------------------------------
# Vue d'ensemble et rapport
# ----------------------------------------------------------------------------


def graphique_activite(donnees: rapport.DonneesRapport) -> None:
    if not donnees.activite or not any(n for _, n in donnees.activite):
        return
    import altair as alt
    import pandas as pd

    tableau = pd.DataFrame(donnees.activite, columns=["Période", "Candidatures"])
    tableau["Ordre"] = range(len(tableau))
    graphique = (
        alt.Chart(tableau)
        .mark_bar(cornerRadiusTopLeft=3, cornerRadiusTopRight=3)
        .encode(
            x=alt.X("Période:N", sort=alt.SortField("Ordre"), title=None, scale=alt.Scale(paddingInner=0.45),
                    axis=alt.Axis(labelAngle=0, ticks=False, domain=False, labelOverlap="greedy")),
            y=alt.Y("Candidatures:Q", title=None, axis=alt.Axis(tickMinStep=1, domain=False, ticks=False,
                                                                 labelPadding=6)),
            tooltip=[alt.Tooltip("Période:N", title="Semaine du" if donnees.activite_par == "semaine" else "Mois"),
                     alt.Tooltip("Candidatures:Q")],
        )
        .properties(height=170, background="transparent")
        .configure_view(strokeWidth=0)
    )
    st.space("small")
    st.caption(f"Candidatures préparées par {donnees.activite_par}")
    st.altair_chart(graphique, width="stretch")


def afficher_vue_ensemble(donnees: rapport.DonneesRapport) -> None:
    with st.container(key="panneau_apercu"):
        st.markdown("**Vue d'ensemble**")
        if donnees.suivi_utilise:
            ui.repartition_statuts(donnees.par_statut)
        else:
            st.caption("Le suivi est facultatif : indique le statut d'une candidature dans sa fiche (Envoyée, "
                       "Entretien...) pour voir ton taux de réponse et être prévenu quand relancer.")
        graphique_activite(donnees)
        lignes = rapport.constats(donnees)
        if lignes:
            st.markdown("\n".join(f"- {ligne}" for ligne in lignes))
    st.caption(":material/touch_app: Clique sur une candidature pour ouvrir sa fiche : fichiers, e-mail, notes et "
               "préparation d'entretien.")


def popover_rapport(historique: list[dict], profil: dict) -> None:
    with st.popover("Rapport PDF", icon=":material/summarize:"):
        st.markdown("**Rapport de ta recherche**")
        st.caption("Un PDF à garder ou à montrer à ton école : chiffres clés, réponses, sites d'emploi, relances "
                   "et détail de chaque candidature.")
        choix = st.selectbox("Période", rapport.PERIODES, key="r_periode")
        debut = fin = None
        if choix == "Personnalisée":
            st.session_state.setdefault("r_plage", (date.today() - timedelta(days=30), date.today()))
            plage = st.date_input("Dates", key="r_plage", format="DD/MM/YYYY", max_value=date.today())
            if isinstance(plage, (list, tuple)) and plage:
                debut, fin = plage[0], plage[-1]
        donnees = rapport.calculer(historique, rapport.periode(choix, debut=debut, fin=fin))
        st.caption(f"{donnees.libelle_periode}. {rapport.phrase_resume(donnees)}")
        st.download_button(
            "Télécharger le rapport", key="dl_rapport", type="primary", icon=":material/download:", width="stretch",
            data=lambda: rapport.generer_pdf(donnees, nom=profil.get("nom", ""), ville=profil.get("ville", "")),
            file_name=rapport.nom_fichier(donnees), mime=ui.MIME_PDF, on_click="ignore", disabled=not donnees.total,
        )


# ----------------------------------------------------------------------------
# Page
# ----------------------------------------------------------------------------

profil = stockage.charger_profil()
historique = stockage.charger_historique()
ui.entete("Mes candidatures", profil=profil)

erreur_suivi = st.session_state.pop("erreur_suivi", None)
if erreur_suivi:
    st.error(erreur_suivi, icon=":material/error:")

if not historique:
    ui.etat_vide("enveloppe", "Aucune candidature pour l'instant",
                 "Chaque candidature générée arrive ici avec sa lettre, son CV et son e-mail. Le suivi des envois et "
                 "des réponses est facultatif.")
    with st.container(horizontal=True, horizontal_alignment="center"):
        st.page_link("vues/nouvelle_candidature.py", label="Préparer ma première candidature",
                     icon=":material/edit_document:")
else:
    ensemble = rapport.calculer(historique, rapport.periode("Depuis le début"))
    col_resume, col_rapport = st.columns([3, 1], vertical_alignment="bottom")
    with col_resume:
        ui.html(f'<p class="resume">{ui.echapper_html(rapport.phrase_resume(ensemble))}</p>')
    with col_rapport:
        with st.container(horizontal=True, horizontal_alignment="right"):
            popover_rapport(historique, profil)

    relances = suivi.candidatures_a_relancer(historique)
    if relances:
        afficher_relances(relances, profil)

    col_liste, col_fiche = st.columns([5, 7], gap="large")
    with col_liste:
        col_recherche, col_filtres = st.columns([3, 1.25], vertical_alignment="center")
        with col_recherche:
            recherche = st.text_input("Rechercher", key="h_recherche", placeholder="Entreprise ou poste",
                                      icon=":material/search:", label_visibility="collapsed")
        with col_filtres:
            actifs = len(st.session_state.get("h_filtre") or []) + (st.session_state.get("h_tri", TRIS[0]) != TRIS[0])
            with st.popover(f"Filtres ({actifs})" if actifs else "Filtres", icon=":material/tune:", width="stretch"):
                filtre = st.pills("Statut", list(suivi.STATUTS), selection_mode="multi", format_func=suivi.libelle,
                                  key="h_filtre")
                tri = st.selectbox("Trier par", TRIS, key="h_tri")
        liste = filtrer(historique, recherche, filtre, tri)

        with st.container(horizontal=True, horizontal_alignment="distribute", vertical_alignment="center"):
            compte = f"{len(liste)} candidature{'s' if len(liste) > 1 else ''}"
            if len(liste) != len(historique):
                compte += f" sur {len(historique)}"
            st.caption(compte)
            st.download_button(
                "Exporter pour Excel", key="dl_export_csv", type="tertiary", icon=":material/table_view:",
                data=lambda: suivi.exporter_csv(liste), file_name=f"candidatures_{date.today().isoformat()}.csv",
                mime="text/csv", on_click="ignore",
                help="Fichier .csv qui s'ouvre dans Excel ou LibreOffice Calc (recherche et filtres appliqués).",
            )

        ouverte = st.session_state.get("candidature_ouverte")
        nb_affiches = st.session_state.get("h_nb_affiches", TAILLE_PAGE)
        if not liste:
            st.caption("Aucune candidature ne correspond à ta recherche.")
        # Liste à hauteur fixe, qui défile seule : la fiche ouverte à droite
        # reste en vue, même pour une candidature en bas de la liste.
        with st.container(height=540 if len(liste) > 6 else "content", border=False, key="liste_candidatures"):
            for entree in liste[:nb_affiches]:
                afficher_ligne(entree, stockage.identifiant_entree(entree) == ouverte)
            if len(liste) > nb_affiches:
                if st.button(f"Afficher {min(TAILLE_PAGE, len(liste) - nb_affiches)} de plus", key="btn_plus",
                             type="tertiary", icon=":material/expand_more:"):
                    st.session_state["h_nb_affiches"] = nb_affiches + TAILLE_PAGE
                    st.rerun()

    with col_fiche:
        entree_ouverte = next((e for e in historique if stockage.identifiant_entree(e) == ouverte), None)
        if entree_ouverte is not None:
            afficher_fiche(entree_ouverte)
        else:
            if ouverte:
                fermer()  # candidature retirée entre-temps
            afficher_vue_ensemble(ensemble)
