"""Test de l'interface Streamlit de bout en bout (sans appel réel à l'IA) :
génération, lettre en anglais, retouches, navigation entre les pages, suivi,
relances, fiche d'une candidature, rapport, CV et profil."""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest
from docx import Document
from streamlit.testing.v1 import AppTest

import ai_client
import import_offre
import interface
import stockage
from conftest import construire_cv_exemple
from ia_commun import ResultatGeneration
from import_offre import OffreImportee

APP = Path(__file__).resolve().parent.parent / "app.py"
CANDIDATURES = "vues/candidatures.py"
ANNONCE = "Nous recherchons un alternant Data Analyst (SQL, Power BI). " * 3
ANNONCE_EN = ("We are looking for a Data Analyst apprentice to join our team. You will build dashboards with "
              "Power BI and analyse data with SQL and Python. The position is based in Paris and you will work "
              "with the sales teams on a weekly basis.")


def _fausse_generation(**kwargs) -> ResultatGeneration:
    return ResultatGeneration(
        entreprise=kwargs.get("entreprise_indiquee") or "Exemple & Fils",
        poste="Data Analyst",
        objet="Candidature au poste de Data Analyst en alternance",
        formule_appel="Madame, Monsieur,",
        paragraphes=["Premier paragraphe. " * 10, "Deuxième paragraphe. " * 10, "Troisième paragraphe. " * 10],
        formule_politesse="Je vous prie d'agréer, Madame, Monsieur, mes salutations distinguées.",
        cv_adaptations={"t0_r0_c0_p1": "Recherche alternance Data Analyst", "p999": "bloc inexistant"},
        modele="modele-de-test",
        email_objet="Candidature Data Analyst",
        email_corps="Madame, Monsieur,\nVeuillez trouver ci-joint...",
        score=72,
        points_forts=["SQL et Python"],
        mots_cles_manquants=["Tableau"],
        langue=kwargs.get("langue", "fr"),
    )


def _faux_json(*, systeme, message, schema):
    proprietes = schema.get("properties", {})
    if "paragraphe" in proprietes:
        return {"paragraphe": "Paragraphe réécrit par l'IA."}, "modele-de-test"
    if "pitch" in proprietes:
        return {"pitch": "Je suis Camille.", "a_savoir": ["Leader"], "questions": [
            {"question": "Pourquoi nous ?", "piste": "Parce que."}], "a_mettre_en_avant": ["SQL"],
            "questions_a_poser": ["Quelle équipe ?"]}, "modele-de-test"
    return {"objet": "Relance", "corps": "Bonjour, je me permets de revenir vers vous."}, "modele-de-test"


@pytest.fixture
def appels_ia(monkeypatch):
    """Paramètres reçus par la (fausse) génération."""
    appels: list[dict] = []

    def generation(**kwargs):
        appels.append(kwargs)
        return _fausse_generation(**kwargs)

    monkeypatch.setattr(ai_client, "generer_candidature", generation)
    return appels


@pytest.fixture
def app(projet_temporaire, monkeypatch, appels_ia):
    stockage.DOSSIER_DATA.mkdir(parents=True)
    construire_cv_exemple(stockage.FICHIER_CV)
    stockage.enregistrer_profil({**stockage.PROFIL_PAR_DEFAUT, "nom": "Camille Martin", "adresse": "1 rue X",
                                 "code_postal": "69001", "ville": "Lyon", "telephone": "0600000000",
                                 "email": "c@example.com"})
    monkeypatch.setenv("FOURNISSEUR_IA", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "cle-de-test")
    monkeypatch.setattr(ai_client, "generer_json", _faux_json)
    test = AppTest.from_file(str(APP), default_timeout=180)
    test.run()
    assert not test.exception
    return test


def _bouton(test: AppTest, libelle: str):
    return next(b for b in test.button if b.label == libelle)


def _textes(test: AppTest) -> str:
    """Tout le texte affiché (markdown, légendes, alertes), pour les vérifications."""
    morceaux = [e.value for e in (*test.markdown, *test.caption, *test.info, *test.success, *test.warning,
                                  *test.error, *test.subheader)]
    return "\n".join(str(m) for m in morceaux)


def _liens(test: AppTest) -> list[str]:
    return [lien.proto.label for lien in test.get("page_link")]


def _generer(app: AppTest, entreprise: str = "Exemple & Fils", annonce: str = ANNONCE) -> None:
    app.text_input(key="f_entreprise").set_value(entreprise)
    app.text_area(key="f_annonce").set_value(annonce)
    app.run()
    _bouton(app, "Générer la candidature").click().run()
    assert not app.exception


