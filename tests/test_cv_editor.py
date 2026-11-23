from pathlib import Path

from docx import Document

from cv_editor import appliquer_adaptations, extraire_blocs


def _blocs_par_texte(chemin: Path) -> dict[str, str]:
    return {b.texte: b.id for b in extraire_blocs(chemin)}


def test_identifiants_stables_entre_deux_extractions(cv_exemple: Path):
    assert [b.id for b in extraire_blocs(cv_exemple)] == [b.id for b in extraire_blocs(cv_exemple)]


def test_blocs_proteges(cv_exemple: Path):
    blocs = {b.texte: b for b in extraire_blocs(cv_exemple)}
    assert not blocs["PROFIL"].modifiable  # titre de section en majuscules
    assert not blocs["06 00 00 00 00 · camille.martin@example.com · Lyon"].modifiable  # coordonnées
    assert not blocs["Portfolio : exemple.org/camille"].modifiable  # lien hypertexte
    assert blocs["Recherche alternance data analyst"].modifiable


def test_libelle_en_gras_conserve(cv_exemple: Path, tmp_path: Path):
    ids = _blocs_par_texte(cv_exemple)
    bloc = ids["Langages de programmation : Python (pandas, scikit-learn), SQL, R"]
    sortie = tmp_path / "cv.docx"
    rapport = appliquer_adaptations(
        cv_exemple, sortie, {bloc: "Langages de programmation : SQL, Python (pandas), R"}
    )
    assert rapport.appliques == [bloc]
    paragraphe = next(p for p in Document(str(sortie)).paragraphs if p.text.startswith("Langages"))
    runs = [(r.text, bool(r.bold)) for r in paragraphe.runs]
    assert runs == [("Langages de programmation", True), (" : SQL, Python (pandas), R", False)]


def test_libelle_reecrit_garde_la_structure(cv_exemple: Path, tmp_path: Path):
    ids = _blocs_par_texte(cv_exemple)
    bloc = ids["Outils : Excel, Power BI, Git"]
    sortie = tmp_path / "cv.docx"
    appliquer_adaptations(cv_exemple, sortie, {bloc: "Logiciels : Power BI, Excel"})
    paragraphe = next(p for p in Document(str(sortie)).paragraphs if p.text.startswith("Logiciels"))
    assert [(r.text, bool(r.bold)) for r in paragraphe.runs] == [("Logiciels", True), (" : Power BI, Excel", False)]


def test_dates_en_fin_de_ligne_conservees(cv_exemple: Path, tmp_path: Path):
    ids = _blocs_par_texte(cv_exemple)
    bloc = ids["Assistante commerciale — Exemple SA, Lyon   |   06/2025 – 08/2025"]
    sortie = tmp_path / "cv.docx"
    appliquer_adaptations(cv_exemple, sortie, {bloc: "Assistante data — Exemple SA, Lyon   |   06/2025 – 08/2025"})
    paragraphe = next(p for p in Document(str(sortie)).paragraphs if p.text.startswith("Assistante"))
    runs = [(r.text, bool(r.bold), bool(r.italic)) for r in paragraphe.runs]
    assert runs[0] == ("Assistante data — Exemple SA, Lyon", True, False)
    assert runs[-1] == ("06/2025 – 08/2025", False, True)


def test_refus_et_raisons(cv_exemple: Path, tmp_path: Path):
    ids = _blocs_par_texte(cv_exemple)
    titre = ids["Recherche alternance data analyst"]
    sortie = tmp_path / "cv.docx"
    rapport = appliquer_adaptations(
        cv_exemple,
        sortie,
        {
            titre: "x" * 200,  # beaucoup trop long
            ids["PROFIL"]: "PROFIL PERSONNEL",  # bloc protégé
            "p999": "inconnu",
        },
    )
    assert rapport.appliques == []
    assert "trop long" in rapport.ignores[titre]
    assert "protégé" in rapport.ignores[ids["PROFIL"]]
    assert "introuvable" in rapport.ignores["p999"]


def test_cv_de_reference_jamais_modifie(cv_exemple: Path, tmp_path: Path):
    avant = cv_exemple.read_bytes()
    ids = _blocs_par_texte(cv_exemple)
    appliquer_adaptations(cv_exemple, tmp_path / "cv.docx", {ids["Outils : Excel, Power BI, Git"]: "Outils : Excel"})
    assert cv_exemple.read_bytes() == avant


def test_contenus_word_speciaux_jamais_reecrits(tmp_path):
    """Modifications suivies, contrôles de contenu (modèles de CV Word) : leur
    texte serait perdu ou dupliqué par une réécriture, ils sont donc protégés."""
    from docx import Document as NouveauDocument
    from docx.oxml import parse_xml

    w = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    document = NouveauDocument()
    corps = document.element.body
    corps.insert(0, parse_xml(
        f'<w:p {w}><w:r><w:rPr><w:b/></w:rPr><w:t xml:space="preserve">Outils : </w:t></w:r>'
        f'<w:sdt><w:sdtContent><w:r><w:t>Excel, Power BI, Python</w:t></w:r></w:sdtContent></w:sdt></w:p>'))
    corps.insert(1, parse_xml(
        f'<w:p {w}><w:r><w:t xml:space="preserve">Stage data analyst chez </w:t></w:r>'
        f'<w:ins w:id="1" w:author="moi" w:date="2026-01-01T00:00:00Z"><w:r><w:t>Exemple SA</w:t></w:r></w:ins>'
        f'<w:r><w:t xml:space="preserve"> (Lyon), tableaux de bord</w:t></w:r></w:p>'))
    corps.insert(2, parse_xml(
        f'<w:p {w}><w:r><w:t xml:space="preserve">Jean</w:t><w:noBreakHyphen/><w:t xml:space="preserve">Pierre '
        f'a animé des ateliers de formation</w:t></w:r></w:p>'))
    source = tmp_path / "cv.docx"
    document.save(str(source))

    blocs = {b.id: b for b in extraire_blocs(source)}
    assert not blocs["p0"].modifiable and not blocs["p1"].modifiable
    assert blocs["p2"].modifiable  # un trait d'union insécable n'empêche pas l'adaptation
    rapport = appliquer_adaptations(source, tmp_path / "sortie.docx", {
        "p0": "Outils : Power BI, Excel", "p1": "Stage data analyst (Lyon), reporting Power BI"})
    assert set(rapport.ignores) == {"p0", "p1"} and not rapport.appliques
    from docx.oxml.ns import qn

    sortie = Document(str(tmp_path / "sortie.docx"))
    textes = [" ".join(t.text for t in p._p.iter(qn("w:t"))) for p in sortie.paragraphs]
    assert "Exemple SA" in textes[1] and "Excel, Power BI, Python" in textes[0]
