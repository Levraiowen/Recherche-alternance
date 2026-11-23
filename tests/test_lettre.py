from datetime import datetime
from pathlib import Path

from docx import Document

from ia_commun import ResultatGeneration
from lettre_generator import (
    construire_contexte,
    decouper_adresse,
    formater_date_en,
    formater_date_fr,
    formater_telephone,
    generer_lettre,
    nettoyer_objet,
    typographie_en,
    typographie_fr,
)

PROFIL = {
    "nom": "Camille Martin",
    "adresse": "1 rue de l'Exemple",
    "code_postal": "69001",
    "ville": "Lyon",
    "telephone": "0600000000",
    "email": "camille.martin@example.com",
}


def _resultat(**modifs) -> ResultatGeneration:
    base = dict(
        entreprise="Natixis Corporate & Investment Banking",
        poste="Data Analyst",
        objet="Objet : Candidature au poste de Data & IA Analyst en alternance",
        formule_appel="Madame, Monsieur,",
        paragraphes=["Premier paragraphe avec R&D et x < y.", "Deuxième paragraphe.", "Troisième."],
        formule_politesse="Je vous prie d'agréer, Madame, Monsieur, mes salutations distinguées.",
    )
    base.update(modifs)
    return ResultatGeneration(**base)


def _lettre(tmp_path: Path, adresse: str = "") -> Path:
    return generer_lettre(resultat=_resultat(), profil=PROFIL, entreprise_adresse=adresse,
                          chemin_sortie=tmp_path / "l.docx")


def _textes(chemin: Path) -> list[str]:
    return [p.text for p in Document(str(chemin)).paragraphs if p.text.strip()]


def test_esperluette_et_chevrons_conserves(tmp_path: Path):
    sortie = _lettre(tmp_path)
    textes = _textes(sortie)
    assert "Natixis Corporate & Investment Banking" in textes
    assert any("R&D et x < y" in t for t in textes)
    assert any("Data & IA Analyst" in t for t in textes)


def test_format_a4_et_objet_sans_doublon(tmp_path: Path):
    sortie = _lettre(tmp_path)
    section = Document(str(sortie)).sections[0]
    assert round(section.page_width.cm, 1) == 21.0
    assert round(section.page_height.cm, 1) == 29.7
    objet = [t for t in _textes(sortie) if t.startswith("Objet")]
    assert len(objet) == 1 and objet[0].count("Objet") == 1


def test_adresse_sur_deux_lignes_et_absente(tmp_path: Path):
    avec = generer_lettre(resultat=_resultat(), profil=PROFIL,
                          entreprise_adresse="5 place de la Pyramide, 92800 Puteaux", chemin_sortie=tmp_path / "a.docx")
    textes = _textes(avec)
    assert "5 place de la Pyramide" in textes and "92800 Puteaux" in textes
    sans = generer_lettre(resultat=_resultat(), profil=PROFIL, entreprise_adresse="", chemin_sortie=tmp_path / "b.docx")
    # Pas de paragraphe vide « fantôme » à la place de l'adresse
    paragraphes = [p.text for p in Document(str(sans)).paragraphs]
    index_entreprise = paragraphes.index("Natixis Corporate & Investment Banking")
    assert paragraphes[index_entreprise + 1].startswith("Lyon, le ")


def test_coordonnees_formatees(tmp_path: Path):
    sortie = _lettre(tmp_path)
    assert "06 00 00 00 00" in _textes(sortie)


def test_aides_typographiques():
    assert typographie_fr("L'offre: SQL ; pourquoi?") == "L’offre : SQL ; pourquoi ?"
    assert typographie_fr("RDV à 10:30 sur https://exemple.org") == "RDV à 10:30 sur https://exemple.org"
    assert typographie_fr("**Gras** suivi") == "Gras suivi"
    assert formater_telephone("07.85.08.28.67") == "07 85 08 28 67"
    assert formater_telephone("+33785082867") == "+33 7 85 08 28 67"
    assert formater_telephone("inconnu") == "inconnu"
    assert decouper_adresse("Tour A, 5 place X, 92800 Puteaux") == ["Tour A, 5 place X", "92800 Puteaux"]
    assert decouper_adresse("") == []
    assert formater_date_fr(datetime(2026, 12, 1)) == "1er décembre 2026"
    assert formater_date_fr(datetime(2026, 11, 23)) == "23 novembre 2026"
    assert nettoyer_objet("Objet : Candidature") == "Candidature"


def test_lettre_en_anglais(tmp_path: Path):
    resultat = _resultat(langue="en", objet="Subject: Application for the Data Analyst work-study position",
                         formule_appel="", formule_politesse="Yours sincerely,", entreprise="",
                         paragraphes=["I'm applying : it's a great fit !", "Second paragraph."])
    contexte = construire_contexte(resultat=resultat, profil=PROFIL, entreprise_adresse="",
                                   date=datetime(2026, 11, 23))
    assert contexte["ligne_date"] == "23 November 2026"  # la date seule, à l'anglaise
    assert contexte["libelle_objet"] == "Subject: "
    assert contexte["objet"] == "Application for the Data Analyst work-study position"
    assert contexte["formule_appel"] == "Dear Hiring Manager," and contexte["entreprise"] == "Hiring Team"
    assert contexte["paragraphes"][0] == "I’m applying: it’s a great fit!"  # pas d'espace avant « : » et « ! »
    assert "+33 6 00 00 00 00" in contexte["expediteur_lignes"]  # téléphone au format international
    chemin = generer_lettre(resultat=resultat, profil=PROFIL, entreprise_adresse="", chemin_sortie=tmp_path / "l.docx")
    textes = [p.text for p in Document(str(chemin)).paragraphs]
    assert "Subject: Application for the Data Analyst work-study position" in textes
    assert not any(t.startswith("Objet") or ", le " in t for t in textes)


def test_lettre_en_francais_inchangee(tmp_path: Path):
    contexte = construire_contexte(resultat=_resultat(), profil=PROFIL, entreprise_adresse="",
                                   date=datetime(2026, 11, 1))
    assert contexte["ligne_date"] == "Lyon, le 1er novembre 2026"
    assert contexte["libelle_objet"] == "Objet\u00a0: " and "06 00 00 00 00" in contexte["expediteur_lignes"]


def test_aides_anglaises():
    assert formater_date_en(datetime(2026, 12, 1)) == "1 December 2026"
    assert formater_telephone("07 85 08 28 67", international=True) == "+33 7 85 08 28 67"
    assert typographie_en("Skills : SQL ; why ?") == "Skills: SQL; why?"
    assert nettoyer_objet("Re: Application") == "Application"
