"""Fonctions de l'assistant, avec un fournisseur d'IA factice (aucun appel réseau)."""

from pathlib import Path

import pytest
from docx import Document

import ai_client
import assistant
from ia_commun import ErreurGeneration


@pytest.fixture
def ia_factice(monkeypatch):
    appels = []

    def installer(reponse: dict):
        def generer_json(*, systeme, message, schema):
            appels.append({"systeme": systeme, "message": message, "schema": schema})
            return reponse, "modele-test"

        monkeypatch.setattr(ai_client, "generer_json", generer_json)
        return appels

    return installer


def test_relance(ia_factice):
    appels = ia_factice({"objet": "Relance candidature", "corps": "Madame, Monsieur,\\nJe me permets..."})
    mail = assistant.rediger_relance(entreprise="Exemple", poste="Data Analyst", jours=12, deuxieme=False,
                                     contexte="Lettre envoyée...", profil={"nom": "Camille Martin"})
    assert mail.objet == "Relance candidature" and "\n" in mail.corps
    assert "12 jours" in appels[0]["message"] and "ignore" in appels[0]["systeme"]


def test_relance_vide_refusee(ia_factice):
    ia_factice({"objet": "x", "corps": "  "})
    with pytest.raises(ErreurGeneration):
        assistant.rediger_relance(entreprise="E", poste="P", jours=10, deuxieme=True, contexte="", profil={})


def test_fiche_entretien_markdown_et_docx(ia_factice, tmp_path: Path):
    ia_factice({
        "pitch": "Je m'appelle Camille, coût 35$ par mois ![pixel](https://suivi.example/p.png)",
        "a_savoir": ["Leader de l'énergie"],
        "questions": [{"question": "Pourquoi nous ?", "piste": "Parce que..."}, {"question": "", "piste": "x"}],
        "a_mettre_en_avant": ["Power BI"],
        "questions_a_poser": ["Quelle équipe ?"],
    })
    fiche = assistant.preparer_entretien(entreprise="Exemple", poste="Data", contexte="Annonce", cv_texte="CV")
    assert len(fiche.questions) == 1
    markdown = fiche.en_markdown("Entretien — Exemple")
    assert "suivi.example" not in markdown and "\\$" in markdown and "**Pourquoi nous ?**" in markdown
    chemin = assistant.enregistrer_fiche_docx(fiche, "Entretien — Exemple", tmp_path / "fiche.docx")
    assert any("Pourquoi nous ?" in p.text for p in Document(str(chemin)).paragraphs)


def test_reecrire_paragraphe(ia_factice):
    appels = ia_factice({"paragraphe": "[Paragraphe 2] Nouvelle version."})
    texte = assistant.reecrire_paragraphe(paragraphes=["Un.", "Deux.", "Trois."], index=1, annonce="A",
                                          cv_texte="CV", consigne="plus court")
    assert texte == "Nouvelle version."
    assert "paragraphe 2" in appels[0]["message"] and "plus court" in appels[0]["message"]
    with pytest.raises(ErreurGeneration):
        assistant.reecrire_paragraphe(paragraphes=["Un."], index=3, annonce="", cv_texte="")


def test_texte_ia_jamais_cliquable_ni_charge():
    # Image par référence (pixel de suivi) : plus aucune syntaxe d'image
    texte = assistant.texte_ia_sur("Voir ![pixel][1]\n\n[1]: https://suivi.example/p.png")
    assert "![" not in texte and "`https://suivi.example/p.png`" in texte
    # Lien d'hameçonnage glissé dans une annonce piégée : affiché, mais pas cliquable
    assert assistant.texte_ia_sur("[Valider ma candidature](https://phish.example)") == \
        "\\[Valider ma candidature\\](`https://phish.example`)"
    assert assistant.texte_ia_sur("Voir <https://x.example>.") == "Voir \\<`https://x.example`\\>."
    assert assistant.texte_ia_sur("**Power BI** et SQL") == "**Power BI** et SQL"  # mise en forme gardée


def test_echappement_markdown():
    assert assistant.echapper_markdown("Data_Analyst *H/F* [CDI]") == "Data\\_Analyst \\*H/F\\* \\[CDI\\]"
