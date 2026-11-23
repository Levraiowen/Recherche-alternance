"""
Appels à l'API Gemini (Google), palier gratuit : génération de la candidature
et des textes de l'assistant (relance, préparation d'entretien...).

Clé gratuite à obtenir sur https://aistudio.google.com/apikey (aucune carte
bancaire requise, indépendant d'un éventuel abonnement Gemini Advanced payant).

Les modèles gratuits de Gemini renvoient parfois une erreur 503 « high
demand » quand ils sont très sollicités : c'est temporaire (quelques
secondes à quelques minutes), donc l'appel est automatiquement retenté une
fois avant d'abandonner (une seule retentative, pas plus : le palier
gratuit a peu de requêtes par jour, chaque tentative en consomme une réelle,
qu'elle réussisse ou échoue avec un 503).

Ce n'est PAS ce mécanisme qui gère un quota dépassé (erreur
"RESOURCE_EXHAUSTED") ni un modèle qui n'existe plus (erreur "NOT_FOUND" —
Google retire des modèles de temps en temps, ex: gemini-2.5-flash n'est
plus accessible aux nouveaux appelants depuis peu). Dans ces deux cas,
retenter le MÊME modèle donnerait le même échec, donc l'app bascule plutôt
sur un modèle différent (voir MODELES_SECOURS), et abandonne seulement si
TOUS les modèles de la liste ont échoué.

Le choix des modèles par défaut vient de données réelles (tableau de bord
aistudio.google.com/rate-limit d'un utilisateur) : les variantes "Flash Lite"
(gemini-3.5-flash-lite, gemini-3.1-flash-lite) ont un palier gratuit bien
plus généreux que les modèles "Flash" normaux, et un modèle "Lite" est
largement suffisant pour rédiger une lettre de motivation structurée.
Google fait évoluer sa gamme régulièrement (ex: en octobre 2026,
gemini-3.7-flash a été remplacé par gemini-3.8-flash et gemini-3.5-flash
par gemini-3.6-flash, voir ai.google.dev/gemini-api/docs/changelog) : d'où
le mécanisme de bascule automatique en secours, et la variable GEMINI_MODEL
pour forcer un autre modèle sans toucher au code.
"""

from __future__ import annotations

import os
import time

from cv_editor import BlocTexte
from ia_commun import (
    SCHEMA_CANDIDATURE,
    SYSTEME,
    ErreurGeneration,
    ResultatGeneration,
    construire_message_utilisateur,
    construire_resultat,
    extraire_json,
    valider_entrees,
)

MODELE_PAR_DEFAUT = "gemini-3.5-flash-lite"

# Modèles essayés, dans l'ordre, si le modèle demandé (ou par défaut) répond
# "quota atteint" ou "modèle indisponible" : un autre "Flash Lite" (gros
# quota gratuit), puis deux "Flash" normaux (petit quota, mais séparé de
# celui du modèle principal, donc encore une chance). Liste à jour de
# novembre 2026 (modèles stables listés sur ai.google.dev/gemini-api/docs/models).
MODELES_SECOURS = ["gemini-3.1-flash-lite", "gemini-3.8-flash", "gemini-3.6-flash"]

REESSAIS_MAX = 2  # 1 seule retentative (pas 2) : le palier gratuit a peu de
# requêtes par jour, chaque retentative en consomme une réelle en plus.
DELAI_INITIAL_SECONDES = 3  # 3s entre les deux tentatives


def _appeler_avec_reessai(client, *, modele: str, contenu: str, config: dict):
    from google.genai import errors as genai_errors

    derniere_erreur: Exception | None = None
    for tentative in range(1, REESSAIS_MAX + 1):
        try:
            return client.models.generate_content(model=modele, contents=contenu, config=config)
        except genai_errors.ServerError as exc:
            # 5xx : erreur momentanée côté Google (ex: 503 « high demand »), on retente.
            derniere_erreur = exc
            if tentative < REESSAIS_MAX:
                time.sleep(DELAI_INITIAL_SECONDES * tentative)
                continue
    raise derniere_erreur


def _resoudre_modeles_a_essayer(modele_demande: str) -> list[str]:
    """Le modèle demandé (ou par défaut) en premier, puis les modèles de
    secours restants (sans le répéter s'il y figure déjà)."""
    modeles = [modele_demande]
    for secours in MODELES_SECOURS:
        if secours not in modeles:
            modeles.append(secours)
    return modeles


# Statuts d'erreur (en plus des surcharges serveur 5xx, toujours concernées)
# pour lesquels changer de modèle a une chance de résoudre
# le problème : quota atteint sur CE modèle précis, ou modèle qui n'existe
# plus / n'est plus accessible (Google en retire de temps en temps). Une
# mauvaise clé API ou une autre erreur ne seraient pas résolues en changeant
# de modèle, donc ces deux statuts uniquement déclenchent la bascule.
STATUTS_CHANGEMENT_MODELE = ("RESOURCE_EXHAUSTED", "NOT_FOUND")


def _generer_avec_secours(client, *, modeles: list[str], contenu: str, config: dict):
    """Essaie chaque modèle de la liste dans l'ordre, en passant au suivant
    quand le statut de l'erreur est dans STATUTS_CHANGEMENT_MODELE. Toute
    autre erreur remonte immédiatement (pas la peine d'essayer les modèles
    suivants pour rien si, par exemple, la clé API est invalide)."""
    from google.genai import errors as genai_errors

    derniere_erreur: Exception | None = None
    for index, modele in enumerate(modeles):
        dernier_modele = index == len(modeles) - 1
        try:
            return _appeler_avec_reessai(client, modele=modele, contenu=contenu, config=config), modele
        except genai_errors.ServerError as exc:
            # Surcharge (503) ou panne (5xx) persistante sur CE modèle, même
            # après la retentative : les autres modèles tournent souvent sur
            # d'autres serveurs, on tente donc le suivant.
            derniere_erreur = exc
            if not dernier_modele:
                continue
            raise
        except genai_errors.ClientError as exc:
            derniere_erreur = exc
            statut = getattr(exc, "status", "") or ""
            if statut in STATUTS_CHANGEMENT_MODELE and not dernier_modele:
                continue  # ce modèle est à quota ou indisponible : on tente le suivant
            raise
    raise derniere_erreur  # ne devrait pas arriver (modeles a toujours au moins un élément)


