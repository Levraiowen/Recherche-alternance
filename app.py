"""
App de génération de candidatures (lettre de motivation + CV adapté) pour
les alternances. Lancement : streamlit run app.py (ou double-clic sur
Lancer.bat sous Windows).
"""

from __future__ import annotations

import hashlib
import io
import os
import subprocess
import sys
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

import streamlit as st  # noqa: E402
import streamlit.components.v1 as components  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).parent / ".env")

import ai_client  # noqa: E402
import stockage  # noqa: E402
from ai_client import ErreurGeneration, generer_candidature  # noqa: E402
from candidature import ResultatCandidature, produire_candidature, verifier_cv_reference  # noqa: E402
from cv_editor import extraire_blocs  # noqa: E402
from ia_commun import CORPS_LETTRE_MAX, CORPS_LETTRE_MIN, ResultatGeneration  # noqa: E402
from mise_en_page import ResultatMiseEnPage, lignes_en_trop_estimees  # noqa: E402
from pdf_export import ErreurConversionPDF  # noqa: E402
from version import VERSION  # noqa: E402

MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
MIME_PDF = "application/pdf"
TAILLE_PAGE_HISTORIQUE = 15

st.set_page_config(page_title="Candidatures alternance", page_icon="📄", layout="wide")


# ----------------------------------------------------------------------------
# Petits utilitaires d'affichage
# ----------------------------------------------------------------------------


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
    if chemin is None or not chemin.exists():
        return False
    if _streamlit_recent():
        # Fichier lu seulement au clic, et pas de rechargement de la page
        # après le téléchargement (les retouches en cours restent affichées).
        st.download_button(libelle, data=lambda: chemin.read_bytes(), file_name=chemin.name,
                           mime=mime, key=cle, on_click="ignore")
    else:
        st.download_button(libelle, data=chemin.read_bytes(), file_name=chemin.name, mime=mime, key=cle)
    return True


def ouvrir_dossier(dossier: Path) -> None:
    """Ouvre le dossier dans l'explorateur de fichiers (l'app tourne en local)."""
    if os.name == "nt":
        os.startfile(dossier)  # type: ignore[attr-defined]  # noqa: S606
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(dossier)])
    else:
        subprocess.Popen(["xdg-open", str(dossier)])


def bouton_ouvrir_dossier(dossier: Path | None, cle: str) -> None:
    if dossier is None or not dossier.exists():
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

        document = pdfium.PdfDocument(chemin)
        page = document[0]
        echelle = 2 * largeur / page.get_size()[0]  # rendu 2x : net sur les écrans haute densité
        image = page.render(scale=echelle).to_pil().convert("RGB")
        document.close()
        ImageDraw.Draw(image).rectangle([0, 0, image.width - 1, image.height - 1], outline=(200, 200, 200), width=2)
        tampon = io.BytesIO()
        image.save(tampon, format="PNG", optimize=True)
        return tampon.getvalue()
    except Exception:  # noqa: BLE001 - un aperçu raté ne doit rien bloquer
        return None


def apercu_pdf(chemin: Path | None, largeur: int = 420) -> None:
    if chemin is None or not chemin.exists():
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
            + ("Raccourcis un peu ton CV de référence (onglet « Mon CV »)."
               if nom == "CV" else "Raccourcis un paragraphe dans la zone de retouche ci-dessous.")
        )


def formater_date(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d/%m/%Y à %H:%M")
    except (TypeError, ValueError):
        return iso or ""


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
    }


def afficher_erreur_production(exc: Exception) -> None:
    if isinstance(exc, PermissionError):
        st.error(
            "Impossible d'écrire un des fichiers : il est sans doute ouvert dans un autre "
            f"programme (Word, lecteur PDF...). Ferme-le puis réessaie.\n\nDétail : {exc}"
        )
    else:
        st.error(f"Erreur pendant la création des fichiers : {exc}")


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
    components.html("<script>window.close();</script>", height=0)
    time.sleep(0.6)
    os._exit(0)

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

