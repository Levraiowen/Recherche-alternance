"""
Rapport PDF de la recherche d'alternance : chiffres clés, entonnoir des
candidatures, activité dans le temps, sites d'emploi, délais de réponse,
relances à faire et liste détaillée.

Utile pour faire le point, ou pour justifier ses démarches (école, CFA,
France Travail). Le calcul (`calculer`) est séparé du rendu PDF
(`generer_pdf`) pour pouvoir être testé et affiché ailleurs.
"""

from __future__ import annotations

import io
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

import suivi

MOIS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre", "octobre",
        "novembre", "décembre"]
MOIS_COURTS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
PERIODES = ("Depuis le début", "30 derniers jours", "Ce mois-ci", "Mois dernier", "Personnalisée")


def date_longue(jour: date) -> str:
    return f"{'1er' if jour.day == 1 else jour.day} {MOIS[jour.month - 1]} {jour.year}"


def date_courte(jour: date | None) -> str:
    return f"{jour.day} {MOIS_COURTS[jour.month - 1]}" if jour else ""


# ---------------------------------------------------------------------------
# Calcul
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Periode:
    debut: date | None  # None : depuis la toute première candidature
    fin: date

    def contient(self, jour: date) -> bool:
        return (self.debut is None or jour >= self.debut) and jour <= self.fin


def periode(nom: str, aujourd_hui: date | None = None, debut: date | None = None,
            fin: date | None = None) -> Periode:
    """Période correspondant à un choix de l'interface (voir PERIODES)."""
    aujourd_hui = aujourd_hui or date.today()
    if nom == "30 derniers jours":
        return Periode(aujourd_hui - timedelta(days=29), aujourd_hui)
    if nom == "Ce mois-ci":
        return Periode(aujourd_hui.replace(day=1), aujourd_hui)
    if nom == "Mois dernier":
        fin_mois = aujourd_hui.replace(day=1) - timedelta(days=1)
        return Periode(fin_mois.replace(day=1), fin_mois)
    if nom == "Personnalisée" and (debut or fin):
        debut, fin = debut or fin, fin or aujourd_hui
        return Periode(min(debut, fin), max(debut, fin))
    return Periode(None, aujourd_hui)


@dataclass
class LigneSource:
    nom: str
    candidatures: int = 0
    envoyees: int = 0
    reponses: int = 0

    @property
    def taux(self) -> float | None:
        return self.reponses / self.envoyees if self.envoyees else None


@dataclass
class DonneesRapport:
    periode: Periode
    aujourd_hui: date
    candidatures: list[dict[str, Any]]  # de la plus récente à la plus ancienne
    total: int = 0
    envoyees: int = 0
    reponses: int = 0
    entretiens: int = 0
    acceptees: int = 0
    refusees: int = 0
    en_attente: int = 0
    delai_moyen: float | None = None
    score_moyen: float | None = None
    par_statut: list[tuple[str, int]] = field(default_factory=list)
    activite: list[tuple[str, int]] = field(default_factory=list)  # (libellé, nombre)
    activite_par: str = "semaine"
    sources: list[LigneSource] = field(default_factory=list)
    relances: list[suivi.Relance] = field(default_factory=list)

    @property
    def taux_reponse(self) -> float | None:
        return self.reponses / self.envoyees if self.envoyees else None

    @property
    def premiere(self) -> date | None:
        jours = [j for j in (_jour(e) for e in self.candidatures) if j]
        return min(jours) if jours else None

    @property
    def libelle_periode(self) -> str:
        debut, fin = self.periode.debut or self.premiere or self.periode.fin, self.periode.fin
        if debut == fin:
            return f"Le {date_longue(fin)}"
        if debut.year == fin.year:  # « Du 8 octobre au 23 novembre 2026 »
            return f"Du {date_longue(debut).rsplit(' ', 1)[0]} au {date_longue(fin)}"
        return f"Du {date_longue(debut)} au {date_longue(fin)}"

    @property
    def suivi_utilise(self) -> bool:
        return any(suivi.statut(e) for e in self.candidatures)


def _jour(entree: dict[str, Any]) -> date | None:
    try:
        return datetime.fromisoformat(str(entree.get("date") or "")).date()
    except ValueError:
        return None