def _ouvrir_fiche(app: AppTest, identifiant: str) -> None:
    app.switch_page(CANDIDATURES).run()
    app.button(key=f"sel_{interface.cle_css(identifiant)}").click().run()
    assert not app.exception


def test_generation_retouche_et_doublon(app: AppTest, appels_ia):
    _generer(app)
    assert appels_ia[-1]["langue"] == "fr"  # annonce en français : lettre en français
    historique = json.loads(stockage.FICHIER_HISTORIQUE.read_text(encoding="utf-8"))
    assert len(historique) == 1 and historique[0]["entreprise"] == "Exemple & Fils"
    assert historique[0]["score"] == 72 and historique[0]["annonce"].startswith("Nous recherchons")
    assert historique[0]["langue"] == "fr"
    lettre = stockage.resoudre_chemin(historique[0]["lettre_docx"])
    assert lettre.exists() and lettre.name == "Lettre_Motivation_Camille_Martin_(Exemple & Fils).docx"
    textes = _textes(app)
    assert "bloc introuvable" in textes
    assert "72&nbsp;%" in textes  # analyse de correspondance
    assert any("Veuillez trouver ci-joint" in c.value for c in app.code)  # e-mail copiable

    # Reformulation d'un paragraphe par l'IA, puis régénération des fichiers
    _bouton(app, "Reformuler").click().run()
    assert not app.exception
    assert app.text_area(key=f"ed_p0_{historique[0]['id']}").value == "Paragraphe réécrit par l'IA."
    _bouton(app, "Mettre à jour les fichiers").click().run()
    assert not app.exception
    assert any("Paragraphe réécrit par l’IA" in p.text for p in Document(str(lettre)).paragraphs)

    # Marquer comme envoyée (facultatif)
    _bouton(app, "Je l'ai envoyée").click().run()
    assert stockage.charger_historique()[0]["statut"] == "envoyee"

    # Deuxième candidature pour la même entreprise : doublon signalé
    _bouton(app, "Générer la candidature").click().run()
    assert "Une autre candidature a déjà été préparée pour cette entreprise" in _textes(app)


def test_lettre_en_anglais(app: AppTest, appels_ia):
    # Langue « Automatique » : une annonce en anglais donne une lettre en anglais
    app.text_area(key="f_annonce").set_value(ANNONCE_EN).run()
    assert "Annonce en anglais" in _textes(app)
    _generer(app, "Nova Energy", ANNONCE_EN)
    assert appels_ia[-1]["langue"] == "en"
    entree = stockage.charger_historique()[0]
    assert entree["langue"] == "en"
    lettre = stockage.resoudre_chemin(entree["lettre_docx"])
    assert lettre.name == "Cover_Letter_Camille_Martin_(Nova Energy).docx"
    paragraphes = [p.text for p in Document(str(lettre)).paragraphs]
    assert any(p.startswith("Subject: ") for p in paragraphes)
    assert "Lettre en anglais" in _textes(app)

    # Choix forcé : la langue demandée l'emporte sur celle de l'annonce
    app.selectbox(key="f_langue").set_value("Français").run()
    _bouton(app, "Générer la candidature").click().run()
    assert appels_ia[-1]["langue"] == "fr"


def test_navigation_garde_le_formulaire_et_les_retouches(app: AppTest):
    _generer(app)
    eid = stockage.charger_historique()[0]["id"]
    app.text_area(key=f"ed_p0_{eid}").set_value("Mon paragraphe retouché.").run()
    app.text_input(key="f_remarques").set_value("Insiste sur SQL").run()
    for page in ("vues/cv.py", CANDIDATURES, "vues/profil.py"):
        app.switch_page(page).run()
        assert not app.exception, page
    app.switch_page("vues/nouvelle_candidature.py").run()
    assert not app.exception
    assert app.text_area(key="f_annonce").value == ANNONCE
    assert app.text_input(key="f_remarques").value == "Insiste sur SQL"
    assert app.text_area(key=f"ed_p0_{eid}").value == "Mon paragraphe retouché."


