"""
Profils de recherche : alternance, stage, job étudiant.

Chaque profil a sa propre description de ce que tu cherches (utilisée par
l'IA), son CV par défaut, son style de lettre et sa propre liste de
candidatures. Les coordonnées (en-tête des lettres) restent communes.
Une candidature enregistrée sans profil (anciennes versions de l'app) compte
comme une candidature d'alternance.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Recherche:
    cle: str
    libelle: str  # « Alternance »
    icone: str  # icône Material
    titre_rapport: str  # « Recherche d’alternance »
    objet_exemple: str  # objet type, pour l'aperçu de l'en-tête de lettre
    resume: str  # ce que change le profil, en une phrase pour l'interface
    aide_contexte: str  # exemple de description pour le champ du profil
    regle: str  # consigne de rédaction donnée à l'IA
    nom_contrat_en: str  # pour une lettre en anglais


RECHERCHES: dict[str, Recherche] = {
    "alternance": Recherche(
        cle="alternance",
        libelle="Alternance",
        icone="school",
        titre_rapport="Recherche d’alternance",
        objet_exemple="Candidature pour un poste en alternance",
        resume="lettre classique qui relie ta formation au poste et parle du rythme école/entreprise",
        aide_contexte="Formation suivie, rythme de l'alternance (ex : 3 semaines en entreprise, 1 à l'école), "
                      "durée du contrat, date de début...",
        regle="Le candidat recherche un contrat en alternance (rythme école/entreprise) : mentionne-le "
              "naturellement, ainsi que le rythme et la durée si le contexte les indique.",
        nom_contrat_en="work-study programme (apprenticeship)",
    ),
    "stage": Recherche(
        cle="stage",
        libelle="Stage",
        icone="work_history",
        titre_rapport="Recherche de stage",
        objet_exemple="Candidature pour un stage",
        resume="lettre classique centrée sur ce que tu veux apprendre et apporter pendant le stage",
        aide_contexte="Formation, stage obligatoire ou non, durée et période (ex : 2 mois à partir d'avril), "
                      "convention de stage fournie par l'école...",
        regle="Le candidat recherche un STAGE (avec convention de stage de son établissement), pas un emploi "
              "ni une alternance : indique la durée et la période du stage si le contexte les donne, montre ce "
              "que le candidat veut apprendre et ce qu'il peut apporter concrètement à l'équipe pendant cette "
              "période. Ne parle jamais d'alternance.",
        nom_contrat_en="internship",
    ),
    "job": Recherche(
        cle="job",
        libelle="Job étudiant",
        icone="storefront",
        titre_rapport="Recherche de job étudiant",
        objet_exemple="Candidature pour un job étudiant",
        resume="lettre plus courte et directe, centrée sur tes disponibilités et ton sérieux",
        aide_contexte="Disponibilités (soirs, week-ends, vacances), nombre d'heures par semaine, permis ou "
                      "véhicule, secteur visé (vente, restauration, logistique, intérim...)",
        regle="Le candidat recherche un JOB ÉTUDIANT ou une mission d'intérim, à temps partiel, en parallèle de "
              "ses études, pas une alternance ni un stage : la lettre est plus courte (corps de 800 à 1 300 "
              "caractères, en 3 paragraphes, ce qui prime sur la règle 5), simple et directe. Elle met en avant "
              "les disponibilités (reprises telles quelles du contexte, sans en inventer), la fiabilité, la "
              "ponctualité, le sens du service et les expériences de terrain du CV ; la formation est citée "
              "brièvement, sans développer de projet de carrière. Pas de jargon technique s'il n'est pas utile "
              "au poste.",
        nom_contrat_en="part-time student job",
    ),
}
DEFAUT = "alternance"


def recherche(cle: str | None) -> Recherche:
    return RECHERCHES.get(cle or "", RECHERCHES[DEFAUT])


def recherche_de(entree: dict[str, Any]) -> str:
    """Profil d'une candidature enregistrée (alternance pour les anciennes)."""
    valeur = entree.get("recherche")
    return valeur if valeur in RECHERCHES else DEFAUT


def filtrer(historique: list[dict[str, Any]], cle: str) -> list[dict[str, Any]]:
    return [e for e in historique if recherche_de(e) == cle]


def reglages(profil: dict[str, Any], cle: str) -> dict[str, str]:
    """Description et CV par défaut d'un profil. Pour l'alternance, la
    description d'avant les profils (« contexte académique ») sert de repli."""
    propres = (profil.get("recherches") or {}).get(cle) or {}
    contexte = propres.get("contexte")
    if contexte is None and cle == DEFAUT:
        contexte = profil.get("contexte_academique", "")
    return {"contexte": contexte or "", "cv": propres.get("cv") or ""}


def avec_reglages(profil: dict[str, Any], cle: str, *, contexte: str, cv: str) -> dict[str, Any]:
    """Profil mis à jour avec les réglages d'un profil de recherche."""
    recherches_profil = dict(profil.get("recherches") or {})
    recherches_profil[cle] = {"contexte": contexte.strip(), "cv": cv}
    nouveau = {**profil, "recherches": recherches_profil}
    if cle == DEFAUT:
        nouveau["contexte_academique"] = contexte.strip()  # compatibilité avec les anciennes versions
    return nouveau
