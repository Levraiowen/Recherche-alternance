"""Rendu du gabarit Word de la lettre de motivation (templates/lettre_template.docx)."""

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


def formater_date_fr(date: datetime | None = None) -> str:
    date = date or datetime.now()
    return f"{date.day} {MOIS_FR[date.month - 1]} {date.year}"


def generer_lettre(
    *,
    resultat: Any,  # ai_client.ResultatGeneration
    profil: dict[str, str],
    entreprise_adresse: str,
    chemin_sortie: Path,
) -> None:
    if not GABARIT.exists():
        raise FileNotFoundError(
            "Gabarit introuvable : templates/lettre_template.docx. "
            "Relance scripts/generer_gabarit_lettre.py."
        )

    cp_ville = " ".join(
        part for part in [profil.get("code_postal", ""), profil.get("ville", "")] if part
    )

    contexte = {
        "expediteur_nom": profil.get("nom", ""),
        "expediteur_adresse": profil.get("adresse", ""),
        "expediteur_cp_ville": cp_ville,
        "expediteur_telephone": profil.get("telephone", ""),
        "expediteur_email": profil.get("email", ""),
        "ville_signature": profil.get("ville", "") or "Paris",
        "date_lettre": formater_date_fr(),
        "entreprise": resultat.entreprise or "l'entreprise",
        "entreprise_adresse": entreprise_adresse,
        "objet": resultat.objet,
        "formule_appel": resultat.formule_appel,
        "paragraphes": resultat.paragraphes,
        "formule_politesse": resultat.formule_politesse,
    }

    doc = DocxTemplate(str(GABARIT))
    doc.render(contexte)
    chemin_sortie.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(chemin_sortie))
