"""
Garantit qu'un document Word (CV ou lettre) tienne sur UNE seule page une
fois converti en PDF, en faisant le moins de concessions visuelles possible.

Principe :
1. On convertit le .docx tel quel et on compte les pages du PDF obtenu
   (c'est le PDF réellement produit par le convertisseur utilisé — Word,
   LibreOffice ou iLovePDF — qui fait foi : chaque moteur de rendu a ses
   petites différences de mise en page, impossible de les prédire à coup sûr).
2. Si ça déborde, on mesure de combien (hauteur du contenu passé en page 2)
   et on choisit directement le plus petit « niveau de compaction » qui
   devrait suffire, puis on reconvertit pour vérifier.
3. Les niveaux sont ordonnés du moins visible au plus visible : on resserre
   d'abord les espacements entre paragraphes et (très légèrement)
   l'interligne, puis les marges, et seulement en dernier recours la taille
   de police (par demi-points). Le contenu n'est JAMAIS coupé ni supprimé.

Chaque niveau est appliqué à partir du document d'origine (jamais par-dessus
une version déjà compactée), pour que deux niveaux soient toujours
comparables et que le résultat ne dépende pas du nombre d'essais.
"""

from __future__ import annotations

import copy
import io
import math
import threading
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from lxml import etree

W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
NS = {"w": W_NS}
TWIPS_PAR_POINT = 20


def _w(nom: str) -> str:
    return f"{{{W_NS}}}{nom}"


# ---------------------------------------------------------------------------
# Niveaux de compaction
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class NiveauCompaction:
    """Réglages appliqués à tout le document.

    - espacement : facteur sur les espaces avant/après paragraphe.
    - interligne : facteur sur l'interligne (1.0 = inchangé).
    - marges : 1.0 = marges haut/bas inchangées, 0.0 = ramenées au plancher.
    - marges_cotes : idem pour les marges gauche/droite.
    - police : facteur sur toutes les tailles de police (arrondi au
      demi-point, jamais sous le plancher de taille).
    """

    espacement: float = 1.0
    interligne: float = 1.0
    marges: float = 1.0
    marges_cotes: float = 1.0
    police: float = 1.0

    def description(self) -> str:
        """Résumé lisible des concessions faites, pour l'interface."""
        morceaux = []
        if self.espacement < 1:
            morceaux.append(f"espacements −{round((1 - self.espacement) * 100)} %")
        if self.interligne < 1:
            morceaux.append(f"interligne −{round((1 - self.interligne) * 100)} %")
        if self.marges < 1:
            morceaux.append("marges haut/bas réduites")
        if self.marges_cotes < 1:
            morceaux.append("marges latérales réduites")
        if self.police < 1:
            morceaux.append(f"police −{round((1 - self.police) * 100)} %")
        return ", ".join(morceaux) if morceaux else "mise en page d'origine"


# Du moins visible au plus visible.
NIVEAUX: tuple[NiveauCompaction, ...] = (
    NiveauCompaction(),
    NiveauCompaction(espacement=0.85, interligne=0.98),
    NiveauCompaction(espacement=0.7, interligne=0.96),
    NiveauCompaction(espacement=0.55, interligne=0.94, marges=0.6),
    NiveauCompaction(espacement=0.45, interligne=0.91, marges=0.3),
    NiveauCompaction(espacement=0.4, interligne=0.9, marges=0.0, police=0.96),
    NiveauCompaction(espacement=0.35, interligne=0.89, marges=0.0, marges_cotes=0.5, police=0.93),
    NiveauCompaction(espacement=0.3, interligne=0.88, marges=0.0, marges_cotes=0.2, police=0.9),
)
NIVEAU_MAX = len(NIVEAUX) - 1


@dataclass(frozen=True)
class ProfilDocument:
    """Réglages propres à un type de document (CV ou lettre).

    - marges/taille : valeurs minimales en dessous desquelles on ne descend
      jamais (marges en twips = 1/20e de point, taille en demi-points).
    - gains : part de hauteur gagnée à chaque niveau par rapport au niveau
      0, mesurée sur de vrais CV et de vraies lettres. Ne sert qu'à viser
      juste du premier coup : le résultat est toujours vérifié sur le PDF.
    """

    marge_haut_bas_twips: int
    marge_cotes_twips: int
    taille_police_demi_points: int
    gains: tuple[float, ...]