def _activite(candidatures: list[dict[str, Any]], debut: date, fin: date) -> tuple[list[tuple[str, int]], str]:
    """Candidatures préparées par semaine (jusqu'à 16 semaines), sinon par mois."""
    jours = [j for j in (_jour(e) for e in candidatures) if j]
    if (fin - debut).days <= 16 * 7:
        lundi = debut - timedelta(days=debut.weekday())
        comptes: dict[date, int] = {}
        while lundi <= fin:
            comptes[lundi] = 0
            lundi += timedelta(weeks=1)
        for jour in jours:
            cle = jour - timedelta(days=jour.weekday())
            if cle in comptes:
                comptes[cle] += 1
        return [(date_courte(lundi), n) for lundi, n in comptes.items()], "semaine"
    mois: dict[tuple[int, int], int] = {}
    curseur = date(debut.year, debut.month, 1)
    while curseur <= fin:
        mois[(curseur.year, curseur.month)] = 0
        curseur = (curseur + timedelta(days=32)).replace(day=1)
    for jour in jours:
        if (jour.year, jour.month) in mois:
            mois[(jour.year, jour.month)] += 1
    return [(f"{MOIS_COURTS[m - 1]} {str(a)[2:]}", n) for (a, m), n in mois.items()], "mois"


def calculer(historique: list[dict[str, Any]], choix: Periode, aujourd_hui: date | None = None) -> DonneesRapport:
    aujourd_hui = aujourd_hui or date.today()
    candidatures = [e for e in historique if (_jour(e) and choix.contient(_jour(e)))]
    candidatures.sort(key=lambda e: e.get("date") or "", reverse=True)
    donnees = DonneesRapport(periode=choix, aujourd_hui=aujourd_hui, candidatures=candidatures)
    statuts = Counter(suivi.statut(e) for e in candidatures)
    donnees.total = len(candidatures)
    donnees.envoyees = sum(statuts[c] for c in suivi.STATUTS_ENVOYES)
    donnees.reponses = sum(statuts[c] for c in suivi.STATUTS_REPONSE)
    donnees.entretiens = statuts["entretien"] + statuts["acceptee"]
    donnees.acceptees = statuts["acceptee"]
    donnees.refusees = statuts["refusee"]
    donnees.en_attente = statuts["envoyee"] + statuts["relancee"]
    donnees.par_statut = [(cle, statuts[cle]) for cle in suivi.STATUTS if statuts[cle]]
    delais = [d for d in (suivi.delai_reponse(e) for e in candidatures) if d is not None]
    donnees.delai_moyen = sum(delais) / len(delais) if delais else None
    scores = [e["score"] for e in candidatures if isinstance(e.get("score"), int)]
    donnees.score_moyen = sum(scores) / len(scores) if scores else None
    debut = choix.debut or donnees.premiere or choix.fin
    donnees.activite, donnees.activite_par = _activite(candidatures, debut, choix.fin)
    sources: dict[str, LigneSource] = {}
    for entree in candidatures:
        ligne = sources.setdefault(suivi.source_offre(entree), LigneSource(suivi.source_offre(entree)))
        ligne.candidatures += 1
        ligne.envoyees += suivi.statut(entree) in suivi.STATUTS_ENVOYES
        ligne.reponses += suivi.statut(entree) in suivi.STATUTS_REPONSE
    donnees.sources = sorted(sources.values(), key=lambda s: (s.nom == "Non renseignée", -s.candidatures, s.nom))
    donnees.relances = suivi.candidatures_a_relancer(candidatures, aujourd_hui)
    return donnees


def pourcentage(valeur: float | None) -> str:
    return "—" if valeur is None else f"{round(valeur * 100)} %"


