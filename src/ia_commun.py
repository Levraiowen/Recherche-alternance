"""
Éléments partagés entre les différents fournisseurs d'IA (Gemini, Anthropic) :
le schéma de sortie structurée, le prompt système, la construction du
message utilisateur et le parsing de la réponse JSON.

Chaque fournisseur (ia_gemini.py, ia_anthropic.py) ne fait que brancher son
SDK sur ces éléments communs, pour que le résultat (ResultatGeneration) soit
identique quel que soit le fournisseur utilisé.
"""

import json
from dataclasses import dataclass, field

from cv_editor import BlocTexte

SCHEMA_CANDIDATURE = {
    "type": "object",
    "properties": {
        "entreprise": {
            "type": "string",
            "description": "Nom de l'entreprise identifié dans l'annonce (chaîne vide si non identifiable).",
        },
        "poste": {
            "type": "string",
            "description": "Intitulé du poste identifié dans l'annonce.",
        },
        "lettre": {
            "type": "object",
            "properties": {
                "objet": {
                    "type": "string",
                    "description": "Ligne d'objet, ex: 'Candidature au poste de Data Analyst en alternance'.",
                },
                "formule_appel": {
                    "type": "string",
                    "description": "Ex: 'Madame, Monsieur,' (rester générique si aucun nom de recruteur n'est fourni).",
                },
                "paragraphes": {
                    "type": "array",
                    "items": {"type": "string"},
                    "minItems": 3,
                    "maxItems": 4,
                    "description": (
                        "3 à 4 paragraphes courts (2 à 5 phrases chacun) formant le corps de "
                        "la lettre, dans cet ordre : (1) accroche spécifique à l'entreprise et "
                        "à l'offre - pas une formule passe-partout, (2) formation et "
                        "compétences réelles du candidat en lien avec ce que l'annonce "
                        "recherche, (3) une expérience, un projet ou une réalisation concrète "
                        "et nommée du CV qui illustre ces compétences en action, (4) motivation "
                        "propre à cette entreprise (en écho à un élément repéré dans l'annonce) "
                        "et ouverture/disponibilité pour un entretien. Chaque paragraphe doit "
                        "s'appuyer sur des éléments nommés et réels du CV et de l'annonce, "
                        "jamais sur des généralités interchangeables."
                    ),
                },
                "formule_politesse": {
                    "type": "string",
                    "description": "Formule de politesse finale.",
                },
            },
            "required": ["objet", "formule_appel", "paragraphes", "formule_politesse"],
        },
        "cv_adaptations": {
            "type": "array",
            "description": (
                "Uniquement les blocs du CV dont le texte doit changer pour "
                "coller à l'offre. Ne pas inclure les blocs inchangés."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "nouveau_texte": {"type": "string"},
                },
                "required": ["id", "nouveau_texte"],
            },
        },
    },
    "required": ["entreprise", "poste", "lettre", "cv_adaptations"],
}

SYSTEME = """Tu aides un candidat français à personnaliser sa candidature (lettre de \
motivation + CV) pour une offre d'emploi précise, en alternance.

Règles impératives :
1. Ne jamais inventer une expérience, un diplôme, une compétence, une date ou \
un chiffre qui n'apparaît pas dans le CV fourni. Tu peux reformuler, \
réorganiser l'emphase, ou légèrement raccourcir/étoffer une formulation \
existante pour coller à l'offre, mais le fond doit rester strictement fidèle \
à la réalité du CV fourni.
2. Pour chaque bloc de CV que tu modifies, vise une longueur proche de la \
longueur d'origine (indiquée en nombre de caractères) pour ne pas casser la \
mise en page du document Word. N'inclus dans cv_adaptations que les blocs \
réellement modifiés.
3. Avant de rédiger, repère dans le CV fourni 2 à 4 éléments concrets et \
nommés (intitulé exact d'une expérience, d'un stage, d'un projet \
académique, d'une formation, d'un outil ou logiciel maîtrisé, d'un résultat \
chiffré si présent), et repère dans l'annonce 2 à 4 éléments concrets et \
nommés (mission précise, technologie ou outil demandé, secteur d'activité, \
activité ou particularité de l'entreprise, valeur mise en avant). La lettre \
doit construire des ponts explicites entre ces deux listes plutôt que de \
rester générale : chaque affirmation doit pouvoir se rattacher à un élément \
réel du CV ou de l'annonce, jamais à une généralité qui conviendrait à \
n'importe quel candidat ou n'importe quelle entreprise.
4. Structure les paragraphes autour de ces éléments concrets, dans cet \
esprit : (1) accroche qui montre que la lettre est écrite pour CETTE \
entreprise et CETTE offre précisément ; (2) lien entre la formation/les \
compétences réelles du candidat et ce que l'annonce recherche ; (3) une \
expérience, un projet ou une réalisation concrète et nommée du CV qui \
illustre ces compétences en action ; (4) motivation spécifique pour cette \
entreprise, en écho à un élément repéré dans l'annonce, et \
ouverture/disponibilité pour un entretien. Le candidat est à la recherche \
d'un contrat en alternance : mentionne-le naturellement si le contexte \
fourni l'indique.
5. Respecte scrupuleusement les codes d'une lettre de motivation française \
classique, même en la personnalisant fortement : registre soutenu et \
vouvoiement du début à la fin, ton sincère et mesuré (éviter les \
superlatifs et formules clichées du type « passionné(e) depuis mon plus \
jeune âge » ou « dynamique et motivé(e) »), aucune liste à puces ni mise en \
forme markdown dans le texte de la lettre, paragraphes courts (2 à 5 \
phrases). La personnalisation ne doit jamais se faire au détriment de ce \
format attendu par un recruteur.
6. Si le nom de l'entreprise ou l'intitulé du poste sont fournis \
explicitement dans le contexte, utilise-les tels quels plutôt que de les \
redéduire de l'annonce.
7. Réponds UNIQUEMENT avec un objet JSON valide respectant exactement le \
schéma demandé. Pas de texte avant ou après, pas de bloc markdown ```.
"""


