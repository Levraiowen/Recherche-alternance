"""
Extraction et édition "en place" d'un CV Word (.docx).

Principe : on repère chaque bloc de texte du document (paragraphes du corps,
cellules de tableaux, en-têtes/pieds de page) et on leur donne un identifiant
stable. L'IA reçoit ces blocs, propose un nouveau texte pour ceux qui doivent
changer, et on réinjecte ce texte dans le document d'origine EN CONSERVANT
la mise en forme : un libellé en gras en début de ligne (« Langages de
programmation : ... »), une date en italique grise en fin de ligne
(« ... | 2026 – 2027 »), etc. restent tels quels si l'IA ne les a pas
réécrits.

Garde-fous :
- Certains blocs ne sont jamais modifiés (coordonnées, liens, titres de
  section en majuscules, paragraphes contenant une image, un champ Word, des
  modifications suivies ou un contrôle de contenu) : ils sont envoyés à l'IA
  comme contexte, marqués "modifiable": false.
- Une adaptation nettement plus longue que le texte d'origine est ignorée
  (elle risquerait d'ajouter des lignes et de faire déborder le CV) ; elle
  est signalée dans le rapport renvoyé.

Limite connue (voir README) : le texte contenu dans des zones de texte,
images ou SmartArt n'est pas détecté (python-docx ne les lit pas).
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator

from docx import Document
from docx.oxml.ns import qn
from docx.text.paragraph import Paragraph
from docx.text.run import Run

# Tolérance de longueur pour une adaptation : au-delà, on garde le texte
# d'origine (une ligne de plus dans un CV déjà plein = débordement assuré).
TOLERANCE_RELATIVE = 0.10
TOLERANCE_MIN_CARACTERES = 6

_MOTIF_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_MOTIF_TELEPHONE = re.compile(r"(?:\+33\s?|0)[1-9](?:[\s.-]?\d{2}){4}")
_MOTIF_URL = re.compile(r"(https?://|www\.|linkedin\.com|github\.com)", re.IGNORECASE)


@dataclass
class BlocTexte:
    id: str
    texte: str
    longueur: int
    modifiable: bool = True

    @property
    def longueur_max(self) -> int:
        """Longueur au-delà de laquelle une adaptation est refusée."""
        return self.longueur + max(TOLERANCE_MIN_CARACTERES, round(self.longueur * TOLERANCE_RELATIVE))


@dataclass
class RapportAdaptations:
    """Ce qui a réellement été appliqué au CV, pour l'afficher à l'utilisateur."""

    appliques: list[str] = field(default_factory=list)
    ignores: dict[str, str] = field(default_factory=dict)  # id -> raison


def _paragraphes_non_vides(paragraphes, prefixe: str) -> Iterator[tuple[str, Paragraph]]:
    for i, p in enumerate(paragraphes):
        if p.text.strip():
            yield f"{prefixe}{i}", p


def _iterer_paragraphes_identifies(document) -> Iterator[tuple[str, Paragraph]]:
    """Parcourt le document dans un ordre déterministe et stable.

    Utilisé à la fois pour l'extraction et pour la réinjection : les deux
    passes doivent absolument produire les mêmes identifiants pour les mêmes
    paragraphes, donc toute la logique de parcours vit ici, une seule fois.
    """
    # Corps du document
    yield from _paragraphes_non_vides(document.paragraphs, "p")

    # Tableaux (ex: en-tête nom + photo, mise en page en colonnes)
    for ti, table in enumerate(document.tables):
        for ri, row in enumerate(table.rows):
            for ci, cell in enumerate(row.cells):
                yield from _paragraphes_non_vides(cell.paragraphs, f"t{ti}_r{ri}_c{ci}_p")

    # En-têtes / pieds de page (parfois utilisés pour le nom ou un titre)
    for si, section in enumerate(document.sections):
        yield from _paragraphes_non_vides(section.header.paragraphs, f"h{si}_p")
        yield from _paragraphes_non_vides(section.footer.paragraphs, f"f{si}_p")


# Contenus qu'une réécriture « run par run » abîmerait : liens, champs, images,
# modifications suivies (insertion/suppression non acceptées), contrôles de
# contenu des modèles de CV Word, balises intelligentes, équations...
_BALISES_PROTEGEES = tuple(qn(b) for b in (
    "w:hyperlink", "w:fldSimple", "w:fldChar", "w:drawing", "w:pict", "w:object", "w:ins", "w:del",
    "w:moveFrom", "w:moveTo", "w:sdt", "w:smartTag", "w:customXml", "w:subDoc", "w:ruby",
)) + ("{http://schemas.openxmlformats.org/officeDocument/2006/math}oMath",)


def _sans_blancs(texte: str) -> str:
    return re.sub(r"\s+", "", texte)


def _est_protege(paragraphe: Paragraph) -> bool:
    """Blocs à ne jamais réécrire automatiquement."""
    element = paragraphe._p
    if any(element.find(".//" + balise) is not None for balise in _BALISES_PROTEGEES):
        return True
    # Filet de sécurité : du texte présent dans le paragraphe mais invisible
    # pour python-docx (structure Word inhabituelle) ne doit jamais être perdu.
    tout_le_texte = "".join(
        "-" if e.tag == qn("w:noBreakHyphen") else (e.text or "")
        for e in element.iter(qn("w:t"), qn("w:noBreakHyphen"))
    )
    if _sans_blancs(tout_le_texte) != _sans_blancs(paragraphe.text):
        return True
    texte = paragraphe.text.strip()
    if _MOTIF_EMAIL.search(texte) or _MOTIF_TELEPHONE.search(texte) or _MOTIF_URL.search(texte):
        return True
    lettres = [c for c in texte if c.isalpha()]
    # Titre de section : court et entièrement en majuscules (« FORMATION »).
    if lettres and len(texte) <= 40 and all(c.isupper() for c in lettres):
        return True
    return False


def extraire_blocs(chemin_docx: Path) -> list[BlocTexte]:
    """Retourne la liste des blocs de texte détectés dans le CV, dans l'ordre."""
    document = Document(str(chemin_docx))
    return [
        BlocTexte(id=identifiant, texte=p.text, longueur=len(p.text), modifiable=not _est_protege(p))
        for identifiant, p in _iterer_paragraphes_identifies(document)
    ]


