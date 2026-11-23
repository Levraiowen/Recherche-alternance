"""
Génération de la candidature via l'API Anthropic (Claude). Payant à l'usage
(non couvert par un abonnement claude.ai) : conservé pour qui préfère cette
option, mais ce n'est pas le mode par défaut de l'app (voir FOURNISSEUR_IA
dans .env). Pour le mode gratuit, voir ia_gemini.py.

Ordre de grandeur (tarifs publics de novembre 2026) : une candidature
consomme ~5 000 jetons en entrée et ~2 000 en sortie, soit environ 3
centimes avec Claude Sonnet 5.5 et environ 0,2 centime avec Claude Haiku
5.5 (ANTHROPIC_MODEL=claude-haiku-5-5 dans .env).
"""

from __future__ import annotations

import os

from cv_editor import BlocTexte
from ia_commun import (
    SCHEMA_CANDIDATURE,
    SYSTEME,
    ErreurGeneration,
    ResultatGeneration,
    construire_message_utilisateur,
    construire_resultat,
    valider_entrees,
)

MODELE_PAR_DEFAUT = "claude-sonnet-5-5"
NOM_OUTIL = "generer_candidature"

SCHEMA_OUTIL = {
    "name": NOM_OUTIL,
    "description": (
        "Produit le contenu d'une candidature (lettre de motivation + "
        "adaptations du CV) pour une offre d'emploi donnée."
    ),
    "input_schema": SCHEMA_CANDIDATURE,
}


def _message_erreur(exc: Exception) -> str:
    import anthropic

    if isinstance(exc, anthropic.AuthenticationError):
        return "Clé API Anthropic invalide : vérifie ANTHROPIC_API_KEY dans .env (console.anthropic.com > API Keys)."
    if isinstance(exc, anthropic.PermissionDeniedError):
        return f"Accès refusé par l'API Anthropic (clé ou modèle non autorisé) : {exc}"
    if isinstance(exc, anthropic.NotFoundError):
        return (
            "Modèle Claude introuvable : vérifie ANTHROPIC_MODEL dans .env (ou supprime la "
            f"ligne pour utiliser {MODELE_PAR_DEFAUT})."
        )
    if isinstance(exc, anthropic.RateLimitError):
        return "Limite de requêtes Anthropic atteinte : patiente une minute puis réessaie."
    if isinstance(exc, anthropic.APIConnectionError):
        return "Impossible de joindre l'API Anthropic (connexion Internet ?)."
    if isinstance(exc, anthropic.APIStatusError):
        texte = str(exc)
        if "credit balance" in texte.lower():
            return "Crédit Anthropic épuisé : recharge ton compte sur console.anthropic.com (Billing)."
        if exc.status_code in (500, 502, 503, 529):
            return "Les serveurs d'Anthropic sont momentanément surchargés : réessaie dans une minute."
        return f"Erreur de l'API Anthropic ({exc.status_code}) : {texte}"
    return f"Erreur inattendue lors de l'appel à Anthropic : {exc}"


def generer_candidature(
    *,
    blocs_cv: list[BlocTexte],
    texte_annonce: str,
    contexte_academique: str,
    entreprise_indiquee: str = "",
    poste_indique: str = "",
    consignes_supplementaires: str = "",
) -> ResultatGeneration:
    valider_entrees(texte_annonce, blocs_cv)

    cle = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not cle:
        raise ErreurGeneration(
            "Aucune clé API Anthropic configurée. Ajoute ANTHROPIC_API_KEY "
            "dans le fichier .env (voir .env.example) puis relance l'app."
        )

    message = construire_message_utilisateur(
        blocs_cv=blocs_cv,
        texte_annonce=texte_annonce,
        contexte_academique=contexte_academique,
        entreprise_indiquee=entreprise_indiquee,
        poste_indique=poste_indique,
        consignes_supplementaires=consignes_supplementaires,
    )

    modele = os.environ.get("ANTHROPIC_MODEL", MODELE_PAR_DEFAUT).strip() or MODELE_PAR_DEFAUT

    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=cle, max_retries=2)
        # Outil imposé (tool_choice) : la réponse arrive directement sous
        # forme d'objet JSON conforme au schéma, sans texte autour.
        reponse = client.messages.create(
            model=modele,
            max_tokens=8000,
            system=SYSTEME,
            tools=[SCHEMA_OUTIL],
            tool_choice={"type": "tool", "name": NOM_OUTIL},
            messages=[{"role": "user", "content": message}],
        )
    except ImportError as exc:
        raise ErreurGeneration(
            "Le module Python « anthropic » n'est pas installé : relance l'app via "
            "Lancer.bat ou lance pip install -r requirements.txt."
        ) from exc
    except Exception as exc:  # noqa: BLE001 - converti en message clair
        raise ErreurGeneration(_message_erreur(exc)) from exc

    bloc_outil = next((b for b in reponse.content if getattr(b, "type", None) == "tool_use"), None)
    if bloc_outil is None:
        raise ErreurGeneration("Réponse inattendue de l'IA (aucun résultat structuré reçu).")

    return construire_resultat(
        bloc_outil.input, entreprise_indiquee, poste_indique, modele=getattr(reponse, "model", modele)
    )
