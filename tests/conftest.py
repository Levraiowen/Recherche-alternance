"""Fixtures partagées : un CV d'exemple (personne fictive) et un dossier de
projet temporaire, pour ne jamais toucher aux vraies données (data/, outputs/)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor, Twips

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE / "src"))


def _titre_section(doc, texte: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(4)
    p.paragraph_format.space_after = Pt(2)
    ppr = p._p.get_or_add_pPr()
    bordure = OxmlElement("w:pBdr")
    bas = OxmlElement("w:bottom")
    for attribut, valeur in (("w:val", "single"), ("w:sz", "8"), ("w:space", "2"), ("w:color", "1F3864")):
        bas.set(qn(attribut), valeur)
    bordure.append(bas)
    # À insérer AVANT <w:spacing> : Word impose un ordre précis aux balises.
    ppr.insert_element_before(bordure, "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:spacing", "w:ind", "w:jc")
    run = p.add_run(texte)
    run.bold = True
    run.font.size = Pt(11)


def _puce_libelle(doc, libelle: str, texte: str) -> None:
    p = doc.add_paragraph(style="List Bullet")
    gras = p.add_run(libelle)
    gras.bold = True
    gras.font.size = Pt(10)
    normal = p.add_run(texte)
    normal.font.size = Pt(10)


def _ligne_experience(doc, titre: str, dates: str) -> None:
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    r1 = p.add_run(titre)
    r1.bold = True
    r1.font.size = Pt(10)
    r2 = p.add_run("   |   ")
    r2.font.size = Pt(9)
    r2.font.color.rgb = RGBColor(0x99, 0x99, 0x99)
    r3 = p.add_run(dates)
    r3.italic = True
    r3.font.size = Pt(9)
    r3.font.color.rgb = RGBColor(0x55, 0x55, 0x55)


def construire_cv_exemple(chemin: Path, *, lignes_profil: int = 1) -> Path:
    """CV d'une personne fictive, avec les structures rencontrées dans un vrai
    CV : en-tête en tableau, titres de section soulignés, puces « libellé en
    gras : texte », lignes « poste | dates »."""
    doc = Document()
    for section in doc.sections:
        section.page_width = Twips(11906)  # A4
        section.page_height = Twips(16838)
        section.top_margin = Pt(25)
        section.bottom_margin = Pt(20)
        section.left_margin = Pt(42)
        section.right_margin = Pt(42)
    style = doc.styles["Normal"]
    style.font.name = "Calibri"
    style.font.size = Pt(10)
    style.paragraph_format.space_after = Pt(0)

    tableau = doc.add_table(rows=1, cols=2)
    cellule = tableau.rows[0].cells[0]
    nom = cellule.paragraphs[0].add_run("Camille MARTIN")
    nom.bold = True
    nom.font.size = Pt(22)
    titre = cellule.add_paragraph().add_run("Recherche alternance data analyst")
    titre.bold = True
    titre.font.size = Pt(12)
    cellule.add_paragraph("06 00 00 00 00 · camille.martin@example.com · Lyon").runs[0].font.size = Pt(9.5)

    _titre_section(doc, "PROFIL")
    profil = doc.add_paragraph(
        " ".join(["Étudiante en statistiques, je recherche une alternance en analyse de données."] * lignes_profil)
    )
    profil.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    _titre_section(doc, "COMPÉTENCES")
    _puce_libelle(doc, "Langages de programmation", " : Python (pandas, scikit-learn), SQL, R")
    _puce_libelle(doc, "Outils", " : Excel, Power BI, Git")
    _titre_section(doc, "EXPÉRIENCE PROFESSIONNELLE")
    _ligne_experience(doc, "Assistante commerciale — Exemple SA, Lyon", "06/2025 – 08/2025")
    doc.add_paragraph("Suivi hebdomadaire des ventes et tableaux de bord sous Excel", style="List Bullet")
    p_lien = doc.add_paragraph("Portfolio : ")
    lien = OxmlElement("w:hyperlink")
    run_lien = OxmlElement("w:r")
    texte_lien = OxmlElement("w:t")
    texte_lien.text = "exemple.org/camille"
    run_lien.append(texte_lien)
    lien.append(run_lien)
    p_lien._p.append(lien)
    doc.save(str(chemin))
    return chemin


@pytest.fixture
def cv_exemple(tmp_path: Path) -> Path:
    return construire_cv_exemple(tmp_path / "cv_exemple.docx")


@pytest.fixture
def projet_temporaire(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirige tous les chemins de stockage vers un dossier temporaire."""
    import stockage

    racine = tmp_path / "projet"
    data = racine / "data"
    monkeypatch.setattr(stockage, "RACINE", racine)
    monkeypatch.setattr(stockage, "DOSSIER_DATA", data)
    monkeypatch.setattr(stockage, "DOSSIER_OUTPUTS", racine / "outputs")
    monkeypatch.setattr(stockage, "FICHIER_PROFIL", data / "profil.json")
    monkeypatch.setattr(stockage, "FICHIER_HISTORIQUE", data / "historique.json")
    monkeypatch.setattr(stockage, "FICHIER_CV", data / "cv_original.docx")
    monkeypatch.setattr(stockage, "FICHIER_MISE_EN_PAGE", data / "mise_en_page.json")
    return racine


def faire_pdf(chemin: Path, bas_par_page: list[float], hauteur: float = 842.0) -> Path:
    """Crée un PDF de test : une ligne de texte dont le bas est à la position
    demandée (en points depuis le haut) sur chaque page."""
    from reportlab.pdfgen import canvas

    toile = canvas.Canvas(str(chemin), pagesize=(595.0, hauteur))
    for bas in bas_par_page:
        toile.setFont("Helvetica", 10)
        toile.drawString(50, hauteur - bas + 2, "Ligne de test")
        toile.showPage()
    toile.save()
    return chemin
