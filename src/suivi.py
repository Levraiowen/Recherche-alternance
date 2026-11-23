"""
Suivi FACULTATIF des candidatures : statut (envoyée, relancée, entretien...),
dates, notes, rappels de relance et statistiques.

Rien n'est obligatoire : une candidature sans statut reste simplement
« Générée », et l'app fonctionne exactement pareil si l'on n'utilise jamais
le suivi.
"""

from __future__ import annotations

import csv
import io
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import stockage

# Clé enregistrée -> (libellé, emoji, couleur de badge Streamlit)
STATUTS: dict[str, tuple[str, str, str]] = {
    "": ("Générée", "📝", "gray"),
    "envoyee": ("Envoyée", "📤", "blue"),
    "relancee": ("Relancée", "🔔", "orange"),
    "entretien": ("Entretien", "🎤", "violet"),
    "acceptee": ("Acceptée", "✅", "green"),
    "refusee": ("Refusée", "❌", "red"),
    "abandonnee": ("Pas envoyée", "🚫", "gray"),
}
STATUTS_ENVOYES = ("envoyee", "relancee", "entretien", "acceptee", "refusee")
STATUTS_REPONSE = ("entretien", "acceptee", "refusee")
DELAI_RELANCE_JOURS = 10  # après l'envoi, sans réponse
DELAI_DEUXIEME_RELANCE_JOURS = 14  # après une première relance


def statut(entree: dict[str, Any]) -> str:
    valeur = entree.get("statut") or ""
    return valeur if valeur in STATUTS else ""


def libelle(cle: str) -> str:
    nom, emoji, _ = STATUTS.get(cle, STATUTS[""])
    return f"{emoji} {nom}"


def badge(cle: str) -> str:
    """Badge coloré en markdown Streamlit, ex: :blue-badge[📤 Envoyée]."""
    nom, emoji, couleur = STATUTS.get(cle, STATUTS[""])
    return f":{couleur}-badge[{emoji} {nom}]"


def _date(valeur: Any) -> date | None:
    if not valeur:
        return None
    try:
        return datetime.fromisoformat(str(valeur)).date()
    except ValueError:
        return None


def date_envoi(entree: dict[str, Any]) -> date | None:
    return _date(entree.get("date_envoi"))


def changer_statut(identifiant: str, nouveau: str, *, le: date | None = None) -> None:
    """Met à jour le statut et date automatiquement l'envoi / la relance."""
    if nouveau not in STATUTS:
        raise ValueError(f"Statut inconnu : {nouveau}")
    entree = next((e for e in stockage.charger_historique() if stockage.identifiant_entree(e) == identifiant), None)
    if entree is None:
        return
    jour = (le or date.today()).isoformat()
    modifications: dict[str, Any] = {"statut": nouveau}
    if nouveau in STATUTS_ENVOYES and not entree.get("date_envoi"):
        modifications["date_envoi"] = jour
    if nouveau == "relancee":
        modifications["date_relance"] = jour
    stockage.mettre_a_jour_historique(identifiant, modifications)


@dataclass
class Relance:
    entree: dict[str, Any]
    jours: int  # jours écoulés depuis l'envoi (ou la dernière relance)
    deuxieme: bool


def candidatures_a_relancer(historique: list[dict[str, Any]], aujourd_hui: date | None = None) -> list[Relance]:
    """Candidatures envoyées restées sans réponse depuis un moment."""
    aujourd_hui = aujourd_hui or date.today()
    resultat: list[Relance] = []
    for entree in historique:
        cle = statut(entree)
        if cle == "envoyee":
            depuis = date_envoi(entree)
            seuil, deuxieme = DELAI_RELANCE_JOURS, False
        elif cle == "relancee":
            depuis = _date(entree.get("date_relance")) or date_envoi(entree)
            seuil, deuxieme = DELAI_DEUXIEME_RELANCE_JOURS, True
        else:
            continue
        if depuis and (aujourd_hui - depuis).days >= seuil and not entree.get("relance_ignoree"):
            resultat.append(Relance(entree, (aujourd_hui - depuis).days, deuxieme))
    return sorted(resultat, key=lambda r: -r.jours)


@dataclass
class Statistiques:
    total: int
    envoyees: int
    reponses: int
    entretiens: int
    par_statut: Counter
    par_semaine: dict[str, int]  # "2026-11-16" (lundi) -> nombre de candidatures générées

    @property
    def taux_reponse(self) -> float | None:
        return self.reponses / self.envoyees if self.envoyees else None


def statistiques(historique: list[dict[str, Any]], semaines: int = 12, aujourd_hui: date | None = None) -> Statistiques:
    aujourd_hui = aujourd_hui or date.today()
    par_statut = Counter(statut(e) for e in historique)
    lundi_courant = aujourd_hui - timedelta(days=aujourd_hui.weekday())
    par_semaine = {(lundi_courant - timedelta(weeks=i)).isoformat(): 0 for i in reversed(range(semaines))}
    for entree in historique:
        jour = _date(entree.get("date"))
        if jour is None:
            continue
        lundi = (jour - timedelta(days=jour.weekday())).isoformat()
        if lundi in par_semaine:
            par_semaine[lundi] += 1
    return Statistiques(
        total=len(historique),
        envoyees=sum(par_statut[c] for c in STATUTS_ENVOYES),
        reponses=sum(par_statut[c] for c in STATUTS_REPONSE),
        entretiens=par_statut["entretien"] + par_statut["acceptee"],
        par_statut=par_statut,
        par_semaine=par_semaine,
    )


# ---------------------------------------------------------------------------
# Export de la liste (pour la retravailler dans Excel ou LibreOffice Calc)
# ---------------------------------------------------------------------------

COLONNES_EXPORT = (
    ("Date", lambda e: (e.get("date") or "")[:10]),
    ("Entreprise", lambda e: e.get("entreprise", "")),
    ("Poste", lambda e: e.get("poste", "")),
    ("Statut", lambda e: STATUTS[statut(e)][0]),
    ("Envoyée le", lambda e: e.get("date_envoi", "")),
    ("Relancée le", lambda e: e.get("date_relance", "")),
    ("Correspondance (%)", lambda e: e.get("score") if isinstance(e.get("score"), int) else ""),
    ("E-mail du recruteur", lambda e: e.get("contact", "")),
    ("Lien de l'offre", lambda e: e.get("url_offre", "")),
    ("CV utilisé", lambda e: e.get("cv_reference", "")),
    ("Notes", lambda e: e.get("notes", "")),
)


def _cellule_sure(valeur: Any) -> str:
    """Un tableur exécute une cellule qui commence par = + - @ comme une
    formule : un nom d'entreprise piégé dans une annonce importée ne doit
    jamais pouvoir lancer quoi que ce soit à l'ouverture du fichier."""
    texte = "" if valeur is None else str(valeur)
    return "'" + texte if texte[:1] in ("=", "+", "-", "@", "\t", "\r") else texte


def exporter_csv(historique: list[dict[str, Any]]) -> bytes:
    """Liste des candidatures au format CSV « à la française » (séparateur ;
    et encodage reconnu par Excel), qui s'ouvre d'un double-clic."""
    tampon = io.StringIO()
    ecrivain = csv.writer(tampon, delimiter=";", lineterminator="\r\n")
    ecrivain.writerow([nom for nom, _ in COLONNES_EXPORT])
    for entree in historique:
        ecrivain.writerow([_cellule_sure(extraire(entree)) for _, extraire in COLONNES_EXPORT])
    return tampon.getvalue().encode("utf-8-sig")