# Un CV peut avoir des marges très fines ; une lettre doit garder un aspect
# de courrier classique (marges confortables, police lisible). Une lettre,
# plus aérée, gagne environ deux fois plus de hauteur à chaque niveau.
PROFIL_CV = ProfilDocument(
    marge_haut_bas_twips=284, marge_cotes_twips=567, taille_police_demi_points=16,
    gains=(0.0, 0.025, 0.06, 0.08, 0.11, 0.18, 0.2, 0.28),
)
PROFIL_LETTRE = ProfilDocument(
    marge_haut_bas_twips=850, marge_cotes_twips=1020, taille_police_demi_points=19,
    gains=(0.0, 0.05, 0.1, 0.14, 0.19, 0.24, 0.28, 0.33),
)


# ---------------------------------------------------------------------------
# Lecture des styles (pour connaître l'espacement « effectif » de chaque
# paragraphe, y compris quand il est hérité d'un style)
# ---------------------------------------------------------------------------

ATTRIBUTS_ESPACEMENT = ("before", "after", "line", "lineRule", "beforeLines", "afterLines",
                        "beforeAutospacing", "afterAutospacing")


def _lire_espacement(ppr) -> dict[str, str]:
    if ppr is None:
        return {}
    spacing = ppr.find("w:spacing", NS)
    if spacing is None:
        return {}
    return {a: spacing.get(_w(a)) for a in ATTRIBUTS_ESPACEMENT if spacing.get(_w(a)) is not None}


class _Styles:
    """Résout l'espacement effectif (style + styles parents + défauts)."""

    def __init__(self, racine_styles):
        self.par_id: dict[str, etree._Element] = {}
        self.defaut_paragraphe: str | None = None
        self.espacement_defaut: dict[str, str] = {}
        self._cache: dict[str, dict[str, str]] = {}
        if racine_styles is None:
            return
        ppr_defaut = racine_styles.find("w:docDefaults/w:pPrDefault/w:pPr", NS)
        self.espacement_defaut = _lire_espacement(ppr_defaut)
        for style in racine_styles.findall("w:style", NS):
            if style.get(_w("type")) != "paragraph":
                continue
            sid = style.get(_w("styleId"))
            if sid:
                self.par_id[sid] = style
                if style.get(_w("default")) in ("1", "true", "on"):
                    self.defaut_paragraphe = sid

    def espacement_effectif(self, style_id: str | None) -> dict[str, str]:
        style_id = style_id or self.defaut_paragraphe
        if not style_id or style_id not in self.par_id:
            return dict(self.espacement_defaut)
        if style_id in self._cache:
            return dict(self._cache[style_id])
        chaine = []
        courant, vus = style_id, set()
        while courant and courant in self.par_id and courant not in vus:
            vus.add(courant)
            style = self.par_id[courant]
            chaine.append(style)
            base = style.find("w:basedOn", NS)
            courant = base.get(_w("val")) if base is not None else None
        resultat = dict(self.espacement_defaut)
        for style in reversed(chaine):  # du parent le plus lointain au style lui-même
            resultat.update(_lire_espacement(style.find("w:pPr", NS)))
        self._cache[style_id] = resultat
        return dict(resultat)


# ---------------------------------------------------------------------------
# Transformations XML
# ---------------------------------------------------------------------------

# Ordre imposé par le schéma OOXML pour les enfants de <w:pPr> : Word peut
# refuser d'ouvrir un fichier dont les éléments ne sont pas dans cet ordre.
ORDRE_PPR = ("pStyle", "keepNext", "keepLines", "pageBreakBefore", "framePr", "widowControl",
             "numPr", "suppressLineNumbers", "pBdr", "shd", "tabs", "suppressAutoHyphens", "kinsoku",
             "wordWrap", "overflowPunct", "topLinePunct", "autoSpaceDE", "autoSpaceDN", "bidi",
             "adjustRightInd", "snapToGrid", "spacing", "ind", "contextualSpacing", "mirrorIndents",
             "suppressOverlap", "jc", "textDirection", "textAlignment", "textboxTightWrap",
             "outlineLvl", "divId", "cnfStyle", "rPr", "sectPr", "pPrChange")
