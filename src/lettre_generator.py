"""Rendu du gabarit Word de la lettre de motivation (templates/lettre_template.docx)."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import Any

from docxtpl import DocxTemplate

RACINE = Path(__file__).resolve().parent.parent
GABARIT = RACINE / "templates" / "lettre_template.docx"

MOIS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]

INSECABLE = " "


def formater_date_fr(date: datetime | None = None) -> str:
    """« 23 novembre 2026 », et « 1er décembre 2026 » le premier du mois."""
    date = date or datetime.now()
    jour = "1er" if date.day == 1 else str(date.day)
    return f"{jour} {MOIS_FR[date.month - 1]} {date.year}"


def formater_telephone(numero: str) -> str:
    """Présente un numéro français par paires : 0785082867 -> 07 85 08 28 67.
    Tout autre format est laissé tel quel."""
    chiffres = re.sub(r"[\s.\-()]", "", numero or "")
    if re.fullmatch(r"0\d{9}", chiffres):
        return " ".join(chiffres[i:i + 2] for i in range(0, 10, 2))
    if re.fullmatch(r"\+33\d{9}", chiffres):
        reste = chiffres[3:]
        return "+33 " + reste[0] + " " + " ".join(reste[i:i + 2] for i in range(1, 9, 2))
    return (numero or "").strip()


def decouper_adresse(adresse: str) -> list[str]:
    """Une adresse saisie sur une ligne (« 5 place X, 92800 Puteaux ») est
    présentée sur deux lignes, comme sur une enveloppe : la coupure se fait
    juste avant le code postal. Les retours à la ligne saisis sont gardés."""
    adresse = (adresse or "").strip()
    if not adresse:
        return []
    if "\n" in adresse:
        return [ligne.strip() for ligne in adresse.splitlines() if ligne.strip()]
    morceaux = re.split(r",\s*(?=\d{5}\b)", adresse, maxsplit=1)
    return [m.strip(" ,") for m in morceaux if m.strip(" ,")]


def typographie_fr(texte: str) -> str:
    """Petites corrections typographiques sur le texte généré par l'IA :
    apostrophes courbes, espace insécable avant « : ; ! ? » et à l'intérieur
    des guillemets français, suppression d'éventuels restes de markdown."""
    texte = (texte or "").strip()
    texte = re.sub(r"\*\*|__", "", texte)  # gras markdown
    texte = re.sub(r"^\s*[-•*]\s+", "", texte)  # puce en début de paragraphe
    texte = texte.replace("'", "’")
    texte = re.sub(r"[ \t  ]+([:;!?»])", INSECABLE + r"\1", texte)
    # Ponctuation double collée au mot (« suivantes: », « pourquoi? ») :
    # on ajoute l'espace insécable attendu en français. Les heures (10:30)
    # et les adresses web (https://) ne sont pas concernées.
    texte = re.sub(r"(?<=[^\W\d_)])([:;!?])(?=\s|$)", INSECABLE + r"\1", texte)
    texte = re.sub(r"«[ \t  ]*", "«" + INSECABLE, texte)
    texte = re.sub(r"[ \t]{2,}", " ", texte)
    return texte


def nettoyer_objet(objet: str) -> str:
    """Le gabarit écrit déjà « Objet : » : on retire un éventuel doublon
    renvoyé par l'IA (« Objet : Candidature... »)."""
    return re.sub(r"^\s*objet\s*:\s*", "", objet or "", flags=re.IGNORECASE).strip()


def construire_contexte(*, resultat: Any, profil: dict[str, str], entreprise_adresse: str,
                        date: datetime | None = None) -> dict[str, Any]:
    cp_ville = " ".join(p for p in [profil.get("code_postal", ""), profil.get("ville", "")] if p)
    expediteur_lignes = [
        profil.get("adresse", "").strip(),
        cp_ville.strip(),
        formater_telephone(profil.get("telephone", "")),
        profil.get("email", "").strip(),
    ]
    return {
        "expediteur_nom": profil.get("nom", "").strip(),
        "expediteur_lignes": [ligne for ligne in expediteur_lignes if ligne],
        "ville_signature": profil.get("ville", "").strip() or "Paris",
        "date_lettre": formater_date_fr(date),
        "entreprise": typographie_fr(resultat.entreprise) or "Service recrutement",
        "entreprise_lignes": decouper_adresse(entreprise_adresse),
        "objet": typographie_fr(nettoyer_objet(resultat.objet)),
        "formule_appel": typographie_fr(resultat.formule_appel) or "Madame, Monsieur,",
        "paragraphes": [typographie_fr(p) for p in resultat.paragraphes if p.strip()],
        "formule_politesse": typographie_fr(resultat.formule_politesse),
    }


def generer_lettre(
    *,
    resultat: Any,  # ia_commun.ResultatGeneration
    profil: dict[str, str],
    entreprise_adresse: str,
    chemin_sortie: Path,
) -> Path:
    if not GABARIT.exists():
        raise FileNotFoundError(
            "Gabarit introuvable : templates/lettre_template.docx. "
            "Relance scripts/generer_gabarit_lettre.py."
        )

    contexte = construire_contexte(resultat=resultat, profil=profil, entreprise_adresse=entreprise_adresse)
    doc = DocxTemplate(str(GABARIT))
    # autoescape=True est indispensable : sans lui, un « & » dans le texte
    # (« Data & IA », « R&D », « Corporate & Investment Banking ») disparaît
    # silencieusement, et un « < » peut même faire disparaître toute la fin
    # de la lettre.
    doc.render(contexte, autoescape=True)
    chemin_sortie.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(chemin_sortie))
    return chemin_sortie