def test_suivi_relance_et_entretien(app: AppTest):
    il_y_a_15_jours = (date.today() - timedelta(days=15)).isoformat()
    stockage.ajouter_historique({"id": "ancienne", "date": f"{il_y_a_15_jours}T10:00:00", "entreprise": "Ancienne SA",
                                 "poste": "Analyste", "statut": "envoyee", "date_envoi": il_y_a_15_jours,
                                 "annonce": "Annonce mémorisée"})
    app.run()
    assert "1 candidature à relancer" in _liens(app)
    app.switch_page(CANDIDATURES).run()
    assert not app.exception
    _bouton(app, "Rédiger la relance").click().run()
    assert not app.exception and any("revenir vers vous" in c.value for c in app.code)
    _bouton(app, "Marquer comme relancée").click().run()
    assert stockage.charger_historique()[0]["statut"] == "relancee"

    app.button(key=f"sel_{interface.cle_css('ancienne')}").click().run()
    _bouton(app, "Préparer l'entretien").click().run()
    assert not app.exception
    assert "Pourquoi nous ?" in stockage.charger_historique()[0]["fiche_entretien"]

    # Changement de statut depuis la fiche
    app.selectbox(key=f"h_statut_{interface.cle_css('ancienne')}").set_value("entretien").run()
    assert stockage.charger_historique()[0]["statut"] == "entretien"
    assert stockage.charger_historique()[0]["date_reponse"] == date.today().isoformat()


def test_statut_affiche_suit_les_changements_faits_ailleurs(app: AppTest):
    il_y_a_15_jours = (date.today() - timedelta(days=15)).isoformat()
    stockage.ajouter_historique({"id": "e0", "date": f"{il_y_a_15_jours}T10:00:00", "entreprise": "Ent 0",
                                 "poste": "Analyste", "statut": "envoyee", "date_envoi": il_y_a_15_jours})
    _ouvrir_fiche(app, "e0")
    cle = f"h_statut_{interface.cle_css('e0')}"
    assert app.selectbox(key=cle).value == "envoyee"
    _bouton(app, "Marquer comme relancée").click().run()  # depuis le panneau des relances
    assert not app.exception
    assert app.selectbox(key=cle).value == "relancee"


def test_liste_recherche_filtre_et_fermeture_de_la_fiche(app: AppTest):
    for i, (nom, statut) in enumerate((("Alpha", "envoyee"), ("Beta", ""), ("Gamma", "refusee"))):
        stockage.ajouter_historique({"id": f"l{i}", "date": f"2026-11-1{i}T10:00:00", "entreprise": nom,
                                     "poste": "Data", "statut": statut, "date_envoi": "2026-11-15" if statut else ""})
    app.switch_page(CANDIDATURES).run()
    lignes = [b.label for b in app.button if b.key and b.key.startswith("sel_")]
    assert lignes == ["Gamma", "Beta", "Alpha"]  # plus récentes en premier
    app.text_input(key="h_recherche").set_value("alp").run()
    assert [b.label for b in app.button if b.key and b.key.startswith("sel_")] == ["Alpha"]
    app.text_input(key="h_recherche").set_value("").run()
    app.button_group(key="h_filtre").set_value(["refusee"]).run()
    assert [b.label for b in app.button if b.key and b.key.startswith("sel_")] == ["Gamma"]
    app.button(key=f"sel_{interface.cle_css('l2')}").click().run()
    assert "Vue d'ensemble" not in _textes(app)
    _bouton(app, "Vue d'ensemble").click().run()
    assert "Vue d'ensemble" in _textes(app) and "candidature_ouverte" not in app.session_state


def test_rapport_et_export(app: AppTest):
    stockage.ajouter_historique({"id": "r1", "date": "2026-11-02T10:00:00", "entreprise": "Rapport SA",
                                 "poste": "Data", "statut": "entretien", "date_envoi": "2026-11-03",
                                 "date_reponse": "2026-11-10"})
    app.switch_page(CANDIDATURES).run()
    libelles = [b.proto.label for b in app.get("download_button")]
    assert "Télécharger le rapport" in libelles and "Exporter pour Excel" in libelles
    assert "1 candidature préparée, 1 envoyée, 1 réponse (100\u00a0%) et 1 entretien." in _textes(app)
    app.selectbox(key="r_periode").set_value("Personnalisée").run()
    assert not app.exception and app.date_input(key="r_plage")
    app.date_input(key="r_plage").set_value((date(2026, 10, 1), date(2026, 10, 31))).run()
    assert "Aucune candidature sur cette période." in _textes(app)