ORDRE_RPR = ("rStyle", "rFonts", "b", "bCs", "i", "iCs", "caps", "smallCaps", "strike", "dstrike",
             "outline", "shadow", "emboss", "imprint", "noProof", "snapToGrid", "vanish", "webHidden",
             "color", "spacing", "w", "kern", "position", "sz", "szCs", "highlight", "u", "effect",
             "bdr", "shd", "fitText", "vertAlign", "rtl", "cs", "em", "lang", "eastAsianLayout",
             "specVanish", "oMath")


def _enfant_ordonne(parent, nom: str, ordre: tuple[str, ...]):
    """Renvoie l'enfant `nom` de `parent`, en le créant à la bonne place
    (selon `ordre`) s'il n'existe pas encore."""
    existant = parent.find(f"w:{nom}", NS)
    if existant is not None:
        return existant
    nouvel = etree.SubElement(parent, _w(nom))
    parent.remove(nouvel)
    rang = ordre.index(nom) if nom in ordre else len(ordre)
    for index, enfant in enumerate(parent):
        nom_enfant = etree.QName(enfant).localname if isinstance(enfant.tag, str) else ""
        if nom_enfant in ordre and ordre.index(nom_enfant) > rang:
            parent.insert(index, nouvel)
            return nouvel
    parent.append(nouvel)
    return nouvel


def _ppr(paragraphe):
    ppr = paragraphe.find("w:pPr", NS)
    if ppr is None:
        ppr = etree.Element(_w("pPr"))
        paragraphe.insert(0, ppr)
    return ppr


def _compacter_espacement_paragraphe(paragraphe, styles: _Styles, niveau: NiveauCompaction) -> None:
    if niveau.espacement >= 1 and niveau.interligne >= 1:
        return
    ppr = paragraphe.find("w:pPr", NS)
    style_el = ppr.find("w:pStyle", NS) if ppr is not None else None
    style_id = style_el.get(_w("val")) if style_el is not None else None
    effectif = styles.espacement_effectif(style_id)
    effectif.update(_lire_espacement(ppr))

    nouveaux: dict[str, str] = {}
    if niveau.espacement < 1:
        for cote in ("before", "after"):
            if effectif.get(f"{cote}Autospacing") in ("1", "true", "on"):
                continue  # espacement automatique « style HTML » : on n'y touche pas
            valeur = effectif.get(cote)
            if valeur is not None and valeur.lstrip("-").isdigit() and int(valeur) > 0:
                nouveaux[cote] = str(round(int(valeur) * niveau.espacement))
            lignes = effectif.get(f"{cote}Lines")
            if lignes is not None and lignes.isdigit() and int(lignes) > 0:
                nouveaux[f"{cote}Lines"] = str(round(int(lignes) * niveau.espacement))
    if niveau.interligne < 1:
        regle = effectif.get("lineRule", "auto")
        ligne = effectif.get("line")
        base = int(ligne) if ligne is not None and ligne.lstrip("-").isdigit() else 240
        if regle == "auto" or ligne is None:
            nouveaux["line"] = str(max(120, round(base * niveau.interligne)))
            nouveaux["lineRule"] = "auto"
        else:  # "exact" ou "atLeast" : valeur en twips
            nouveaux["line"] = str(max(40, round(abs(base) * niveau.interligne)))
            nouveaux["lineRule"] = regle
    if not nouveaux:
        return
    spacing = _enfant_ordonne(_ppr(paragraphe), "spacing", ORDRE_PPR)
    for nom, valeur in nouveaux.items():
        spacing.set(_w(nom), valeur)


def _nouvelle_taille(valeur: int, niveau: NiveauCompaction, profil: ProfilDocument) -> int:
    if valeur <= profil.taille_police_demi_points:
        return valeur  # déjà petit (ex: espaceur de 1 pt) : on ne touche pas
    return max(profil.taille_police_demi_points, round(valeur * niveau.police))