onglet_candidature, onglet_historique, onglet_cv, onglet_profil = st.tabs(
    ["✉️ Nouvelle candidature", "🕓 Historique", "📎 Mon CV", "👤 Mon profil"]
)

# ----------------------------------------------------------------------------
# Onglet : Nouvelle candidature
# ----------------------------------------------------------------------------


def afficher_resultat_et_retouches() -> None:
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
        st.success(f"Candidature prête dans `{dossier_affiche}`")

    ligne_statut_page("Lettre", production.lettre)
    ligne_statut_page("CV", production.cv)
    details = [f"PDF : {production.methode_pdf}" if production.methode_pdf else "",
               f"IA : {resultat.modele}" if resultat.modele else ""]
    st.caption(" · ".join(d for d in details if d))

    precedentes = stockage.candidatures_precedentes(resultat.entreprise, sauf=eid)
    if precedentes:
        dates = ", ".join(formater_date(e.get("date", "")).split(" à ")[0] for e in precedentes[:5])
        st.info(f"ℹ️ Tu as déjà généré {len(precedentes)} candidature(s) pour **{resultat.entreprise}** ({dates}).")

    col_lettre, col_cv = st.columns(2)
    with col_lettre:
        st.markdown("**Lettre de motivation**")
        c1, c2, _ = st.columns([1, 1, 3])
        with c1:
            bouton_telechargement(production.chemin_lettre_pdf, "⬇️ PDF", MIME_PDF, f"dl_l_pdf_{eid}")
        with c2:
            bouton_telechargement(production.chemin_lettre_docx, "⬇️ Word", MIME_DOCX, f"dl_l_docx_{eid}")
        apercu_pdf(production.chemin_lettre_pdf)
    with col_cv:
        st.markdown("**CV adapté**")
        c1, c2, _ = st.columns([1, 1, 3])
        with c1:
            bouton_telechargement(production.chemin_cv_pdf, "⬇️ PDF", MIME_PDF, f"dl_c_pdf_{eid}")
        with c2:
            bouton_telechargement(production.chemin_cv_docx, "⬇️ Word", MIME_DOCX, f"dl_c_docx_{eid}")
        apercu_pdf(production.chemin_cv_pdf)
    bouton_ouvrir_dossier(dossier, f"ouvrir_{eid}")

    # --- Relecture / retouches -------------------------------------------
    st.subheader("✏️ Relire et retoucher avant d'envoyer")
    st.caption(
        "Modifie librement le texte ci-dessous puis clique sur « Mettre à jour les fichiers » : "
        "la lettre et le CV sont régénérés (Word + PDF sur 1 page) sans rappeler l'IA."
    )
    objet = st.text_input("Objet", value=resultat.objet, key=f"ed_objet_{eid}")
    appel = st.text_input("Formule d'appel", value=resultat.formule_appel, key=f"ed_appel_{eid}")
    paragraphes = []
    for i, texte in enumerate(resultat.paragraphes):
        paragraphes.append(st.text_area(f"Paragraphe {i + 1}", value=texte, height=130, key=f"ed_p{i}_{eid}"))
    politesse = st.text_area("Formule de politesse", value=resultat.formule_politesse, height=70,
                             key=f"ed_politesse_{eid}")
    longueur = sum(len(p) for p in paragraphes)
    indication = "✅" if longueur <= CORPS_LETTRE_MAX + 150 else "⚠️ un peu long : la mise en page sera resserrée"
    st.caption(f"Corps de la lettre : {longueur} caractères (cible {CORPS_LETTRE_MIN}–{CORPS_LETTRE_MAX}) {indication}")

    st.markdown("**Modifications du CV**")
    blocs_avant = session["blocs_avant"]
    nouvelles_adaptations: dict[str, str] = {}
    if not resultat.cv_adaptations:
        st.info("Aucune adaptation proposée : le CV collait déjà bien à l'offre.")
    for bid, texte in resultat.cv_adaptations.items():
        if " ".join(texte.split()) == " ".join(blocs_avant.get(bid, "").split()):
            continue  # proposition identique au CV d'origine : rien à montrer
        raison = production.adaptations.ignores.get(bid)
        with st.container(border=True):
            actif = st.checkbox(
                f"Appliquer la modification du bloc [{bid}]",
                value=raison is None,
                key=f"ed_cv_on_{bid}_{eid}",
            )
            if raison:
                st.caption(f"⚠️ Non appliquée lors de la génération : {raison}.")
            st.caption("Avant :")
            st.text(blocs_avant.get(bid, "(bloc introuvable dans le CV)"))
            nouveau = st.text_area("Après :", value=texte, height=90, key=f"ed_cv_txt_{bid}_{eid}")
            if actif:
                nouvelles_adaptations[bid] = nouveau

    if st.button("♻️ Mettre à jour les fichiers avec mes retouches", type="primary", key=f"maj_{eid}"):
        modifie = replace(
            resultat,
            objet=objet,
            formule_appel=appel,
            paragraphes=[p for p in paragraphes if p.strip()],
            formule_politesse=politesse,
            cv_adaptations=nouvelles_adaptations,
        )
        try:
            with st.spinner("Régénération des fichiers et mise en page sur 1 page..."):
                nouvelle_production = produire_candidature(
                    resultat=modifie, profil=stockage.charger_profil(),
                    entreprise_adresse=session["entreprise_adresse"], dossier=dossier,
                )
        except Exception as exc:  # noqa: BLE001
            afficher_erreur_production(exc)
        else:
            maj = entree_historique(modifie, nouvelle_production, dossier, eid)
            maj.pop("date")  # garder la date de création d'origine
            stockage.mettre_a_jour_historique(eid, maj)
            session["resultat"] = modifie
            session["production"] = nouvelle_production
            st.toast("Fichiers mis à jour ✅")
            st.rerun()


