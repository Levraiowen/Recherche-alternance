"""
Génération de la candidature via l'API Anthropic (Claude). Payant à l'usage
(non couvert par un abonnement claude.ai) : conservé pour qui préfère cette
option, mais ce n'est pas le mode par défaut de l'app (voir FOURNISSEUR_IA
dans .env). Pour le mode gratuit, voir ia_gemini.py.
"""

import os

from anthropic import Anthropic, APIError

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

MODELE_PAR_DEFAUT = "claude-sonnet-5"
NOM_OUTIL = "generer_candidature"

SCHEMA_OUTIL = {
    "name": NOM_OUTIL,
    "description": (
        "Produit le contenu d'une candidature (lettre de motivation + "
        "adaptations du CV) pour une offre d'emploi donnée."
    ),
    "input_schema": SCHEMA_CANDIDATURE,
}


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
    client = Anthropic(api_key=cle)

    try:
        reponse = client.messages.create(
            model=modele,
            max_tokens=4000,
            system=SYSTEME,
            tools=[SCHEMA_OUTIL],
            tool_choice={"type": "tool", "name": NOM_OUTIL},
            messages=[{"role": "user", "content": message}],
        )
    except APIError as exc:
        raise ErreurGeneration(f"Erreur de l'API Anthropic : {exc}") from exc

    bloc_outil = next(
        (b for b in reponse.content if getattr(b, "type", None) == "tool_use"), None
    )
    if bloc_outil is None:
        raise ErreurGeneration("Réponse inattendue de l'IA (aucun résultat structuré reçu).")

    return construire_resultat(bloc_outil.input, entreprise_indiquee, poste_indique)