def _compacter_polices(racine, niveau: NiveauCompaction, profil: ProfilDocument) -> None:
    if niveau.police >= 1 or racine is None:
        return
    for balise in ("sz", "szCs"):
        for element in racine.iter(_w(balise)):
            valeur = element.get(_w("val"))
            if valeur and valeur.isdigit():
                element.set(_w("val"), str(_nouvelle_taille(int(valeur), niveau, profil)))


def _assurer_taille_par_defaut(racine_styles, niveau: NiveauCompaction, profil: ProfilDocument) -> None:
    """Sans taille explicite dans les styles par défaut, Word utilise 10 pt :
    on l'écrit explicitement pour que la réduction s'applique aussi au texte
    qui n'a aucune taille définie nulle part."""
    if niveau.police >= 1 or racine_styles is None:
        return
    doc_defaults = racine_styles.find("w:docDefaults", NS)
    if doc_defaults is None:
        doc_defaults = etree.Element(_w("docDefaults"))
        racine_styles.insert(0, doc_defaults)
    rpr_default = doc_defaults.find("w:rPrDefault", NS)
    if rpr_default is None:
        rpr_default = etree.Element(_w("rPrDefault"))
        doc_defaults.insert(0, rpr_default)
    rpr = rpr_default.find("w:rPr", NS)
    if rpr is None:
        rpr = etree.SubElement(rpr_default, _w("rPr"))
    for balise in ("sz", "szCs"):
        if rpr.find(f"w:{balise}", NS) is None:
            element = _enfant_ordonne(rpr, balise, ORDRE_RPR)
            element.set(_w("val"), str(_nouvelle_taille(20, niveau, profil)))


def _texte_paragraphe(paragraphe) -> str:
    return "".join(t.text or "" for t in paragraphe.iter(_w("t")))


def _contient_objet(paragraphe) -> bool:
    return any(True for _ in paragraphe.iter(_w("drawing"))) or any(True for _ in paragraphe.iter(_w("pict")))


def _reduire_paragraphes_vides_finaux(corps) -> None:
    """Un paragraphe vide en fin de document (Word en impose un après un
    tableau final, par exemple) peut à lui seul créer une 2e page blanche :
    on le ramène à une hauteur quasi nulle (1 pt), invisible à l'œil."""
    enfants = [e for e in corps if isinstance(e.tag, str) and etree.QName(e).localname != "sectPr"]
    for element in reversed(enfants):
        if etree.QName(element).localname != "p":
            break
        porte_section = element.find("w:pPr/w:sectPr", NS) is not None
        if _texte_paragraphe(element).strip() or _contient_objet(element) or porte_section:
            break
        ppr = _ppr(element)
        spacing = _enfant_ordonne(ppr, "spacing", ORDRE_PPR)
        spacing.set(_w("before"), "0")
        spacing.set(_w("after"), "0")
        spacing.set(_w("line"), "20")
        spacing.set(_w("lineRule"), "exact")
        rpr = _enfant_ordonne(ppr, "rPr", ORDRE_PPR)
        for balise in ("sz", "szCs"):
            _enfant_ordonne(rpr, balise, ORDRE_RPR).set(_w("val"), "2")


def _reduire(valeur: int, plancher: int, facteur: float) -> int:
    """Rapproche une marge de son plancher : facteur 1 = inchangée,
    facteur 0 = ramenée au plancher. Une marge déjà sous le plancher reste
    telle quelle (on ne l'agrandit jamais)."""
    signe = -1 if valeur < 0 else 1
    absolue = abs(valeur)
    if absolue <= plancher:
        return valeur
    return signe * round(plancher + (absolue - plancher) * facteur)


