from pathlib import Path

from candidature import noms_fichiers, produire_candidature
from conftest import faire_pdf
from ia_commun import ResultatGeneration
from pdf_export import ErreurConversionPDF

PROFIL = {"nom": "Camille Martin", "adresse": "1 rue X", "code_postal": "69001", "ville": "Lyon",
          "telephone": "0600000000", "email": "c@example.com"}


def _resultat() -> ResultatGeneration:
    return ResultatGeneration(
        entreprise="Exemple & Fils", poste="Data Analyst", objet="Candidature",
        formule_appel="Madame, Monsieur,", paragraphes=["Un.", "Deux.", "Trois."],
        formule_politesse="Cordialement.",
        cv_adaptations={"t0_r0_c0_p1": "Recherche alternance Data Analyst"},
    )


def test_noms_de_fichiers():
    assert noms_fichiers("Owen Charpentier", "Exemple: SA") == (
        "Lettre_Motivation_Owen_Charpentier_(Exemple SA)", "CV_Owen_Charpentier_(Exemple SA)"
    )


def test_nom_de_la_lettre_en_anglais():
    assert noms_fichiers("Owen Charpentier", "Exemple SA", "en")[0] == "Cover_Letter_Owen_Charpentier_(Exemple SA)"


def test_production_complete(projet_temporaire, cv_exemple: Path, tmp_path: Path):
    def convertir(chemin_docx: Path):
        return faire_pdf(chemin_docx.with_suffix(".pdf"), [500]), "factice"

    sortie = produire_candidature(resultat=_resultat(), profil=PROFIL, entreprise_adresse="",
                                  dossier=tmp_path / "out", cv_reference=cv_exemple, convertir=convertir)
    assert sortie.chemin_lettre_docx.name == "Lettre_Motivation_Camille_Martin_(Exemple & Fils).docx"
    assert sortie.chemin_cv_pdf.exists() and sortie.chemin_lettre_pdf.exists()
    assert sortie.lettre.une_page and sortie.cv.une_page
    assert sortie.adaptations.appliques == ["t0_r0_c0_p1"]
    assert sortie.methode_pdf == "factice" and not sortie.erreurs_pdf


def test_erreur_pdf_garde_les_docx(projet_temporaire, cv_exemple: Path, tmp_path: Path):
    def convertir(chemin_docx: Path):
        raise ErreurConversionPDF("aucun convertisseur")

    sortie = produire_candidature(resultat=_resultat(), profil=PROFIL, entreprise_adresse="",
                                  dossier=tmp_path / "out", cv_reference=cv_exemple, convertir=convertir)
    assert sortie.chemin_lettre_docx.exists() and sortie.chemin_cv_docx.exists()
    assert sortie.chemin_lettre_pdf is None and sortie.erreurs_pdf == ["aucun convertisseur"]