@dataclass
class ResultatGeneration:
    entreprise: str
    poste: str
    objet: str
    formule_appel: str
    paragraphes: list[str]
    formule_politesse: str
    cv_adaptations: dict[str, str] = field(default_factory=dict)


class ErreurGeneration(Exception):
    """Erreur lisible à afficher telle quelle dans l'interface."""


def valider_entrees(texte_annonce: str, blocs_cv: list[BlocTexte]) -> None:
    if not texte_annonce.strip():
        raise ErreurGeneration("Colle le texte de l'annonce avant de générer la candidature.")
    if not blocs_cv:
        raise ErreurGeneration("Aucun texte détecté dans le CV importé (voir l'onglet Mon CV).")


def construire_message_utilisateur(
    *,
    blocs_cv: list[BlocTexte],
    texte_annonce: str,
    contexte_academique: str,
    entreprise_indiquee: str = "",
    poste_indique: str = "",
    consignes_supplementaires: str = "",
) -> str:
    blocs_json = json.dumps(
        [{"id": b.id, "texte": b.texte, "longueur": b.longueur} for b in blocs_cv],
        ensure_ascii=False,
    )

    parties_contexte = [
        f"Contexte du candidat : {contexte_academique}" if contexte_academique.strip() else "",
        f"Nom d'entreprise fourni par le candidat : {entreprise_indiquee}" if entreprise_indiquee.strip() else "",
        f"Intitulé de poste fourni par le candidat : {poste_indique}" if poste_indique.strip() else "",
        f"Consignes supplémentaires du candidat pour cette génération : {consignes_supplementaires}"
        if consignes_supplementaires.strip()
        else "",
    ]
    contexte = "\n".join(p for p in parties_contexte if p)

    return f"""{contexte}

Annonce collée par le candidat :
---
{texte_annonce.strip()}
---

Blocs de texte détectés dans le CV du candidat (format JSON, un identifiant \
et une longueur en caractères par bloc) :
---
{blocs_json}
---

Repère d'abord les éléments concrets et nommés du CV ci-dessus et de \
l'annonce ci-dessus (voir consignes système), puis génère la candidature au \
format JSON demandé en t'appuyant explicitement dessus."""


def construire_resultat(
    donnees: dict, entreprise_indiquee: str = "", poste_indique: str = ""
) -> ResultatGeneration:
    try:
        lettre = donnees["lettre"]
        paragraphes = list(lettre["paragraphes"])
        resultat = ResultatGeneration(
            entreprise=(donnees.get("entreprise") or entreprise_indiquee or "").strip(),
            poste=(donnees.get("poste") or poste_indique or "").strip(),
            objet=lettre["objet"],
            formule_appel=lettre["formule_appel"],
            paragraphes=paragraphes,
            formule_politesse=lettre["formule_politesse"],
            cv_adaptations={
                item["id"]: item["nouveau_texte"] for item in donnees.get("cv_adaptations", [])
            },
        )
    except (KeyError, TypeError) as exc:
        raise ErreurGeneration(f"Réponse de l'IA incomplète ou mal formée : {exc}") from exc

    # Filet de sécurité : le schéma demande 3-4 paragraphes non vides, mais
    # rien ne garantit à 100% qu'un fournisseur le respecte toujours à la
    # lettre. Mieux vaut un message d'erreur clair ici qu'une lettre sans
    # corps envoyée par erreur.
    if not any(p.strip() for p in resultat.paragraphes):
        raise ErreurGeneration(
            "Réponse de l'IA incomplète : la lettre générée n'a aucun "
            "paragraphe. Réessaie la génération."
        )
    return resultat