def _compacter_marges(racine_doc, niveau: NiveauCompaction, profil: ProfilDocument) -> None:
    if niveau.marges >= 1 and niveau.marges_cotes >= 1:
        return
    for sect in racine_doc.iter(_w("sectPr")):
        marges = sect.find("w:pgMar", NS)
        if marges is None:
            continue
        largeur_page = sect.find("w:pgSz", NS)
        largeur = int(largeur_page.get(_w("w"), "11906")) if largeur_page is not None else 11906

        def lire(nom: str, marges=marges) -> int:
            valeur = marges.get(_w(nom))
            return int(valeur) if valeur and valeur.lstrip("-").isdigit() else 0

        if niveau.marges < 1:
            for nom in ("top", "bottom"):
                marges.set(_w(nom), str(_reduire(lire(nom), profil.marge_haut_bas_twips, niveau.marges)))
        if niveau.marges_cotes < 1:
            ancienne_largeur_texte = largeur - lire("left") - lire("right")
            for nom in ("left", "right"):
                marges.set(_w(nom), str(_reduire(lire(nom), profil.marge_cotes_twips, niveau.marges_cotes)))
            nouvelle_largeur_texte = largeur - lire("left") - lire("right")
            if ancienne_largeur_texte > 0 and nouvelle_largeur_texte != ancienne_largeur_texte:
                _elargir_tableaux(racine_doc, nouvelle_largeur_texte / ancienne_largeur_texte)


def _elargir_tableaux(racine_doc, ratio: float) -> None:
    """Quand la zone de texte s'élargit, les tableaux à largeur fixe (ex:
    en-tête nom + photo) suivent la même proportion pour garder leur
    alignement avec le reste de la page."""
    corps = racine_doc.find("w:body", NS)
    if corps is None:
        return
    for tableau in corps.findall("w:tbl", NS):  # tableaux de premier niveau seulement
        for chemin in ("w:tblPr/w:tblW", ".//w:tcW"):
            for element in tableau.findall(chemin, NS):
                if element.get(_w("type"), "dxa") == "dxa":
                    valeur = element.get(_w("w"))
                    if valeur and valeur.isdigit():
                        element.set(_w("w"), str(round(int(valeur) * ratio)))
        for colonne in tableau.findall("w:tblGrid/w:gridCol", NS):
            valeur = colonne.get(_w("w"))
            if valeur and valeur.isdigit():
                colonne.set(_w("w"), str(round(int(valeur) * ratio)))


def _parties_texte(noms: list[str]) -> list[str]:
    return [n for n in noms if n == "word/document.xml"
            or (n.startswith("word/header") and n.endswith(".xml"))
            or (n.startswith("word/footer") and n.endswith(".xml"))]


def compacter_docx(contenu: bytes, niveau: NiveauCompaction, profil: ProfilDocument) -> bytes:
    """Renvoie une copie du .docx (`contenu`, en octets) avec le niveau de
    compaction appliqué. Le niveau 0 renvoie le document strictement
    inchangé (mêmes octets)."""
    if niveau == NIVEAUX[0]:
        return contenu

    entree = zipfile.ZipFile(io.BytesIO(contenu))
    noms = entree.namelist()
    parties: dict[str, etree._Element] = {}
    parseur = etree.XMLParser(remove_blank_text=False, resolve_entities=False)
    for nom in _parties_texte(noms) + [n for n in ("word/styles.xml", "word/numbering.xml") if n in noms]:
        parties[nom] = etree.fromstring(entree.read(nom), parseur)

    styles = _Styles(parties.get("word/styles.xml"))
    for nom in _parties_texte(noms):
        racine = parties[nom]
        for paragraphe in racine.iter(_w("p")):
            _compacter_espacement_paragraphe(paragraphe, styles, niveau)
        _compacter_polices(racine, niveau, profil)
    _compacter_polices(parties.get("word/styles.xml"), niveau, profil)
    _assurer_taille_par_defaut(parties.get("word/styles.xml"), niveau, profil)
    _compacter_polices(parties.get("word/numbering.xml"), niveau, profil)

    document = parties["word/document.xml"]
    _compacter_marges(document, niveau, profil)
    corps = document.find("w:body", NS)
    if corps is not None:
        _reduire_paragraphes_vides_finaux(corps)

    sortie = io.BytesIO()
    with zipfile.ZipFile(sortie, "w", zipfile.ZIP_DEFLATED) as zout:
        for info in entree.infolist():
            if info.filename in parties:
                donnees = etree.tostring(parties[info.filename], xml_declaration=True,
                                         encoding="UTF-8", standalone=True)
            else:
                donnees = entree.read(info.filename)
            zout.writestr(copy.copy(info), donnees)
    return sortie.getvalue()