def test_texte_de_la_lettre_et_nouvelle_offre(app: AppTest):
    _generer(app)
    texte = next(c.value for c in app.code if c.value.startswith("Madame, Monsieur,\n\nPremier paragraphe"))
    assert texte.endswith("Camille Martin")  # lettre en texte brut, signée
    _bouton(app, "Nouvelle offre").click().run()
    assert not app.exception
    assert app.text_area(key="f_annonce").value == "" and app.text_input(key="f_entreprise").value == ""
    assert "Tes documents apparaîtront ici" in _textes(app)  # résultat précédent masqué


def test_import_ne_garde_pas_les_champs_de_l_offre_precedente(app: AppTest, monkeypatch):
    offres = {
        "https://offres.exemple.org/a": OffreImportee(texte="Offre A. " * 20, entreprise="Alpha", poste="Data Analyst",
                                                      adresse="1 rue A, 69001 Lyon", structuree=True),
        "https://offres.exemple.org/b": OffreImportee(texte="Offre B. " * 20, entreprise="", poste="", adresse="",
                                                      structuree=False),
    }
    monkeypatch.setattr(import_offre, "importer_offre", lambda url: offres[url])
    app.text_input(key="f_url").set_value("https://offres.exemple.org/a").run()
    _bouton(app, "Importer").click().run()
    assert app.text_input(key="f_poste").value == "Data Analyst"
    app.text_input(key="f_contact").set_value("rh@alpha.example").run()
    _bouton(app, "Générer la candidature").click().run()
    assert not app.exception

    # Offre B (sans données structurées) : rien de l'offre A ne doit rester
    app.text_input(key="f_url").set_value("https://offres.exemple.org/b").run()
    _bouton(app, "Importer").click().run()
    assert app.text_area(key="f_annonce").value.startswith("Offre B.")
    for cle in ("f_entreprise", "f_poste", "f_adresse", "f_contact"):
        assert app.text_input(key=cle).value == "", cle

    # Ce que l'utilisateur tape lui-même pour l'offre en cours n'est jamais effacé
    app.text_input(key="f_entreprise").set_value("Beta").run()
    _bouton(app, "Importer").click().run()
    assert app.text_input(key="f_entreprise").value == "Beta"


def test_cv_supplementaire_choix_et_suppression_confirmee(app: AppTest):
    stockage.DOSSIER_CVS.mkdir(parents=True, exist_ok=True)
    construire_cv_exemple(stockage.DOSSIER_CVS / "CV Marketing.docx")
    app.run()
    assert "CV Marketing" in app.selectbox(key="f_cv").options  # choix du CV de départ
    app.selectbox(key="f_cv").set_value("CV Marketing").run()
    app.switch_page("vues/cv.py").run()
    assert not app.exception
    _bouton(app, "Oui, supprimer").click().run()  # bouton placé dans la fenêtre de confirmation
    assert not app.exception
    assert not (stockage.DOSSIER_CVS / "CV Marketing.docx").exists()
    assert stockage.FICHIER_CV.exists()  # le CV principal n'est jamais supprimé
    app.switch_page("vues/nouvelle_candidature.py").run()  # le CV choisi n'existe plus : aucun plantage
    assert not app.exception


def test_notes_et_date_d_envoi(app: AppTest):
    stockage.ajouter_historique({"id": "n1", "date": "2026-11-02T10:00:00", "entreprise": "Notes SA", "poste": "Data"})
    _ouvrir_fiche(app, "n1")
    next(d for d in app.date_input if d.label == "Date d'envoi").set_value(date(2026, 11, 3))
    next(t for t in app.text_area if t.label == "Notes").set_value("Contact : Mme Exemple")
    _bouton(app, "Enregistrer").click().run()
    assert not app.exception
    entree = stockage.charger_historique()[0]
    assert entree["date_envoi"] == "2026-11-03" and entree["notes"] == "Contact : Mme Exemple"
    assert entree["statut"] == "envoyee"  # une date d'envoi suffit à la compter comme envoyée


def test_profil_et_apercu_de_l_en_tete(app: AppTest):
    app.switch_page("vues/profil.py").run()
    assert not app.exception
    next(t for t in app.text_input if t.label == "Ville").set_value("Nanterre")
    _bouton(app, "Enregistrer mon profil").click().run()
    assert not app.exception
    assert stockage.charger_profil()["ville"] == "Nanterre"
    assert "Nanterre, le " in _textes(app)  # aperçu de l'en-tête mis à jour tout de suite


