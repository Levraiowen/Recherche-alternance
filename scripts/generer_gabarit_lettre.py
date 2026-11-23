"""
Génère le gabarit Word de la lettre de motivation : templates/lettre_template.docx

Ce script construit le fichier .docx avec python-docx plutôt que de le taper
à la main dans Word. Raison : docxtpl (qui remplit le gabarit) repère les
balises {{ ... }} et {%p ... %} dans le texte, mais Word a tendance à couper
un texte tapé au clavier en plusieurs morceaux internes ("runs"), ce qui casse
les balises de façon invisible à l'œil. En générant le fichier ici, chaque
balise est écrite en un seul bloc, donc le gabarit reste fiable.

Mise en page : format A4 (pas US Letter, le format par défaut de
python-docx), présentation classique d'une lettre française :
expéditeur en haut à gauche, destinataire à droite, puis lieu et date,
objet, corps justifié, formule de politesse et signature. Le même gabarit
sert aux lettres en anglais : les textes fixes (« Objet : » / « Subject: »,
ligne de date) sont fournis par src/lettre_generator.py selon la langue.

Pour changer la mise en page de la lettre (police, taille, alignement,
espacements...), modifie ce script puis relance-le :

    python scripts/generer_gabarit_lettre.py

Ne modifie jamais directement templates/lettre_template.docx dans Word :
la prochaine régénération écraserait tes changements, et une édition
manuelle des balises risquerait de les casser.
"""

from pathlib import Path

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, Twips

RACINE = Path(__file__).resolve().parent.parent
SORTIE = RACINE / "templates" / "lettre_template.docx"

POLICE = "Calibri"
TAILLE_CORPS = Pt(11)
TAILLE_PETIT = Pt(10)

# A4 en twips (1/20e de point) : 21 x 29,7 cm.
LARGEUR_A4 = Twips(11906)
HAUTEUR_A4 = Twips(16838)


def paragraphe(doc, texte, *, taille=TAILLE_CORPS, gras=False, alignement=None,
               espace_avant=0, espace_apres=6, garder_avec_suivant=False):
    p = doc.add_paragraph()
    fmt = p.paragraph_format
    fmt.space_before = Pt(espace_avant)
    fmt.space_after = Pt(espace_apres)
    fmt.keep_with_next = garder_avec_suivant
    if alignement is not None:
        p.alignment = alignement
    run = p.add_run(texte)
    run.font.name = POLICE
    run.font.size = taille
    run.bold = gras
    return p


def balise(doc, texte):
    """Paragraphe de contrôle docxtpl ({%p ... %}) : il disparaît au rendu."""
    return doc.add_paragraph(texte)


def construire():
    doc = Document()

    style_normal = doc.styles["Normal"]
    style_normal.font.name = POLICE
    style_normal.font.size = TAILLE_CORPS
    style_normal.paragraph_format.space_after = Pt(0)
    for section in doc.sections:
        section.page_width = LARGEUR_A4
        section.page_height = HAUTEUR_A4
        section.top_margin = Pt(56)
        section.bottom_margin = Pt(56)
        section.left_margin = Pt(70)
        section.right_margin = Pt(70)

    gauche = WD_ALIGN_PARAGRAPH.LEFT
    droite = WD_ALIGN_PARAGRAPH.RIGHT
    justifie = WD_ALIGN_PARAGRAPH.JUSTIFY

    # --- Expéditeur (haut gauche) ---
    paragraphe(doc, "{{ expediteur_nom }}", taille=TAILLE_PETIT, gras=True, alignement=gauche, espace_apres=0)
    balise(doc, "{%p for ligne in expediteur_lignes %}")
    paragraphe(doc, "{{ ligne }}", taille=TAILLE_PETIT, alignement=gauche, espace_apres=0)
    balise(doc, "{%p endfor %}")

    # --- Destinataire (droite) ---
    paragraphe(doc, "{{ entreprise }}", taille=TAILLE_PETIT, gras=True, alignement=droite,
               espace_avant=14, espace_apres=0)
    balise(doc, "{%p for ligne in entreprise_lignes %}")
    paragraphe(doc, "{{ ligne }}", taille=TAILLE_PETIT, alignement=droite, espace_apres=0)
    balise(doc, "{%p endfor %}")

    # --- Lieu et date (droite) ---
    paragraphe(doc, "{{ ligne_date }}", taille=TAILLE_PETIT, alignement=droite, espace_avant=14, espace_apres=0)

    # --- Objet ---
    paragraphe(doc, "{{ libelle_objet }}{{ objet }}", gras=True, alignement=gauche,
               espace_avant=22, espace_apres=16)

    # --- Formule d'appel ---
    paragraphe(doc, "{{ formule_appel }}", alignement=gauche, espace_apres=10)

    # --- Corps de la lettre : un paragraphe Word par paragraphe généré ---
    balise(doc, "{%p for paragraphe_corps in paragraphes %}")
    p_corps = doc.add_paragraph()
    p_corps.paragraph_format.space_after = Pt(10)
    p_corps.paragraph_format.line_spacing = 1.15
    p_corps.alignment = justifie
    run_corps = p_corps.add_run("{{ paragraphe_corps }}")
    run_corps.font.name = POLICE
    run_corps.font.size = TAILLE_CORPS
    balise(doc, "{%p endfor %}")

    # --- Formule de politesse + signature (toujours ensemble) ---
    paragraphe(doc, "{{ formule_politesse }}", alignement=justifie, espace_avant=2,
               espace_apres=30, garder_avec_suivant=True)
    paragraphe(doc, "{{ expediteur_nom }}", gras=True, alignement=gauche, espace_apres=0)

    SORTIE.parent.mkdir(parents=True, exist_ok=True)
    doc.core_properties.author = ""
    doc.core_properties.title = "Lettre de motivation"
    doc.save(SORTIE)
    print(f"Gabarit généré : {SORTIE}")


if __name__ == "__main__":
    construire()