def marges_points(contenu: bytes) -> tuple[float, float]:
    """Marges haut/bas (en points) de la dernière section du document."""
    with zipfile.ZipFile(io.BytesIO(contenu)) as z:
        racine = etree.fromstring(z.read("word/document.xml"))
    sect = None
    corps = racine.find("w:body", NS)
    if corps is not None:
        sect = corps.find("w:sectPr", NS)
    marges = sect.find("w:pgMar", NS) if sect is not None else None
    if marges is None:
        return 72.0, 72.0
    haut = abs(int(marges.get(_w("top"), "1440"))) / TWIPS_PAR_POINT
    bas = abs(int(marges.get(_w("bottom"), "1440"))) / TWIPS_PAR_POINT
    return haut, bas


# ---------------------------------------------------------------------------
# Mesure du PDF obtenu
# ---------------------------------------------------------------------------


@dataclass
class MesurePDF:
    pages: int
    hauteur_page: float
    bas_contenu_par_page: list[float]  # depuis le haut de la page, en points
    marge_haut: float
    marge_bas: float

    @property
    def capacite(self) -> float:
        return max(1.0, self.hauteur_page - self.marge_haut - self.marge_bas)

    @property
    def depassement(self) -> float:
        """Hauteur de contenu en trop (points), > 0 si plus d'une page."""
        if self.pages <= 1 or not self.bas_contenu_par_page:
            return 0.0
        utilise = 0.0
        for bas in self.bas_contenu_par_page:
            utilise += max(0.0, bas - self.marge_haut)
        # Au moins une ligne : sinon une page 2 « presque vide » (ex: une
        # seule ligne repoussée par le contrôle des veuves et orphelines)
        # donnerait un dépassement estimé nul ou négatif.
        return max(utilise - self.capacite, 14.0)

    @property
    def espace_libre(self) -> float:
        """Espace restant en bas de la page 1 (points), si tout tient."""
        if self.pages != 1 or not self.bas_contenu_par_page:
            return 0.0
        return max(0.0, self.hauteur_page - self.marge_bas - self.bas_contenu_par_page[0])


# PDFium (la bibliothèque qui lit les PDF) n'accepte pas d'être utilisée
# par deux fils d'exécution en même temps, même sur des fichiers différents :
# tout accès passe par ce verrou (le CV et la lettre sont traités en
# parallèle, et l'interface affiche des aperçus).
VERROU_PDFIUM = threading.Lock()


def mesurer_pdf(chemin_pdf: Path, marge_haut: float, marge_bas: float) -> MesurePDF:
    with VERROU_PDFIUM:
        return _mesurer_pdf(chemin_pdf, marge_haut, marge_bas)


def _mesurer_pdf(chemin_pdf: Path, marge_haut: float, marge_bas: float) -> MesurePDF:
    import pypdfium2 as pdfium

    document = pdfium.PdfDocument(str(chemin_pdf))
    try:
        bas_par_page: list[float] = []
        hauteur = 842.0
        for page in document:
            _, hauteur = page.get_size()
            texte = page.get_textpage()
            plus_bas = 0.0
            for index in range(texte.count_chars()):
                gauche, bas, droite, haut = texte.get_charbox(index)
                if droite - gauche <= 0 or haut - bas <= 0:
                    continue  # caractère généré (espace, retour ligne) sans boîte
                plus_bas = max(plus_bas, hauteur - bas)
            bas_par_page.append(plus_bas)
            texte.close()
            page.close()
        return MesurePDF(
            pages=len(bas_par_page),
            hauteur_page=hauteur,
            bas_contenu_par_page=bas_par_page,
            marge_haut=marge_haut,
            marge_bas=marge_bas,
        )
    finally:
        document.close()