def texte_brut(blocs: list[BlocTexte]) -> str:
    """Vue à plat du contenu du CV, pour donner du contexte global à l'IA."""
    return "\n".join(b.texte for b in blocs)


# ---------------------------------------------------------------------------
# Remplacement de texte en conservant la mise en forme
# ---------------------------------------------------------------------------


def _signature_format(run: Run) -> bytes:
    rpr = run._r.rPr
    return b"" if rpr is None else rpr.xml.encode("utf-8")


def _segments(runs: list[Run]) -> list[tuple[str, Run]]:
    """Regroupe les runs consécutifs de même mise en forme : un paragraphe
    « Libellé (gras) + texte (normal) » donne 2 segments, quel que soit le
    nombre de runs internes créés par Word/LibreOffice."""
    segments: list[tuple[str, Run]] = []
    signature_precedente = None
    for run in runs:
        texte = run.text
        signature = _signature_format(run)
        if segments and signature == signature_precedente:
            segments[-1] = (segments[-1][0] + texte, segments[-1][1])
        else:
            segments.append((texte, run))
        signature_precedente = signature
    return [s for s in segments if s[0]]


def _decouper(nouveau: str, segments: list[tuple[str, Run]]) -> list[tuple[str, Run]]:
    """Répartit le nouveau texte entre les segments de mise en forme
    d'origine.

    1. Les segments de début dont le texte est inchangé (ex: libellé en
       gras) et les segments de fin inchangés (ex: dates en gris) sont
       conservés tels quels ; le reste du nouveau texte prend la mise en
       forme du premier segment « modifié ».
    2. Si l'IA a réécrit le libellé lui-même mais a gardé la structure
       « libellé : texte », on recoupe au même séparateur.
    3. Sinon, tout le texte prend la mise en forme majoritaire du
       paragraphe (celle qui couvre le plus de caractères), plutôt que celle
       du premier mot — qui est souvent un libellé en gras.
    """
    if len(segments) <= 1:
        return [(nouveau, segments[0][1])] if segments else []

    debut: list[tuple[str, Run]] = []
    position = 0
    for texte, run in segments[:-1]:
        if nouveau.startswith(texte, position):
            debut.append((texte, run))
            position += len(texte)
        else:
            break
    fin: list[tuple[str, Run]] = []
    fin_position = len(nouveau)
    for texte, run in reversed(segments[len(debut):]):
        if len(fin) >= len(segments) - len(debut) - 1:
            break  # garder au moins un segment pour le texte du milieu
        if fin_position - len(texte) >= position and nouveau.endswith(texte, 0, fin_position):
            fin.insert(0, (texte, run))
            fin_position -= len(texte)
        else:
            break
    milieu = nouveau[position:fin_position]
    if debut or fin:
        modele_milieu = segments[len(debut)][1]
        resultat = list(debut)
        if milieu:
            resultat.append((milieu, modele_milieu))
        return resultat + fin

    # Libellé réécrit mais structure « libellé : texte » conservée.
    premier_texte = segments[0][0]
    if premier_texte and not premier_texte.endswith(" ") and len(segments) >= 2:
        separateur = segments[1][0][:3]  # ex: " : "
        if separateur.strip() and separateur in nouveau:
            coupe = nouveau.index(separateur)
            if 0 < coupe <= 60:
                return [(nouveau[:coupe], segments[0][1]), (nouveau[coupe:], segments[1][1])]

    majoritaire = max(segments, key=lambda s: len(s[0]))[1]
    return [(nouveau, majoritaire)]