with onglet_candidature:
    profil = stockage.charger_profil()
    if not stockage.cv_present():
        st.warning("Importe d'abord ton CV dans l'onglet « 📎 Mon CV ».")
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
        manquants = stockage.profil_incomplet(profil)
        if manquants:
            st.info(
                f"ℹ️ Profil incomplet ({', '.join(manquants)}) : l'en-tête de la lettre le sera aussi. "
                "Complète-le dans l'onglet « 👤 Mon profil »."
            )

        col_a, col_b = st.columns(2)
        with col_a:
            entreprise_saisie = st.text_input("Nom de l'entreprise (optionnel)")
            poste_saisi = st.text_input("Intitulé du poste (optionnel)")
        with col_b:
            entreprise_adresse = st.text_input(
                "Adresse de l'entreprise (optionnel)",
                help="Ex : « 5 place de la Pyramide, 92800 Puteaux » (présentée sur deux lignes dans la lettre).",
            )
            consignes = st.text_input(
                "Remarques pour l'IA (optionnel)",
                help="Ex : « mets plus en avant mes compétences en Python et SQL »",
            )

        if entreprise_saisie.strip():
            deja = stockage.candidatures_precedentes(entreprise_saisie)
            if deja:
                st.caption(
                    f"ℹ️ Déjà {len(deja)} candidature(s) générée(s) pour cette entreprise "
                    f"(dernière le {formater_date(deja[0].get('date', ''))})."
                )

        annonce = st.text_area("Colle le texte de l'annonce ici", height=280)

        if st.button("✨ Générer la candidature (PDF direct)", type="primary"):
            blocs = extraire_blocs(stockage.FICHIER_CV)
            try:
                with st.spinner(f"Rédaction par l'IA ({ai_client.modele_configure()})..."):
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
                try:
                    with st.spinner("Création des fichiers Word et PDF (mise en page sur 1 page)..."):
                        production = produire_candidature(
                            resultat=resultat, profil=profil,
                            entreprise_adresse=entreprise_adresse, dossier=dossier,
                        )
                except Exception as exc:  # noqa: BLE001
                    afficher_erreur_production(exc)
                else:
                    stockage.ajouter_historique(entree_historique(resultat, production, dossier, identifiant))
                    st.session_state["derniere_candidature"] = {
                        "id": identifiant,
                        "resultat": resultat,
                        "production": production,
                        "dossier": dossier,
                        "entreprise_adresse": entreprise_adresse,
                        "blocs_avant": {b.id: b.texte for b in blocs},
                    }

        afficher_resultat_et_retouches()