def test_mise_a_jour_pendant_que_l_app_tourne(app: AppTest, monkeypatch):
    import version

    monkeypatch.setattr(version, "VERSION", "ancienne-version")  # modules restés en mémoire
    app.run()
    assert not app.exception
    assert [t.value for t in app.title] == ["Mise à jour installée"]  # rien d'autre tant que l'app n'est pas relancée


def _textes_cv(entree: dict) -> str:
    document = Document(str(stockage.resoudre_chemin(entree["cv_docx"])))
    return " ".join(c.text for t in document.tables for r in t.rows for c in r.cells)


def _paragraphes_lettre(entree: dict) -> list[str]:
    return [p.text for p in Document(str(stockage.resoudre_chemin(entree["lettre_docx"]))).paragraphs]


def test_retouches_rien_n_est_perdu_apres_mise_a_jour(app: AppTest):
    _generer(app)
    eid = stockage.charger_historique()[0]["id"]
    # Paragraphe 2 vidé : retiré de la lettre, mais les 3 zones restent affichées
    app.text_area(key=f"ed_p1_{eid}").set_value("")
    _bouton(app, "Mettre à jour les fichiers").click().run()
    assert not app.exception
    lettre = _paragraphes_lettre(stockage.charger_historique()[0])
    assert any(p.startswith("Troisième") for p in lettre) and not any(p.startswith("Deuxième") for p in lettre)
    assert app.text_area(key=f"ed_p2_{eid}").value.startswith("Troisième")
    # Une seconde mise à jour (objet seulement) garde bien le 3e paragraphe
    app.text_input(key=f"ed_objet_{eid}").set_value("Candidature, Data Analyst (alternance)")
    _bouton(app, "Mettre à jour les fichiers").click().run()
    assert any(p.startswith("Troisième") for p in _paragraphes_lettre(stockage.charger_historique()[0]))

    # Modification du CV décochée : retirée du CV, mais toujours proposée (et réactivable)
    case = f"ed_cv_on_t0_r0_c0_p1_{eid}"
    assert "Data Analyst" in _textes_cv(stockage.charger_historique()[0])
    app.checkbox(key=case).uncheck()
    _bouton(app, "Mettre à jour les fichiers").click().run()
    assert "Data Analyst" not in _textes_cv(stockage.charger_historique()[0])
    app.checkbox(key=case).check()
    _bouton(app, "Mettre à jour les fichiers").click().run()
    assert "Data Analyst" in _textes_cv(stockage.charger_historique()[0])


def test_nouvelle_annonce_collee_a_la_main(app: AppTest):
    app.text_input(key="f_adresse").set_value("1 rue Alpha, 75001 Paris")
    app.text_input(key="f_contact").set_value("rh@alpha.example")
    _generer(app, "Alpha SA")

    # Simple correction de la même annonce : rien n'est retiré
    app.text_area(key="f_annonce").set_value(app.text_area(key="f_annonce").value + " Poste basé à Paris.").run()
    assert app.text_input(key="f_adresse").value == "1 rue Alpha, 75001 Paris"

    # Une AUTRE annonce collée à la main : les champs de l'offre Alpha sont retirés
    app.text_area(key="f_annonce").set_value("Beta recrute un alternant chargé d'études marketing digital. " * 4).run()
    assert not app.exception
    for cle in ("f_entreprise", "f_adresse", "f_contact"):
        assert app.text_input(key=cle).value == "", cle
    assert "Nouvelle annonce" in _textes(app)
    app.text_input(key="f_entreprise").set_value("Beta SAS").run()
    _bouton(app, "Générer la candidature").click().run()
    entree = stockage.charger_historique()[0]
    assert entree["contact"] == "" and not any("Alpha" in p for p in _paragraphes_lettre(entree))


def test_telechargements_limites_aux_fichiers_generes(app: AppTest, tmp_path):
    secret = tmp_path / "hors_du_projet.pdf"
    secret.write_bytes(b"%PDF-1.7 donnees personnelles")
    stockage.ajouter_historique({"id": "piege", "date": "2026-11-20T10:00:00", "entreprise": "Piège SA",
                                 "lettre_pdf": str(secret), "dossier": str(tmp_path)})
    _ouvrir_fiche(app, "piege")
    libelles = [b.proto.label for b in app.get("download_button")]
    assert "PDF" not in libelles and "Word" not in libelles
    assert "Fichiers introuvables" in _textes(app)
    assert not any(b.label == "Ouvrir le dossier" for b in app.button)  # dossier hors de outputs/ : jamais ouvert