def _message_erreur(exc: Exception, modeles_essayes: list[str] | None = None) -> str:
    from google.genai import errors as genai_errors

    modeles_essayes = modeles_essayes or []

    if isinstance(exc, genai_errors.ServerError):
        code = getattr(exc, "code", "?")
        statut = getattr(exc, "status", "") or ""
        return (
            f"Les serveurs Gemini sont momentanément surchargés (erreur {code} "
            f"{statut}). L'app a essayé {len(modeles_essayes) or 1} modèle(s) "
            f"({', '.join(modeles_essayes)}) sans succès — c'est un problème "
            "temporaire côté Google, pas un souci avec ta clé ou ton quota : "
            "réessaie dans une minute ou deux."
        )
    if isinstance(exc, genai_errors.ClientError):
        statut = getattr(exc, "status", "") or ""
        if statut in ("RESOURCE_EXHAUSTED", "NOT_FOUND"):
            detail = (getattr(exc, "message", "") or "").strip()
            essai = (
                f" L'app a essayé {len(modeles_essayes)} modèles au total "
                f"({', '.join(modeles_essayes)}) : aucun n'a répondu (quota atteint "
                "et/ou modèle indisponible)."
                if len(modeles_essayes) > 1
                else ""
            )
            return (
                "Quota gratuit Gemini atteint, ou modèle indisponible."
                + essai + " Si c'est le quota par minute, attends 1 minute et "
                "réessaie. Si ça persiste, c'est peut-être le quota journalier "
                "(il se réinitialise le lendemain, détails sur "
                "ai.google.dev/gemini-api/docs/rate-limits) ou un modèle que "
                "Google a retiré : vérifie aistudio.google.com/rate-limit."
                + (f"\n\nDétail renvoyé par Google (dernier modèle essayé) : {detail}" if detail else "")
            )
        if statut in ("UNAUTHENTICATED", "PERMISSION_DENIED"):
            return (
                "Clé API Gemini invalide ou refusée. Vérifie GEMINI_API_KEY "
                "dans .env (recrée une clé sur aistudio.google.com/apikey si besoin)."
            )
        return f"Erreur de l'API Gemini ({getattr(exc, 'code', '?')} {statut}) : {getattr(exc, 'message', exc)}"
    return f"Erreur inattendue lors de l'appel à Gemini : {exc}"


def generer_json(*, systeme: str, message: str, schema: dict) -> tuple[dict, str]:
    """Appel générique : renvoie (objet JSON conforme à `schema`, modèle utilisé).
    Gère la clé, la bascule entre modèles et les messages d'erreur clairs."""
    cle = os.environ.get("GEMINI_API_KEY", "").strip()
    if not cle:
        raise ErreurGeneration(
            "Aucune clé API Gemini configurée. Crée une clé gratuite sur "
            "https://aistudio.google.com/apikey, ajoute GEMINI_API_KEY dans "
            "le fichier .env (voir .env.example) puis relance l'app."
        )

    modele_demande = os.environ.get("GEMINI_MODEL", MODELE_PAR_DEFAUT).strip() or MODELE_PAR_DEFAUT
    modeles_a_essayer = _resoudre_modeles_a_essayer(modele_demande)

    try:
        from google import genai
    except ImportError as exc:
        raise ErreurGeneration(
            "Le module Python « google-genai » n'est pas installé : relance l'app via "
            "Lancer.bat ou lance pip install -r requirements.txt."
        ) from exc

    try:
        client = genai.Client(api_key=cle)
        reponse, modele_utilise = _generer_avec_secours(
            client,
            modeles=modeles_a_essayer,
            contenu=message,
            config={
                "system_instruction": systeme,
                "response_mime_type": "application/json",
                "response_json_schema": schema,
            },
        )
    except ErreurGeneration:
        raise
    except Exception as exc:  # noqa: BLE001 - converti en message clair ci-dessous
        raise ErreurGeneration(_message_erreur(exc, modeles_a_essayer)) from exc

    texte_reponse = (getattr(reponse, "text", None) or "").strip()
    if not texte_reponse:
        raison = ""
        try:
            raison = str(reponse.candidates[0].finish_reason or "")
        except (AttributeError, IndexError, TypeError):
            pass
        raise ErreurGeneration(
            "Réponse vide reçue de l'API Gemini"
            + (f" (motif : {raison})" if raison else "")
            + ". Réessaie ; si ça se reproduit, raccourcis le texte envoyé."
        )

    try:
        return extraire_json(texte_reponse), modele_utilise
    except ValueError as exc:
        raise ErreurGeneration(f"Réponse Gemini non JSON valide : {exc}") from exc


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
    message = construire_message_utilisateur(
        blocs_cv=blocs_cv,
        texte_annonce=texte_annonce,
        contexte_academique=contexte_academique,
        entreprise_indiquee=entreprise_indiquee,
        poste_indique=poste_indique,
        consignes_supplementaires=consignes_supplementaires,
    )
    donnees, modele_utilise = generer_json(systeme=SYSTEME, message=message, schema=SCHEMA_CANDIDATURE)
    return construire_resultat(donnees, entreprise_indiquee, poste_indique, modele=modele_utilise)