def phrase_resume(donnees: DonneesRapport) -> str:
    """Résumé en une phrase, ex : « 12 candidatures préparées, 8 envoyées,
    3 réponses (38 %) et 2 entretiens. »"""
    if not donnees.total:
        return "Aucune candidature sur cette période."
    pluriel = "s" if donnees.total > 1 else ""
    debut = f"{donnees.total} candidature{pluriel} préparée{pluriel}"
    if not donnees.suivi_utilise:
        return debut + "."
    morceaux = [debut, f"{donnees.envoyees} envoyée{'s' if donnees.envoyees > 1 else ''}"]
    reponses = f"{donnees.reponses} réponse{'s' if donnees.reponses > 1 else ''}"
    if donnees.taux_reponse is not None:
        reponses += f" ({pourcentage(donnees.taux_reponse)})"
    morceaux.append(reponses)
    entretiens = f"{donnees.entretiens} entretien{'s' if donnees.entretiens > 1 else ''}"
    return ", ".join(morceaux) + f" et {entretiens}."


def constats(donnees: DonneesRapport) -> list[str]:
    """Quelques enseignements tirés des chiffres (sans jamais extrapoler)."""
    lignes = []
    if donnees.delai_moyen is not None:
        lignes.append(f"Délai moyen avant une réponse : {round(donnees.delai_moyen)} jours après l’envoi.")
    efficaces = [s for s in donnees.sources if s.envoyees >= 2 and s.nom != "Non renseignée" and s.reponses]
    if efficaces:
        meilleure = max(efficaces, key=lambda s: (s.taux or 0, s.reponses))
        lignes.append(f"Site le plus efficace : {meilleure.nom}, avec {meilleure.reponses} réponse"
                      f"{'s' if meilleure.reponses > 1 else ''} pour {meilleure.envoyees} envois.")
    if donnees.score_moyen is not None:
        lignes.append(f"Correspondance moyenne estimée entre le CV et les offres : {round(donnees.score_moyen)} %.")
    if donnees.relances:
        nombre = len(donnees.relances)
        lignes.append(f"{nombre} candidature{'s' if nombre > 1 else ''} à relancer (sans réponse depuis plus de "
                      f"{suivi.DELAI_RELANCE_JOURS} jours).")
    return lignes


# ---------------------------------------------------------------------------
# Rendu PDF
# ---------------------------------------------------------------------------

DOSSIER_POLICES = Path(__file__).resolve().parent.parent / "static" / "polices"
ENCRE = "#3346D3"
GRAPHITE = "#1B2030"
PLUME = "#5B6275"
FILET = "#E3E6EE"
BRUME = "#F3F5F9"
COULEURS_STATUT = {"gray": "#8A90A0", "blue": "#3346D3", "orange": "#C2711A", "violet": "#7A4FD0",
                   "green": "#2E8B57", "red": "#C8433B"}
_CARACTERES_HORS_POLICE = re.compile("[\U00010000-\U0010FFFF☀-➿️]")


def _polices() -> tuple[str, str, str, str, str]:
    """(texte, texte moyen, texte gras, titres, titres italique) : polices de
    l'app si elles sont disponibles, sinon les polices standard du PDF."""
    from reportlab.lib.fonts import addMapping
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont

    fichiers = {
        "Instrument": "InstrumentSans_400Regular.ttf",
        "Instrument-Medium": "InstrumentSans_500Medium.ttf",
        "Instrument-SemiBold": "InstrumentSans_600SemiBold.ttf",
        "Spectral": "Spectral_500Medium.ttf",
        "Spectral-Italic": "Spectral_400Regular_Italic.ttf",
    }
    try:
        for nom, fichier in fichiers.items():
            if nom not in pdfmetrics.getRegisteredFontNames():
                pdfmetrics.registerFont(TTFont(nom, str(DOSSIER_POLICES / fichier)))
        addMapping("Instrument", 0, 0, "Instrument")
        addMapping("Instrument", 1, 0, "Instrument-SemiBold")
        addMapping("Instrument", 0, 1, "Instrument")
        addMapping("Instrument", 1, 1, "Instrument-SemiBold")
        return "Instrument", "Instrument-Medium", "Instrument-SemiBold", "Spectral", "Spectral-Italic"
    except Exception:  # noqa: BLE001 - police absente ou illisible : polices standard
        return "Helvetica", "Helvetica", "Helvetica-Bold", "Times-Roman", "Times-Italic"


def _texte(valeur: Any) -> str:
    """Texte sûr pour les paragraphes reportlab (balises échappées, emojis retirés)."""
    return escape(_CARACTERES_HORS_POLICE.sub("", str(valeur or "")).strip())