# ----------------------------------------------------------------------------
# Onglet : Historique
# ----------------------------------------------------------------------------
with onglet_historique:
    historique = stockage.charger_historique()
    if not historique:
        st.info("Aucune candidature générée avec l'app pour le moment.")
    else:
        recherche = st.text_input("🔎 Rechercher (entreprise ou poste)", key="h_recherche")
        if recherche.strip():
            cible = stockage.normaliser_nom(recherche)
            historique = [
                e for e in historique
                if cible in stockage.normaliser_nom(f"{e.get('entreprise', '')} {e.get('poste', '')}")
            ]
        nb_affiches = st.session_state.get("h_nb_affiches", TAILLE_PAGE_HISTORIQUE)
        st.caption(f"{len(historique)} candidature(s)")

        for rang, entree in enumerate(historique[:nb_affiches]):
            eid = stockage.identifiant_entree(entree)
            cle = f"{rang}_{eid}"  # rang inclus : clés uniques même si deux anciennes entrées se ressemblent
            with st.container(border=True):
                col_titre, col_suppr = st.columns([8, 1], vertical_alignment="center")
                with col_titre:
                    st.markdown(f"**{entree.get('entreprise', '?')}** — {entree.get('poste') or 'poste non précisé'}")
                    infos = [formater_date(entree.get("date", ""))]
                    if entree.get("methode_pdf"):
                        infos.append(f"PDF via {entree['methode_pdf']}")
                    st.caption(" · ".join(infos))
                with col_suppr:
                    if st.button("🗑️", key=f"h_suppr_{cle}",
                                 help="Retire cette candidature de la liste (les fichiers restent dans outputs/)."):
                        stockage.supprimer_historique(eid)
                        st.rerun()

                c1, c2, c3 = st.columns([2, 2, 1])
                with c1:
                    st.caption("Lettre de motivation")
                    t1 = bouton_telechargement(stockage.resoudre_chemin(entree.get("lettre_pdf")),
                                               "⬇️ PDF", MIME_PDF, f"h_l_pdf_{cle}")
                    t2 = bouton_telechargement(
                        stockage.resoudre_chemin(entree.get("lettre_docx") or entree.get("lettre")),
                        "⬇️ Word", MIME_DOCX, f"h_l_docx_{cle}")
                    if not (t1 or t2):
                        st.caption("Fichiers introuvables (déplacés ou supprimés).")
                with c2:
                    st.caption("CV adapté")
                    t1 = bouton_telechargement(stockage.resoudre_chemin(entree.get("cv_pdf")),
                                               "⬇️ PDF", MIME_PDF, f"h_c_pdf_{cle}")
                    t2 = bouton_telechargement(
                        stockage.resoudre_chemin(entree.get("cv_docx") or entree.get("cv")),
                        "⬇️ Word", MIME_DOCX, f"h_c_docx_{cle}")
                    if not (t1 or t2):
                        st.caption("Fichiers introuvables (déplacés ou supprimés).")
                with c3:
                    dossier_entree = stockage.resoudre_chemin(entree.get("dossier"))
                    if dossier_entree is None:
                        fichier = stockage.resoudre_chemin(entree.get("lettre_docx") or entree.get("lettre"))
                        dossier_entree = fichier.parent if fichier else None
                    bouton_ouvrir_dossier(dossier_entree, f"h_ouvrir_{cle}")

        if len(historique) > nb_affiches:
            if st.button(f"Afficher {min(TAILLE_PAGE_HISTORIQUE, len(historique) - nb_affiches)} de plus"):
                st.session_state["h_nb_affiches"] = nb_affiches + TAILLE_PAGE_HISTORIQUE
                st.rerun()

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
        nom_original = profil_actuel.get("_cv_nom_original", "cv_original.docx")
        importe_le = formater_date(profil_actuel.get("_cv_importe_le", ""))
        st.success(f"CV enregistré : **{nom_original}**" + (f" (importé le {importe_le})." if importe_le else "."))
    else:
        st.warning("Aucun CV importé pour le moment.")

    fichier = st.file_uploader("Remplacer / importer le CV (.docx uniquement)", type=["docx"])
    if fichier is not None:
        contenu = fichier.getvalue()
        signature = hashlib.sha256(contenu).hexdigest()  # chaque fichier importé n'est traité qu'une fois
        if st.session_state.get("cv_importe") != signature:
            try:
                from docx import Document

                Document(io.BytesIO(contenu))  # vérifie que c'est bien un .docx lisible
            except Exception:  # noqa: BLE001
                st.error("Ce fichier n'est pas un document Word (.docx) valide : il n'a pas été enregistré.")
            else:
                stockage.enregistrer_cv(contenu, fichier.name)
                st.session_state["cv_importe"] = signature
                st.session_state.pop("verif_cv", None)
                st.success(f"CV « {fichier.name} » enregistré comme nouvelle référence.")

    if stockage.cv_present():
        blocs = extraire_blocs(stockage.FICHIER_CV)
        with st.expander(f"Voir le texte détecté dans le CV ({len(blocs)} blocs)"):
            if not blocs:
                st.warning(
                    "Aucun texte détecté. Le CV utilise peut-être des zones de texte "
                    "ou des images plutôt que des paragraphes Word standards "
                    "(voir la limite connue dans le README)."
                )
            st.caption("🔒 = bloc jamais modifié par l'IA (coordonnées, liens, titres de section).")
            for b in blocs:
                st.text(f"{'' if b.modifiable else '🔒 '}[{b.id}] {b.texte}")

        st.markdown("**Mise en page**")
        st.caption(
            "Chaque CV généré est automatiquement ajusté pour tenir sur une seule page. "
            "Ce test vérifie ton CV de référence tel quel et mémorise le réglage pour accélérer "
            "les prochaines candidatures."
        )
        if st.button("🧪 Vérifier que mon CV tient sur une page"):
            try:
                with st.spinner("Conversion en PDF et vérification..."):
                    verif = verifier_cv_reference(stockage.DOSSIER_OUTPUTS / "_verification_cv")
            except ErreurConversionPDF as exc:
                st.error(str(exc))
            else:
                st.session_state["verif_cv"] = verif
        verif = st.session_state.get("verif_cv")
        if verif is not None:
            if verif.une_page and verif.niveau == 0:
                st.success(f"✅ Ton CV tient sur une page tel quel (PDF via {verif.methode}).")
            elif verif.une_page:
                st.info(
                    f"✅ Ton CV tient sur une page avec un léger resserrement ({verif.description}), "
                    f"appliqué automatiquement à chaque candidature (PDF via {verif.methode})."
                )
            else:
                st.warning(
                    f"⚠️ Même resserré au maximum, ton CV fait {verif.pages} pages (environ "
                    f"{lignes_en_trop_estimees(verif)} ligne(s) de trop) : raccourcis-le un peu."
                )
            apercu_pdf(verif.chemin_pdf, largeur=480)

    st.info(
        "⚠️ Limite connue : seuls les paragraphes et tableaux Word « standards » "
        "sont détectés. Le texte dans des zones de texte, images ou SmartArt "
        "n'est pas modifié. Relis toujours le CV généré avant de l'envoyer."
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
            stockage.enregistrer_profil(
                {
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
                }
            )
            st.success("Profil enregistré.")