def _remplacer_texte_paragraphe(paragraphe: Paragraph, nouveau_texte: str) -> None:
    runs = [r for r in paragraphe.runs if r.text]
    if not runs:
        paragraphe.add_run(nouveau_texte)
        return
    morceaux = _decouper(nouveau_texte, _segments(runs))

    # On construit les nouveaux runs à partir de copies des runs modèles
    # (même police, taille, couleur, gras...), insérés à la place du
    # premier run d'origine, puis on retire les runs d'origine.
    ancre = runs[0]._r
    for texte, modele in morceaux:
        nouvel_element = copy.deepcopy(modele._r)
        for enfant in list(nouvel_element):
            if enfant.tag != qn("w:rPr"):
                nouvel_element.remove(enfant)
        ancre.addprevious(nouvel_element)
        Run(nouvel_element, paragraphe).text = texte
    for run in runs:
        run._r.getparent().remove(run._r)


def _normaliser(texte: str) -> str:
    return " ".join(texte.split())


def appliquer_adaptations(
    chemin_source: Path, chemin_destination: Path, adaptations: dict[str, str]
) -> RapportAdaptations:
    """Crée une copie du CV avec les blocs listés dans `adaptations` remplacés.

    Le fichier source (le CV de référence) n'est jamais modifié : le résultat
    est écrit dans `chemin_destination`. Le rapport indique les blocs
    réellement modifiés et ceux ignorés (avec la raison), pour que
    l'interface n'affiche jamais comme « appliqué » un changement absent du
    fichier final.
    """
    document = Document(str(chemin_source))
    rapport = RapportAdaptations()
    restants = dict(adaptations)
    for identifiant, paragraphe in _iterer_paragraphes_identifies(document):
        if identifiant not in restants:
            continue
        nouveau = restants.pop(identifiant).strip()
        bloc = BlocTexte(identifiant, paragraphe.text, len(paragraphe.text), not _est_protege(paragraphe))
        if not bloc.modifiable:
            rapport.ignores[identifiant] = "bloc protégé (coordonnées, lien, titre de section ou contenu Word spécial)"
        elif not nouveau:
            rapport.ignores[identifiant] = "texte proposé vide"
        elif _normaliser(nouveau) == _normaliser(bloc.texte):
            continue  # identique à l'original : rien à faire, rien à signaler
        elif len(nouveau) > bloc.longueur_max:
            rapport.ignores[identifiant] = (
                f"trop long ({len(nouveau)} caractères pour {bloc.longueur} à l'origine) : "
                "texte d'origine conservé pour ne pas faire déborder le CV"
            )
        else:
            _remplacer_texte_paragraphe(paragraphe, nouveau)
            rapport.appliques.append(identifiant)
    for identifiant in restants:
        rapport.ignores[identifiant] = "bloc introuvable dans le CV"

    chemin_destination.parent.mkdir(parents=True, exist_ok=True)
    document.save(str(chemin_destination))
    return rapport
