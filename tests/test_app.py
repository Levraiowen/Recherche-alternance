"""Test de l'interface Streamlit de bout en bout (sans appel réel à l'IA) :
génération, retouche manuelle, historique et détection des doublons."""

import json
from pathlib import Path

import pytest
from docx import Document
from streamlit.testing.v1 import AppTest

import ai_client
import stockage
from conftest import construire_cv_exemple
from ia_commun import ResultatGeneration

APP = Path(__file__).resolve().parent.parent / "app.py"


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
    )


@pytest.fixture
def app(projet_temporaire, monkeypatch):
    stockage.DOSSIER_DATA.mkdir(parents=True)
    construire_cv_exemple(stockage.FICHIER_CV)
    stockage.enregistrer_profil({**stockage.PROFIL_PAR_DEFAUT, "nom": "Camille Martin", "adresse": "1 rue X",
                                 "code_postal": "69001", "ville": "Lyon", "telephone": "0600000000",
                                 "email": "c@example.com"})
    monkeypatch.setenv("FOURNISSEUR_IA", "gemini")
    monkeypatch.setenv("GEMINI_API_KEY", "cle-de-test")
    monkeypatch.setattr(ai_client, "generer_candidature", _fausse_generation)
    test = AppTest.from_file(str(APP), default_timeout=180)
    test.run()
    assert not test.exception
    return test


def _bouton(test: AppTest, debut: str):
    return next(b for b in test.button if b.label.startswith(debut))


def test_generation_retouche_historique(app: AppTest):
    app.text_input[0].set_value("Exemple & Fils")
    app.text_area[0].set_value("Nous recherchons un alternant Data Analyst (SQL, Power BI, Python). " * 3)
    app.run()
    _bouton(app, "✨ Générer").click().run()
    assert not app.exception

    historique = json.loads(stockage.FICHIER_HISTORIQUE.read_text(encoding="utf-8"))
    assert len(historique) == 1 and historique[0]["entreprise"] == "Exemple & Fils"
    lettre = stockage.resoudre_chemin(historique[0]["lettre_docx"])
    assert lettre.exists() and lettre.name == "Lettre_Motivation_Camille_Martin_(Exemple & Fils).docx"
    assert any("bloc introuvable" in c.value for c in app.caption)

    # Retouche manuelle d'un paragraphe puis régénération sans IA
    next(t for t in app.text_area if t.label == "Paragraphe 1").set_value("Paragraphe retouché à la main.")
    app.run()
    _bouton(app, "♻️ Mettre à jour").click().run()
    assert not app.exception
    assert any("retouché à la main" in p.text for p in Document(str(lettre)).paragraphs)

    # Deuxième candidature pour la même entreprise : doublon signalé
    _bouton(app, "✨ Générer").click().run()
    assert any("déjà généré 1 candidature" in i.value for i in app.info)
