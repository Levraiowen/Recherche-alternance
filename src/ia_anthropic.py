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
    ErreurGeneration,
    ResultatGeneration,
    construire_message_utilisateur,
    construire_resultat,
    schema_candidature,
    systeme_candidature,
    valider_entrees,
)

MODELE_PAR_DEFAUT = "claude-sonnet-5-5"
NOM_OUTIL = "repondre"


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


def generer_json(*, systeme: str, message: str, schema: dict) -> tuple[dict, str]:
    """Appel générique : renvoie (objet JSON conforme à `schema`, modèle utilisé).

    L'outil est imposé (tool_choice) : la réponse arrive directement sous
    forme d'objet JSON conforme au schéma, sans texte autour."""
    cle = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not cle:
        raise ErreurGeneration(
            "Aucune clé API Anthropic configurée. Ajoute ANTHROPIC_API_KEY "
            "dans le fichier .env (voir .env.example) puis relance l'app."
        )
    modele = os.environ.get("ANTHROPIC_MODEL", MODELE_PAR_DEFAUT).strip() or MODELE_PAR_DEFAUT
    outil = {
        "name": NOM_OUTIL,
        "description": "Renvoie le résultat demandé, structuré selon le schéma.",
        "input_schema": schema,
    }
    try:
        from anthropic import Anthropic

        client = Anthropic(api_key=cle, max_retries=2)
        reponse = client.messages.create(
            model=modele,
            max_tokens=8000,
            system=systeme,
            tools=[outil],
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
    if bloc_outil is None or not isinstance(bloc_outil.input, dict):
        raise ErreurGeneration("Réponse inattendue de l'IA (aucun résultat structuré reçu).")
    return bloc_outil.input, getattr(reponse, "model", modele)


def generer_candidature(
    *,
    blocs_cv: list[BlocTexte],
    texte_annonce: str,
    contexte_academique: str,
    entreprise_indiquee: str = "",
    poste_indique: str = "",
    consignes_supplementaires: str = "",
    langue: str = "fr",
) -> ResultatGeneration:
    valider_entrees(texte_annonce, blocs_cv)
    message = construire_message_utilisateur(
        blocs_cv=blocs_cv,
        texte_annonce=texte_annonce,
        contexte_academique=contexte_academique,
        entreprise_indiquee=entreprise_indiquee,
        poste_indique=poste_indique,
        consignes_supplementaires=consignes_supplementaires,
        langue=langue,
    )
    donnees, modele = generer_json(systeme=systeme_candidature(langue), message=message,
                                   schema=schema_candidature(langue))
    return construire_resultat(donnees, entreprise_indiquee, poste_indique, modele=modele, langue=langue)
