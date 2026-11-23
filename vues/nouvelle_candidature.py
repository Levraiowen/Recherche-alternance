"""Page « Nouvelle candidature » : l'offre à gauche, les documents à droite."""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import streamlit as st

import ai_client
import assistant
import interface as ui
import recherches
import stockage
import suivi
from ai_client import ErreurGeneration, generer_candidature
from candidature import ResultatCandidature, produire_candidature
from cv_editor import extraire_blocs
from ia_commun import (
    CORPS_LETTRE_MAX,
    CORPS_LETTRE_MIN,
    LONGUEURS,
    TONS,
    ResultatGeneration,
    consignes_redaction,
    detecter_langue,
)
from import_offre import ErreurImport, importer_offre

CHAMPS_OFFRE = ("f_url", "f_annonce", "f_entreprise", "f_poste", "f_adresse", "f_contact", "f_remarques")
# Champs propres à UNE offre : quand on passe à une autre offre, une valeur
# restée de la précédente (souvent dans les options repliées) ne doit pas se
# retrouver dans la nouvelle candidature.
CHAMPS_LIES_A_L_OFFRE = {"f_entreprise": "l'entreprise", "f_poste": "le poste", "f_adresse": "l'adresse",
                         "f_contact": "l'e-mail du recruteur", "f_url": "le lien"}
SEUIL_MEME_OFFRE = 0.6  # part de mots communs au-delà de laquelle une annonce modifiée reste « la même offre »
CHOIX_LANGUE = ("Automatique", "Français", "Anglais")


