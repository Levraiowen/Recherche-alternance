"""
Point d'entrée unique pour la génération IA : bascule entre les fournisseurs
selon la variable d'environnement FOURNISSEUR_IA (voir .env.example).

- "gemini" (par défaut) : gratuit, via une clé API Gemini (aistudio.google.com).
- "anthropic" : payant à l'usage, via une clé API Anthropic (console.anthropic.com).

Le reste de l'app (app.py) importe uniquement ce module : le fournisseur
utilisé n'a donc aucun impact sur le reste du code.
"""

import os

from cv_editor import BlocTexte
from ia_commun import ErreurGeneration, ResultatGeneration  # noqa: F401 - réexporté pour app.py

FOURNISSEUR_PAR_DEFAUT = "gemini"
FOURNISSEURS_CONNUS = ("gemini", "anthropic")


def generer_candidature(
    *,
    blocs_cv: list[BlocTexte],
    texte_annonce: str,
    contexte_academique: str,
    entreprise_indiquee: str = "",
    poste_indique: str = "",
    consignes_supplementaires: str = "",
) -> ResultatGeneration:
    fournisseur = (os.environ.get("FOURNISSEUR_IA", "").strip().lower() or FOURNISSEUR_PAR_DEFAUT)

    if fournisseur == "gemini":
        import ia_gemini as module_fournisseur
    elif fournisseur == "anthropic":
        import ia_anthropic as module_fournisseur
    else:
        raise ErreurGeneration(
            f"FOURNISSEUR_IA={fournisseur!r} inconnu dans .env "
            f"(valeurs acceptées : {', '.join(FOURNISSEURS_CONNUS)})."
        )

    return module_fournisseur.generer_candidature(
        blocs_cv=blocs_cv,
        texte_annonce=texte_annonce,
        contexte_academique=contexte_academique,
        entreprise_indiquee=entreprise_indiquee,
        poste_indique=poste_indique,
        consignes_supplementaires=consignes_supplementaires,
    )


def fournisseur_actif() -> str:
    return (os.environ.get("FOURNISSEUR_IA", "").strip().lower() or FOURNISSEUR_PAR_DEFAUT)


def cle_api_presente() -> bool:
    """Vérifie qu'une clé est configurée pour le fournisseur actuellement actif."""
    if fournisseur_actif() == "gemini":
        return bool(os.environ.get("GEMINI_API_KEY", "").strip())
    return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())