def generer_pdf(donnees: DonneesRapport, *, nom: str = "", ville: str = "") -> bytes:
    from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
    from reportlab.lib.colors import HexColor
    from reportlab.lib.enums import TA_RIGHT
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.pdfgen import canvas as module_canvas
    from reportlab.platypus import (
        KeepTogether,
        LongTable,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    texte, moyen, gras, titre, italique = _polices()
    encre, graphite, plume, filet = HexColor(ENCRE), HexColor(GRAPHITE), HexColor(PLUME), HexColor(FILET)
    marge, retrait = 16 * mm, 6  # le cadre de reportlab ajoute 6 pt de retrait de chaque côté
    bord = marge + retrait  # bord gauche réel du contenu (aligné avec le pied de page)
    largeur_utile = A4[0] - 2 * bord

    def style(nom_style: str, **options) -> ParagraphStyle:
        base = {"fontName": texte, "fontSize": 9.5, "leading": 13.5, "textColor": graphite}
        base.update(options)
        return ParagraphStyle(nom_style, **base)

    s_titre = style("titre", fontName=titre, fontSize=26, leading=30)
    s_sous_titre = style("sous_titre", textColor=plume, fontSize=10.5, leading=14.5)
    s_date = style("date", fontName=italique, fontSize=11, leading=14, textColor=plume, alignment=TA_RIGHT)
    s_resume = style("resume", fontName=titre, fontSize=15, leading=21)
    s_section = style("section", fontName=titre, fontSize=14, leading=18, spaceBefore=16, spaceAfter=8)
    s_corps = style("corps")
    s_cellule = style("cellule", fontSize=8.5, leading=11)
    s_cellule_gras = style("cellule_gras", fontName=moyen, fontSize=8.5, leading=11)
    s_entete = style("entete", fontName=moyen, fontSize=8, leading=10, textColor=plume)
    s_nombre = style("nombre", fontName=titre, fontSize=24, leading=27)
    s_libelle = style("libelle", fontSize=8.5, leading=11, textColor=plume)

    elements: list[Any] = []
    # --- En-tête : titre à gauche, lieu et date « comme sur une lettre » à droite
    ligne_date = f"{ville}, le {date_longue(donnees.aujourd_hui)}" if ville else date_longue(donnees.aujourd_hui)
    entete = Table(
        [[Paragraph("Recherche d’alternance", s_titre), Paragraph(_texte(ligne_date), s_date)],
         [Paragraph(_texte(nom) + "<br/>" + _texte(donnees.libelle_periode), s_sous_titre), ""]],
        colWidths=[largeur_utile * 0.62, largeur_utile * 0.38],
    )
    entete.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "BOTTOM"), ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0), ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]))
    elements += [entete, Spacer(1, 9 * mm), Paragraph(_texte(phrase_resume(donnees)), s_resume), Spacer(1, 6 * mm)]

    # --- Chiffres clés
    chiffres = [("Préparées", str(donnees.total))]
    if donnees.suivi_utilise:
        chiffres += [("Envoyées", str(donnees.envoyees)), ("Réponses", str(donnees.reponses)),
                     ("Taux de réponse", pourcentage(donnees.taux_reponse)), ("Entretiens", str(donnees.entretiens))]
    cellules = [[Paragraph(valeur, s_nombre) for _, valeur in chiffres],
                [Paragraph(libelle, s_libelle) for libelle, _ in chiffres]]
    bandeau = Table(cellules, colWidths=[largeur_utile / 5] * len(chiffres), hAlign="LEFT")
    bandeau.setStyle(TableStyle([
        ("LINEABOVE", (0, 0), (-1, 0), 0.6, filet), ("LINEBELOW", (0, -1), (-1, -1), 0.6, filet),
        ("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, 0), 10),
        ("BOTTOMPADDING", (0, -1), (-1, -1), 10),
    ]))
    elements.append(bandeau)

    lignes_constats = constats(donnees)
    if lignes_constats:
        elements.append(Spacer(1, 5 * mm))
        elements += [Paragraph(_texte(ligne), s_corps) for ligne in lignes_constats]

    # --- Entonnoir
    if donnees.suivi_utilise and donnees.total:
        etapes = [("Préparées", donnees.total), ("Envoyées", donnees.envoyees), ("Réponses", donnees.reponses),
                  ("Entretiens", donnees.entretiens), ("Acceptées", donnees.acceptees)]
        hauteur_ligne, marge_libelle = 7 * mm, 26 * mm
        dessin = Drawing(largeur_utile, hauteur_ligne * len(etapes))
        longueur_max = largeur_utile - marge_libelle - 14 * mm
        for rang, (libelle, nombre) in enumerate(etapes):
            y = dessin.height - (rang + 1) * hauteur_ligne + 2 * mm
            dessin.add(String(0, y + 1.2 * mm, libelle, fontName=texte, fontSize=9, fillColor=graphite))
            dessin.add(Rect(marge_libelle, y, longueur_max, 3.6 * mm, fillColor=HexColor(BRUME), strokeColor=None))
            longueur = longueur_max * nombre / donnees.total if donnees.total else 0
            if longueur:
                dessin.add(Rect(marge_libelle, y, max(longueur, 1.2 * mm), 3.6 * mm, fillColor=encre,
                                strokeColor=None, fillOpacity=1 - rang * 0.14))
            dessin.add(String(marge_libelle + longueur_max + 3 * mm, y + 1.2 * mm, str(nombre),
                              fontName=moyen, fontSize=9, fillColor=graphite))
        elements += [Paragraph("Entonnoir des candidatures", s_section), dessin]

    # --- Activité dans le temps
    if donnees.activite and donnees.total:
        hauteur = 34 * mm
        dessin = Drawing(largeur_utile, hauteur + 8 * mm)
        maximum = max(n for _, n in donnees.activite) or 1
        pas = largeur_utile / len(donnees.activite)
        largeur_barre = min(pas * 0.56, 9 * mm)
        frequence = max(1, round(len(donnees.activite) / 8))  # au plus ~8 étiquettes lisibles
        dessin.add(Line(0, 6 * mm, largeur_utile, 6 * mm, strokeColor=filet, strokeWidth=0.6))
        for rang, (libelle, nombre) in enumerate(donnees.activite):
            x = rang * pas + (pas - largeur_barre) / 2
            h = (hauteur - 6 * mm) * nombre / maximum
            if nombre:
                dessin.add(Rect(x, 6 * mm, largeur_barre, h, fillColor=encre, strokeColor=None))
                dessin.add(String(x + largeur_barre / 2, 6 * mm + h + 1.5 * mm, str(nombre), fontName=moyen,
                                  fontSize=7.5, fillColor=graphite, textAnchor="middle"))
            if rang % frequence == 0:
                dessin.add(String(x + largeur_barre / 2, 1.6 * mm, libelle, fontName=texte, fontSize=7,
                                  fillColor=plume, textAnchor="middle"))
        titre_activite = "Candidatures préparées par " + ("semaine" if donnees.activite_par == "semaine" else "mois")
        elements.append(KeepTogether([Paragraph(titre_activite, s_section), dessin]))

    def tableau(entetes: list[str], lignes: list[list[Any]], largeurs: list[float], long: bool = False) -> Table:
        donnees_tableau = [[Paragraph(e, s_entete) for e in entetes]] + lignes
        classe = LongTable if long else Table
        t = classe(donnees_tableau, colWidths=largeurs, repeatRows=1, hAlign="LEFT")
        t.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, graphite),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, filet),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 4.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 4.5),
        ]))
        return t

    # --- Sites d'emploi
    if donnees.sources and any(s.nom != "Non renseignée" for s in donnees.sources):
        lignes = [[Paragraph(_texte(s.nom), s_cellule_gras), Paragraph(str(s.candidatures), s_cellule),
                   Paragraph(str(s.envoyees), s_cellule), Paragraph(str(s.reponses), s_cellule),
                   Paragraph(pourcentage(s.taux), s_cellule)] for s in donnees.sources]
        largeurs = [largeur_utile * f for f in (0.4, 0.15, 0.15, 0.15, 0.15)]
        elements.append(KeepTogether([
            Paragraph("Par site d’emploi", s_section),
            tableau(["Site", "Préparées", "Envoyées", "Réponses", "Taux de réponse"], lignes, largeurs),
        ]))

    # --- Relances à faire
    if donnees.relances:
        lignes = [[Paragraph(_texte(r.entree.get("entreprise")), s_cellule_gras),
                   Paragraph(_texte(r.entree.get("poste")), s_cellule),
                   Paragraph(date_courte(suivi.date_envoi(r.entree)), s_cellule),
                   Paragraph(f"{r.jours} jours" + (" (2e relance)" if r.deuxieme else ""), s_cellule)]
                  for r in donnees.relances]
        largeurs = [largeur_utile * f for f in (0.32, 0.36, 0.14, 0.18)]
        elements.append(KeepTogether([
            Paragraph("À relancer", s_section),
            tableau(["Entreprise", "Poste", "Envoyée le", "Sans réponse depuis"], lignes, largeurs),
        ]))

    # --- Détail
    elements.append(Paragraph("Détail des candidatures", s_section))
    if donnees.candidatures:
        lignes = []
        for entree in donnees.candidatures:
            cle = suivi.statut(entree)
            nom_statut, _, couleur = suivi.STATUTS[cle]
            pastille = Drawing(8, 8)
            pastille.add(Circle(3, 3, 2.6, fillColor=HexColor(COULEURS_STATUT.get(couleur, PLUME)), strokeColor=None))
            statut_cellule = Table([[pastille, Paragraph(nom_statut, s_cellule)]], colWidths=[9, None])
            statut_cellule.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                                                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                                ("TOPPADDING", (0, 0), (-1, -1), 0),
                                                ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
                                                ("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
            delai = suivi.delai_reponse(entree)
            score = entree.get("score")
            lignes.append([
                Paragraph(date_courte(_jour(entree)), s_cellule),
                Paragraph(_texte(entree.get("entreprise")) or "—", s_cellule_gras),
                Paragraph(_texte(entree.get("poste")) or "—", s_cellule),
                statut_cellule,
                Paragraph(date_courte(suivi.date_envoi(entree)), s_cellule),
                Paragraph(f"{delai} j" if delai is not None else "", s_cellule),
                Paragraph(f"{score} %" if isinstance(score, int) else "", s_cellule),
            ])
        largeurs = [largeur_utile * f for f in (0.09, 0.24, 0.27, 0.15, 0.09, 0.08, 0.08)]
        elements.append(tableau(["Date", "Entreprise", "Poste", "Statut", "Envoyée", "Réponse", "Score"],
                                lignes, largeurs, long=True))
    else:
        elements.append(Paragraph("Aucune candidature sur cette période.", s_corps))

    pied = "Rapport généré par l’app Candidatures alternance"

    class CanevasNumerote(module_canvas.Canvas):
        """Ajoute « page n / total » en pied de page (le total n'est connu qu'à la fin)."""

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._pages: list[dict] = []

        def showPage(self):  # noqa: N802 - nom imposé par reportlab
            self._pages.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._pages)
            for etat in self._pages:
                self.__dict__.update(etat)
                self.setStrokeColor(filet)
                self.setLineWidth(0.6)
                self.line(bord, 14 * mm, A4[0] - bord, 14 * mm)
                self.setFont(texte, 7.5)
                self.setFillColor(plume)
                self.drawString(bord, 9.5 * mm, pied)
                self.drawRightString(A4[0] - bord, 9.5 * mm, f"{self._pageNumber} / {total}")
                super().showPage()
            super().save()

    tampon = io.BytesIO()
    document = SimpleDocTemplate(tampon, pagesize=A4, leftMargin=marge, rightMargin=marge, topMargin=16 * mm,
                                 bottomMargin=22 * mm, title="Rapport de recherche d’alternance",
                                 author=nom or "", subject=donnees.libelle_periode)
    document.build(elements, canvasmaker=CanevasNumerote)
    return tampon.getvalue()


def nom_fichier(donnees: DonneesRapport) -> str:
    return f"Rapport_candidatures_{donnees.aujourd_hui.isoformat()}.pdf"