# ----------------------------------------------------------------------------
# Formulaire : mémoire de l'offre en cours, import par lien
# ----------------------------------------------------------------------------


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
    ton, la longueur, la langue et le CV choisis sont gardés)."""
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


def phrase_deja_postule(precedentes: list[dict], autre: bool = False) -> str:
    """« Une candidature a déjà été préparée pour cette entreprise, le 21 novembre 2026. »"""
    derniere = ui.formater_date(precedentes[0].get("date", ""), avec_heure=False)
    if len(precedentes) == 1:
        return (f"{'Une autre' if autre else 'Une'} candidature a déjà été préparée pour cette entreprise, "
                f"le {derniere}.")
    return (f"{len(precedentes)} {'autres ' if autre else ''}candidatures ont déjà été préparées pour cette "
            f"entreprise, la dernière le {derniere}.")


def langue_de_la_lettre(choix: str, annonce: str) -> str:
    if choix == "Anglais":
        return "en"
    if choix == "Français":
        return "fr"
    return detecter_langue(annonce)


# ----------------------------------------------------------------------------
# Résultat : analyse, retouches, documents
# ----------------------------------------------------------------------------


def afficher_analyse(resultat: ResultatGeneration) -> None:
    if resultat.score is None:
        st.info("Pas d'analyse de correspondance pour cette candidature.", icon=":material/info:")
        return
    col_score, col_detail = st.columns([1, 2.6], gap="medium")
    with col_score:
        ui.html(f'<p class="resume" style="font-size:2.6rem;margin:0">{resultat.score}&nbsp;%</p>'
                '<p class="legende-feuille" style="margin:0">Correspondance estimée</p>')
        st.progress(resultat.score / 100)
    with col_detail:
        if resultat.points_forts:
            st.markdown("**Tes atouts pour cette offre**")
            st.markdown("  \n".join(f":green[:material/check:] {assistant.texte_ia_sur(p)}"
                                    for p in resultat.points_forts))
        if resultat.mots_cles_manquants:
            st.markdown("**Ce que l'offre demande et que ton CV ne montre pas**")
            st.markdown("  \n".join(f":orange[:material/priority_high:] {assistant.texte_ia_sur(m)}"
                                    for m in resultat.mots_cles_manquants))
            st.caption("À ajouter à ton CV seulement si c'est vrai. Sinon, prépare-toi à en parler en entretien.")
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
        "Modifie le texte puis clique sur « Mettre à jour les fichiers » : la lettre et le CV sont régénérés "
        "(Word et PDF sur une page) sans rappeler l'IA. « Reformuler » fait réécrire un seul paragraphe par "
        "l'IA. Un paragraphe laissé vide est retiré de la lettre."
    )
    # Valeurs initiales posées une seule fois dans l'état de session, puis
    # champs créés SANS `value=` : on peut ainsi les modifier par programme
    # (bouton « Reformuler ») sans conflit avec Streamlit.
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
    consigne = st.text_input("Consigne pour « Reformuler » (facultatif)", key=f"ed_consigne_{eid}",
                             placeholder="Plus court, plus concret, insiste sur Power BI...")
    paragraphes = []
    cles_paragraphes = [f"ed_p{i}_{eid}" for i in range(len(paragraphes_origine))]
    for i, cle in enumerate(cles_paragraphes):
        col_label, col_bouton = st.columns([3, 1.3], vertical_alignment="bottom")
        with col_label:
            st.markdown(f"**Paragraphe {i + 1}**")
        with col_bouton:
            # Bouton placé AVANT la zone de texte : on peut ainsi remplacer
            # son contenu dans ce même affichage.
            if st.button("Reformuler", key=f"btn_reformuler_{i}_{eid}", icon=":material/autorenew:",
                         type="tertiary", help="Réécriture de ce paragraphe par l'IA"):
                actuels = [st.session_state.get(c, "") for c in cles_paragraphes]
                try:
                    with st.spinner("Réécriture du paragraphe..."):
                        st.session_state[cle] = assistant.reecrire_paragraphe(
                            paragraphes=[p or "(paragraphe vide)" for p in actuels], index=i,
                            annonce=session.get("annonce", ""), cv_texte=ui.texte_cv(session.get("cv_reference")),
                            consigne=consigne, langue=resultat.langue,
                        )
                except ErreurGeneration as exc:
                    st.error(str(exc))
        paragraphes.append(st.text_area(f"Paragraphe {i + 1}", height=130, key=cle, label_visibility="collapsed"))
    politesse = st.text_area("Formule de politesse", height=70, key=f"ed_politesse_{eid}")
    longueur = sum(len(p) for p in paragraphes)
    if longueur <= CORPS_LETTRE_MAX + 150:
        st.caption(f"Corps de la lettre : {longueur} caractères (cible {CORPS_LETTRE_MIN} à {CORPS_LETTRE_MAX}).")
    else:
        st.caption(f"Corps de la lettre : {longueur} caractères. Un peu long : la mise en page sera resserrée "
                   "pour tenir sur une page.")

    st.markdown("**Modifications du CV**")
    blocs_avant = session["blocs_avant"]
    nouvelles_adaptations: dict[str, str] = {}
    visibles = 0
    for bid, texte in propositions_cv.items():
        if " ".join(texte.split()) == " ".join(blocs_avant.get(bid, "").split()):
            continue  # proposition identique au CV d'origine : rien à montrer
        visibles += 1
        with st.container(border=True):
            actif = st.checkbox(f"Appliquer la modification du bloc {bid}", key=f"ed_cv_on_{bid}_{eid}")
            raison = production.adaptations.ignores.get(bid)
            if raison is None and not actif and bid not in production.adaptations.appliques:
                raison = ignores_origine.get(bid)
            if raison:
                st.caption(f":orange[:material/warning:] Non appliquée : {raison}.")
            st.caption("Avant")
            st.text(blocs_avant.get(bid, "(bloc introuvable dans le CV)"))
            nouveau = st.text_area("Après", height=90, key=f"ed_cv_txt_{bid}_{eid}")
            if actif:
                nouvelles_adaptations[bid] = nouveau
    if not visibles:
        st.caption("Aucune modification proposée : ton CV collait déjà bien à l'offre.")

    if st.button("Mettre à jour les fichiers", type="primary", key=f"maj_{eid}", icon=":material/sync:"):
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
            with st.spinner("Régénération des fichiers et mise en page sur une page..."):
                nouvelle_production = produire_candidature(
                    resultat=modifie, profil=stockage.charger_profil(),
                    entreprise_adresse=session["entreprise_adresse"], dossier=session["dossier"],
                    cv_reference=session.get("cv_reference"),
                )
        except Exception as exc:  # noqa: BLE001
            ui.afficher_erreur_production(exc)
            return
        maj = ui.entree_historique(modifie, nouvelle_production, session["dossier"], eid)
        maj.pop("date")  # garder la date de création d'origine
        try:
            stockage.mettre_a_jour_historique(eid, maj)
        except OSError as exc:
            st.warning(f"Fichiers mis à jour, mais l'historique n'a pas pu être enregistré : {exc}")
        session["resultat"] = modifie
        session["production"] = nouvelle_production
        st.toast("Fichiers mis à jour", icon=":material/check_circle:")
        st.rerun()


def afficher_resultat(session: dict) -> None:
    resultat: ResultatGeneration = session["resultat"]
    production: ResultatCandidature = session["production"]
    dossier: Path = session["dossier"]
    eid: str = session["id"]
    cle = ui.cle_css(eid)

    col_titre, col_langue = st.columns([3, 1], vertical_alignment="bottom")
    with col_titre:
        st.subheader(ui.md(resultat.entreprise or "Entreprise"), anchor=False)
        if resultat.poste:
            st.caption(ui.md(resultat.poste))
    with col_langue:
        if resultat.langue == "en":
            st.markdown(":blue-badge[:material/translate: Lettre en anglais]", text_alignment="right")
    if production.erreurs_pdf:
        st.warning("Les fichiers Word sont prêts, mais l'export PDF a échoué : télécharge les .docx et "
                   "exporte-les en PDF toi-même.", icon=":material/warning:")
        with st.expander("Détail de l'erreur PDF"):
            st.text("\n\n".join(production.erreurs_pdf))
    precedentes = stockage.candidatures_precedentes(resultat.entreprise, sauf=eid)
    if precedentes:
        st.caption(f":material/history: {phrase_deja_postule(precedentes, autre=True)}")

    nom_lettre = "Cover letter" if resultat.langue == "en" else "Lettre de motivation"
    col_lettre, col_cv = st.columns(2, gap="medium")
    with col_lettre:
        ui.feuille(production.chemin_lettre_pdf, f"lettre_{cle}",
                   legende=f"{nom_lettre}, {ui.statut_page('Lettre', production.lettre)}".rstrip(", "))
        with st.container(horizontal=True, gap="small"):
            ui.bouton_telechargement(production.chemin_lettre_pdf, "PDF", ui.MIME_PDF, f"dl_l_pdf_{eid}",
                                     icon=":material/download:")
            ui.bouton_telechargement(production.chemin_lettre_docx, "Word", ui.MIME_DOCX, f"dl_l_docx_{eid}",
                                     icon=":material/download:")
    with col_cv:
        ui.feuille(production.chemin_cv_pdf, f"cv_{cle}",
                   legende=f"CV adapté, {ui.statut_page('CV', production.cv)}".rstrip(", "))
        with st.container(horizontal=True, gap="small"):
            ui.bouton_telechargement(production.chemin_cv_pdf, "PDF", ui.MIME_PDF, f"dl_c_pdf_{eid}",
                                     icon=":material/download:")
            ui.bouton_telechargement(production.chemin_cv_docx, "Word", ui.MIME_DOCX, f"dl_c_docx_{eid}",
                                     icon=":material/download:")
    ui.alerte_pages("Lettre", production.lettre)
    ui.alerte_pages("CV", production.cv)

    entree = ui.entree_par_id(eid) or {}
    envoyee = False
    with st.container(horizontal=True, vertical_alignment="center", gap="small"):
        ui.bouton_ouvrir_dossier(dossier, f"ouvrir_{eid}")
        if suivi.statut(entree) in suivi.STATUTS_ENVOYES:
            badge = suivi.badge(suivi.statut(entree))
            envoi = ui.formater_date(entree.get("date_envoi", ""), avec_heure=False)
            st.markdown(f"{badge} le {envoi}" if envoi else badge)
        else:
            envoyee = st.button("Je l'ai envoyée", key=f"envoyee_{eid}", icon=":material/send:",
                                help="Facultatif : note la date d'envoi pour être prévenu quand il sera temps "
                                     "de relancer.")
    if envoyee:
        with ui.signaler_erreur_enregistrement():
            suivi.changer_statut(eid, "envoyee")
            st.toast("Candidature marquée comme envoyée", icon=":material/send:")
            st.rerun()

    details = []
    if production.methode_pdf:
        details.append(f"PDF créés avec {production.methode_pdf}")
    if resultat.modele:
        details.append(f"texte rédigé par {resultat.modele}")
    if details:
        texte = ", ".join(details)
        st.caption(texte[0].upper() + texte[1:] + ".")

    onglet_analyse, onglet_mail, onglet_retouches = st.tabs(
        [":material/insights: Analyse", ":material/mail: E-mail et texte", ":material/edit: Retouches"])
    with onglet_analyse:
        afficher_analyse(resultat)
    with onglet_mail:
        if resultat.email_corps:
            st.markdown("**E-mail d'accompagnement**")
            st.caption("Pense à joindre les deux PDF avant d'envoyer.")
            ui.bloc_mail(resultat.email_objet, resultat.email_corps, session.get("contact", ""))
        else:
            st.caption("Pas d'e-mail généré pour cette candidature.")
        st.markdown("**Texte de la lettre**")
        st.caption("Pour les sites qui demandent de coller la lettre dans un champ plutôt que de joindre le PDF.")
        st.code(ui.texte_lettre(resultat, stockage.charger_profil().get("nom", "")), language=None,
                wrap_lines=True)
    with onglet_retouches:
        afficher_retouches(session)


def generer(*, profil: dict, cv_choisi, annonce: str, entreprise_saisie: str, poste_saisi: str,
            entreprise_adresse: str, contact: str, consignes: str, langue: str, recherche: str) -> None:
    with st.status("Génération de ta candidature...", expanded=True) as etat:
        try:
            blocs = extraire_blocs(cv_choisi.chemin)
            langue_txt = " en anglais" if langue == "en" else ""
            etat.write(f":material/edit_note: Rédaction{langue_txt} par l'IA ({ai_client.modele_configure()})")
            resultat = generer_candidature(
                blocs_cv=blocs,
                texte_annonce=annonce,
                contexte_academique=recherches.reglages(profil, recherche)["contexte"],
                entreprise_indiquee=entreprise_saisie,
                poste_indique=poste_saisi,
                consignes_supplementaires=consignes,
                langue=langue,
                type_recherche=recherche,
            )
            etat.write(f":material/check: Contenu rédigé ({resultat.modele})")
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
            return
        except Exception as exc:  # noqa: BLE001
            etat.update(label="La création des fichiers a échoué", state="error", expanded=True)
            ui.afficher_erreur_production(exc)
            return
        entree = ui.entree_historique(resultat, production, dossier, identifiant)
        entree.update({
            "annonce": annonce.strip(),
            "url_offre": st.session_state.get("f_url", "").strip(),
            "contact": contact.strip(),
            "cv_reference": cv_choisi.nom,
            "recherche": recherche,
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
        etat.update(label=f"Candidature prête pour {resultat.entreprise}", state="complete", expanded=False)


# ----------------------------------------------------------------------------
# Page
# ----------------------------------------------------------------------------

profil = stockage.charger_profil()
cvs = stockage.lister_cvs()
recherche = ui.recherche_active()
type_recherche = recherches.recherche(recherche)
reglages = recherches.reglages(profil, recherche)
ui.entete("Nouvelle candidature",
          "Colle le lien ou le texte d'une offre : ta lettre et ton CV adapté sortent prêts à envoyer, "
          "chacun sur une page.", profil)

if not cvs:
    ui.etat_vide("cv", "Commence par importer ton CV",
                 "Ton CV Word sert de base à chaque candidature. Il n'est jamais modifié : l'app travaille sur "
                 "une copie.")
    with st.container(horizontal=True, horizontal_alignment="center"):
        st.page_link("vues/cv.py", label="Importer mon CV", icon=":material/upload_file:")
elif not ai_client.cle_api_presente():
    fournisseur = ai_client.fournisseur_actif()
    if fournisseur == "gemini":
        st.warning("Aucune clé d'IA configurée. Crée une clé gratuite sur aistudio.google.com/apikey, copie le "
                   "fichier .env.example en .env, colle la clé après GEMINI_API_KEY= puis relance l'app.",
                   icon=":material/key:")
    else:
        st.warning(f"Aucune clé {fournisseur} configurée. Copie .env.example en .env, ajoute ta clé puis relance "
                   "l'app.", icon=":material/key:")
else:
    a_relancer = suivi.candidatures_a_relancer(recherches.filtrer(stockage.charger_historique(), recherche))
    manquants = stockage.profil_incomplet(profil)
    if a_relancer or manquants or not reglages["contexte"]:
        with st.container(horizontal=True, gap="small", vertical_alignment="center", key="rappels"):
            if a_relancer:
                st.page_link("vues/candidatures.py", icon=":material/notifications_active:",
                             label=f"{ui.pluriel(len(a_relancer), 'candidature')} à relancer")
            if manquants:
                st.page_link("vues/profil.py", icon=":material/person_alert:",
                             label=f"Profil incomplet ({', '.join(manquants)}) : l'en-tête de la lettre le sera aussi")
            if not reglages["contexte"]:
                st.page_link("vues/profil.py", icon=":material/edit_note:",
                             label=f"Décris ta recherche ({type_recherche.libelle.lower()}) pour des lettres plus "
                                   "justes")

    col_offre, col_documents = st.columns([5, 6], gap="large")
    with col_offre:
        col_url, col_import = st.columns([4, 1.25], vertical_alignment="bottom")
        with col_url:
            st.text_input("Lien de l'offre", key="f_url",
                          placeholder="https://… (Welcome to the Jungle, HelloWork, site carrière…)")
        with col_import:
            st.button("Importer", on_click=importer_depuis_lien, width="stretch", icon=":material/download:",
                      help="Récupère le texte de l'offre et remplit le formulaire.")
        message_import = st.session_state.pop("import_message", None)
        if message_import:
            nature, texte = message_import
            {"success": lambda t: st.success(t, icon=":material/check_circle:"),
             "info": lambda t: st.info(t, icon=":material/info:")}.get(
                nature, lambda t: st.warning(t, icon=":material/link_off:"))(texte)

        col_a, col_b = st.columns(2)
        with col_a:
            entreprise_saisie = st.text_input("Entreprise", key="f_entreprise", placeholder="Détectée dans l'annonce")
        with col_b:
            poste_saisi = st.text_input("Poste", key="f_poste", placeholder="Détecté dans l'annonce")
        if entreprise_saisie.strip():
            deja = stockage.candidatures_precedentes(entreprise_saisie)
            if deja:
                st.caption(f":material/history: {phrase_deja_postule(deja)}")

        annonce = st.text_area("Texte de l'annonce", height=280, key="f_annonce", on_change=annonce_modifiee,
                               placeholder="Colle ici le texte complet de l'offre : missions, profil recherché…")

        noms_cvs = [cv.nom for cv in cvs]
        if st.session_state.get("cv_pour_recherche") != f"{recherche}|{reglages['cv']}":
            # Changement de recherche (ou de son CV par défaut, réglé dans le profil) : on part de ce CV.
            st.session_state["cv_pour_recherche"] = f"{recherche}|{reglages['cv']}"
            st.session_state["f_cv"] = reglages["cv"] if reglages["cv"] in noms_cvs else noms_cvs[0]
        if st.session_state.get("f_cv") not in noms_cvs:
            st.session_state.pop("f_cv", None)  # CV supprimé entre-temps : on repart du CV principal
        cv_choisi = cvs[0]
        col_cv, col_langue = st.columns(2)
        with col_cv:
            if len(cvs) > 1:
                nom_choisi = st.selectbox("CV de départ", noms_cvs, key="f_cv")
                cv_choisi = cvs[noms_cvs.index(nom_choisi)] if nom_choisi in noms_cvs else cvs[0]
            else:
                ui.fait("CV de départ", cv_choisi.nom)
        with col_langue:
            choix_langue = st.selectbox("Langue de la lettre", CHOIX_LANGUE, key="f_langue",
                                        help="Automatique : la langue de l'annonce.")
        langue = langue_de_la_lettre(choix_langue, annonce)
        if choix_langue == "Automatique" and annonce.strip() and langue == "en":
            st.caption(":material/translate: Annonce en anglais : la lettre et l'e-mail seront rédigés en anglais.")
        st.caption(f":material/{type_recherche.icone}: Candidature {type_recherche.libelle.lower()} : "
                   f"{type_recherche.resume}.")

        with st.expander("Options : adresse, e-mail du recruteur, ton, longueur", icon=":material/tune:"):
            col_c, col_d = st.columns(2)
            with col_c:
                entreprise_adresse = st.text_input(
                    "Adresse de l'entreprise", key="f_adresse",
                    help="Ex : 5 place de la Pyramide, 92800 Puteaux (présentée sur deux lignes dans la lettre).",
                )
                ton = st.selectbox("Ton de la lettre", list(TONS), key="f_ton")
            with col_d:
                contact = st.text_input("E-mail du recruteur", key="f_contact",
                                        help="Facultatif : prérempli dans l'e-mail d'accompagnement et les relances.")
                longueur = st.selectbox("Longueur de la lettre", list(LONGUEURS), key="f_longueur")
            remarques = st.text_input("Remarques pour l'IA", key="f_remarques",
                                      placeholder="Mets plus en avant mes projets en Python et SQL")

        with st.container(horizontal=True, gap="small"):
            lancer = st.button("Générer la candidature", type="primary", icon=":material/auto_awesome:")
            st.button("Nouvelle offre", on_click=vider_formulaire, icon=":material/restart_alt:",
                      help="Vide le formulaire pour passer à l'offre suivante. Le ton, la longueur, la langue et le "
                           "CV choisis sont gardés.")
        if lancer:
            generer(profil=profil, cv_choisi=cv_choisi, annonce=annonce, entreprise_saisie=entreprise_saisie,
                    poste_saisi=poste_saisi, entreprise_adresse=entreprise_adresse, contact=contact,
                    consignes=consignes_redaction(ton, longueur, remarques), langue=langue, recherche=recherche)

    with col_documents:
        derniere = st.session_state.get("derniere_candidature")
        if derniere:
            afficher_resultat(derniere)
        else:
            ui.etat_vide("feuilles", "Tes documents apparaîtront ici",
                         "Une lettre et un CV adaptés à l'offre, chacun sur une page, prêts à télécharger en PDF "
                         "ou en Word.")