def niveau_suivant(niveau_actuel: int, mesure: MesurePDF, profil: ProfilDocument) -> int:
    """Plus petit niveau qui devrait suffire, d'après le dépassement mesuré."""
    if niveau_actuel >= NIVEAU_MAX:
        return NIVEAU_MAX
    ratio = mesure.depassement / mesure.capacite
    gain_actuel = profil.gains[niveau_actuel]
    gain_necessaire = 1 - (1 - gain_actuel) / (1 + ratio) + 0.005  # petite marge de sécurité
    for candidat in range(niveau_actuel + 1, NIVEAU_MAX + 1):
        if profil.gains[candidat] >= gain_necessaire:
            return candidat
    return NIVEAU_MAX


def niveau_inferieur_suffirait(niveau: int, mesure: MesurePDF, profil: ProfilDocument) -> bool:
    """Après une réussite, indique si le niveau juste en dessous aurait très
    probablement suffi (beaucoup d'espace libre en bas de page) : sert à
    redescendre progressivement le niveau mémorisé pour le CV, sans
    conversion supplémentaire."""
    if niveau <= 0 or mesure.pages != 1:
        return False
    gain_en_trop = (profil.gains[niveau] - profil.gains[niveau - 1]) * mesure.capacite
    return mesure.espace_libre > gain_en_trop * 1.5 + 6


# ---------------------------------------------------------------------------
# Boucle « convertir, vérifier, resserrer si besoin »
# ---------------------------------------------------------------------------


@dataclass
class ResultatMiseEnPage:
    chemin_pdf: Path | None
    pages: int
    niveau: int
    conversions: int
    methode: str = ""
    mesure: MesurePDF | None = None
    essais: list[tuple[int, int]] = field(default_factory=list)  # (niveau, pages)

    @property
    def une_page(self) -> bool:
        return self.chemin_pdf is not None and self.pages == 1

    @property
    def description(self) -> str:
        return NIVEAUX[self.niveau].description()


Convertisseur = Callable[[Path], tuple[Path, str]]


def ajuster_sur_une_page(
    chemin_docx: Path,
    convertir: Convertisseur,
    *,
    profil: ProfilDocument,
    niveau_depart: int = 0,
    conversions_max: int = 4,
) -> ResultatMiseEnPage:
    """Convertit `chemin_docx` en PDF et le resserre si besoin jusqu'à ce que
    le PDF tienne sur une page (ou que le niveau maximal soit atteint).

    `convertir(chemin_docx)` doit renvoyer (chemin_pdf, nom_de_la_methode).
    Le .docx final (celui livré à l'utilisateur) correspond toujours
    exactement au PDF final. Les erreurs de conversion remontent telles
    quelles à l'appelant.
    """
    original = chemin_docx.read_bytes()
    niveau = max(0, min(NIVEAU_MAX, niveau_depart))
    essais: list[tuple[int, int]] = []
    conversions = 0
    while True:
        contenu = compacter_docx(original, NIVEAUX[niveau], profil)
        chemin_docx.write_bytes(contenu)
        chemin_pdf, methode = convertir(chemin_docx)
        conversions += 1
        marge_haut, marge_bas = marges_points(contenu)
        mesure = mesurer_pdf(chemin_pdf, marge_haut, marge_bas)
        essais.append((niveau, mesure.pages))
        termine = (
            mesure.pages <= 1
            or niveau >= NIVEAU_MAX
            or conversions >= conversions_max
        )
        if termine:
            return ResultatMiseEnPage(
                chemin_pdf=chemin_pdf,
                pages=mesure.pages,
                niveau=niveau,
                conversions=conversions,
                methode=methode,
                mesure=mesure,
                essais=essais,
            )
        niveau = niveau_suivant(niveau, mesure, profil)
        if conversions == conversions_max - 1:
            niveau = NIVEAU_MAX  # dernier essai autorisé : on tente le maximum avant d'abandonner


def lignes_en_trop_estimees(resultat: ResultatMiseEnPage, hauteur_ligne: float = 12.5) -> int:
    """Pour un message d'aide quand même le niveau maximal ne suffit pas."""
    if resultat.mesure is None or resultat.pages <= 1:
        return 0
    return max(1, math.ceil(resultat.mesure.depassement / hauteur_ligne))
