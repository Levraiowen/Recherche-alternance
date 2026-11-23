import io
import shutil
import zipfile
from pathlib import Path

import pytest
from docx import Document
from lxml import etree

import mise_en_page as mp
from conftest import construire_cv_exemple, faire_pdf


def _xml(contenu: bytes, partie: str = "word/document.xml"):
    with zipfile.ZipFile(io.BytesIO(contenu)) as z:
        return etree.fromstring(z.read(partie))


def test_niveau_zero_ne_change_rien(cv_exemple: Path):
    contenu = cv_exemple.read_bytes()
    assert mp.compacter_docx(contenu, mp.NIVEAUX[0], mp.PROFIL_CV) == contenu


def test_compaction_espacements_polices_marges(cv_exemple: Path):
    contenu = cv_exemple.read_bytes()
    niveau = mp.NIVEAUX[mp.NIVEAU_MAX]
    compacte = mp.compacter_docx(contenu, niveau, mp.PROFIL_CV)
    Document(io.BytesIO(compacte))  # toujours un .docx valide

    avant, apres = _xml(contenu), _xml(compacte)
    w = mp.W_NS
    tailles_avant = sorted(int(e.get(f"{{{w}}}val")) for e in avant.iter(f"{{{w}}}sz"))
    tailles_apres = sorted(int(e.get(f"{{{w}}}val")) for e in apres.iter(f"{{{w}}}sz"))
    assert max(tailles_apres) < max(tailles_avant)  # le nom en 22 pt rétrécit
    assert min(tailles_apres) >= min(mp.PROFIL_CV.taille_police_demi_points, min(tailles_avant))

    espacements = [int(e.get(f"{{{w}}}before")) for e in apres.iter(f"{{{w}}}spacing") if e.get(f"{{{w}}}before")]
    assert espacements and max(espacements) <= 80 * niveau.espacement + 1  # 4 pt avant -> réduit

    marges_avant = avant.find(".//w:pgMar", mp.NS)
    marges_apres = apres.find(".//w:pgMar", mp.NS)
    for cote in ("left", "right"):
        assert int(marges_apres.get(f"{{{w}}}{cote}")) <= int(marges_avant.get(f"{{{w}}}{cote}"))
        assert int(marges_apres.get(f"{{{w}}}{cote}")) >= mp.PROFIL_CV.marge_cotes_twips - 1


def test_ordre_des_elements_respecte(cv_exemple: Path):
    """Word refuse parfois d'ouvrir un fichier dont les balises ne sont pas
    dans l'ordre imposé par le format : on le vérifie sur chaque niveau."""
    contenu = cv_exemple.read_bytes()
    for niveau in mp.NIVEAUX[1:]:
        racine = _xml(mp.compacter_docx(contenu, niveau, mp.PROFIL_CV))
        for balise, ordre in (("pPr", mp.ORDRE_PPR), ("rPr", mp.ORDRE_RPR)):
            for element in racine.iter(f"{{{mp.W_NS}}}{balise}"):
                rangs = [ordre.index(etree.QName(e).localname) for e in element
                         if etree.QName(e).localname in ordre]
                assert rangs == sorted(rangs)


def test_mesure_et_choix_du_niveau(tmp_path: Path):
    deux_pages = mp.mesurer_pdf(faire_pdf(tmp_path / "a.pdf", [815, 55]), marge_haut=25, marge_bas=20)
    assert deux_pages.pages == 2 and deux_pages.depassement > 0
    petit = mp.niveau_suivant(0, deux_pages, mp.PROFIL_CV)
    gros = mp.niveau_suivant(0, mp.mesurer_pdf(faire_pdf(tmp_path / "b.pdf", [815, 600]), 25, 20), mp.PROFIL_CV)
    assert 1 <= petit < gros <= mp.NIVEAU_MAX

    une_page = mp.mesurer_pdf(faire_pdf(tmp_path / "c.pdf", [500]), marge_haut=25, marge_bas=20)
    assert une_page.pages == 1 and une_page.espace_libre == pytest.approx(842 - 20 - 500, abs=3)
    assert mp.niveau_inferieur_suffirait(3, une_page, mp.PROFIL_CV)


def test_boucle_avec_convertisseur_factice(cv_exemple: Path, tmp_path: Path):
    """Le convertisseur factice déborde tant que les espacements avant les
    titres (4 pt) n'ont pas été réduits d'au moins 30 % : la boucle doit
    s'arrêter au premier niveau suffisant, et le .docx livré doit
    correspondre au PDF final."""
    appels = []

    def convertir(chemin_docx: Path):
        racine = _xml(chemin_docx.read_bytes())
        avant = [int(e.get(f"{{{mp.W_NS}}}before")) for e in racine.iter(f"{{{mp.W_NS}}}spacing")
                 if e.get(f"{{{mp.W_NS}}}before")]
        resserre = max(avant) <= 56  # 80 twips (4 pt) x 0,7
        appels.append(resserre)
        pdf = chemin_docx.with_suffix(".pdf")
        return faire_pdf(pdf, [500] if resserre else [815, 60]), "factice"

    resultat = mp.ajuster_sur_une_page(cv_exemple, convertir, profil=mp.PROFIL_CV)
    assert resultat.une_page and resultat.methode == "factice"
    assert resultat.niveau >= 2 and resultat.conversions == len(appels) <= 3
    assert appels[-1] is True


def test_nombre_de_conversions_plafonne(cv_exemple: Path):
    def convertir(chemin_docx: Path):
        return faire_pdf(chemin_docx.with_suffix(".pdf"), [815, 815, 815]), "factice"

    resultat = mp.ajuster_sur_une_page(cv_exemple, convertir, profil=mp.PROFIL_CV, conversions_max=2)
    assert resultat.conversions == 2 and not resultat.une_page


@pytest.mark.skipif(shutil.which("soffice") is None, reason="LibreOffice non installé")
def test_integration_libreoffice_cv_trop_long(tmp_path: Path):
    """Test réel : un CV qui déborde d'une dizaine de lignes est ramené sur
    une page par le vrai moteur de rendu."""
    from pdf_export import convertir_en_pdf

    chemin = construire_cv_exemple(tmp_path / "long.docx", lignes_profil=75)
    initial = mp.mesurer_pdf(convertir_en_pdf(chemin)[0], 25, 20)
    assert initial.pages == 2, "le CV de test devrait déborder au départ"
    resultat = mp.ajuster_sur_une_page(chemin, convertir_en_pdf, profil=mp.PROFIL_CV)
    assert resultat.une_page and resultat.niveau > 0
