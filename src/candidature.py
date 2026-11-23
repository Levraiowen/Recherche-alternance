"""
Assemble une candidature complète à partir du contenu généré par l'IA :
lettre Word + CV adapté, puis export PDF garanti sur une page chacun.

Séparé de l'interface (app.py) pour pouvoir être testé et réutilisé tel
quel, par exemple pour régénérer les fichiers après une retouche manuelle
du texte sans rappeler l'IA.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import mise_en_page
import stockage
from cv_editor import RapportAdaptations, appliquer_adaptations
from lettre_generator import generer_lettre
from pdf_export import ErreurConversionPDF, convertir_en_pdf


@dataclass
class ResultatCandidature:
    chemin_lettre_docx: Path
    chemin_cv_docx: Path
    adaptations: RapportAdaptations
    lettre: mise_en_page.ResultatMiseEnPage | None = None
    cv: mise_en_page.ResultatMiseEnPage | None = None
    erreurs_pdf: list[str] = field(default_factory=list)

    @property
    def chemin_lettre_pdf(self) -> Path | None:
        return self.lettre.chemin_pdf if self.lettre else None

    @property
    def chemin_cv_pdf(self) -> Path | None:
        return self.cv.chemin_pdf if self.cv else None

    @property
    def methode_pdf(self) -> str:
        methodes = {r.methode for r in (self.lettre, self.cv) if r and r.methode}
        return " + ".join(sorted(methodes))


def noms_fichiers(nom_personne: str, entreprise: str) -> tuple[str, str]:
    """Noms des fichiers (sans extension), ex :
    Lettre_Motivation_Owen_Charpentier_(Entreprise) et CV_Owen_Charpentier_(Entreprise)."""
    personne = stockage.slugifier_nom_fichier(nom_personne, longueur_max=40).replace(" ", "_") or "Candidat"
    entreprise_slug = stockage.slugifier_nom_fichier(entreprise) or "Entreprise"
    return f"Lettre_Motivation_{personne}_({entreprise_slug})", f"CV_{personne}_({entreprise_slug})"


def produire_candidature(
    *,
    resultat: Any,  # ia_commun.ResultatGeneration
    profil: dict[str, Any],
    entreprise_adresse: str,
    dossier: Path,
    cv_reference: Path | None = None,
    convertir: Callable[[Path], tuple[Path, str]] = convertir_en_pdf,
) -> ResultatCandidature:
    """Crée les deux fichiers Word dans `dossier`, puis leurs PDF sur une
    page. Une erreur de conversion PDF n'empêche jamais d'obtenir les .docx
    (elle est simplement rapportée dans `erreurs_pdf`)."""
    cv_reference = cv_reference or stockage.FICHIER_CV
    nom_lettre, nom_cv = noms_fichiers(profil.get("nom", ""), resultat.entreprise)
    chemin_lettre = dossier / f"{nom_lettre}.docx"
    chemin_cv = dossier / f"{nom_cv}.docx"

    generer_lettre(resultat=resultat, profil=profil, entreprise_adresse=entreprise_adresse,
                   chemin_sortie=chemin_lettre)
    rapport = appliquer_adaptations(cv_reference, chemin_cv, resultat.cv_adaptations)
    sortie = ResultatCandidature(chemin_lettre, chemin_cv, rapport)

    try:
        sortie.lettre = mise_en_page.ajuster_sur_une_page(
            chemin_lettre, convertir, profil=mise_en_page.PROFIL_LETTRE
        )
    except ErreurConversionPDF as exc:
        sortie.erreurs_pdf.append(str(exc))
        return sortie  # inutile d'essayer le CV : même convertisseur, même échec

    # Réglage mémorisé propre à CE CV de référence ET à ce convertisseur
    # (Word et LibreOffice ne mettent pas tout à fait en page pareil).
    empreinte = ""
    if cv_reference == stockage.FICHIER_CV:
        empreinte = f"{stockage.empreinte_cv()}:{sortie.lettre.methode}"
    niveau_depart = stockage.niveau_cv_memorise(empreinte) if empreinte else 0
    try:
        sortie.cv = mise_en_page.ajuster_sur_une_page(
            chemin_cv, convertir, profil=mise_en_page.PROFIL_CV, niveau_depart=niveau_depart
        )
    except ErreurConversionPDF as exc:
        sortie.erreurs_pdf.append(str(exc))
        return sortie

    if empreinte and sortie.cv.mesure is not None:
        niveau = sortie.cv.niveau
        trop_resserre = mise_en_page.niveau_inferieur_suffirait(niveau, sortie.cv.mesure, mise_en_page.PROFIL_CV)
        if sortie.cv.une_page and trop_resserre:
            niveau -= 1  # la prochaine fois, on tente un cran plus aéré
        stockage.memoriser_niveau_cv(empreinte, niveau)
    return sortie


def verifier_cv_reference(
    dossier_temporaire: Path,
    convertir: Callable[[Path], tuple[Path, str]] = convertir_en_pdf,
) -> mise_en_page.ResultatMiseEnPage:
    """Teste la mise en page du CV de référence tel quel (sans adaptation) :
    sert au bouton « Vérifier que mon CV tient sur 1 page » et initialise le
    niveau mémorisé pour les candidatures suivantes."""
    dossier_temporaire.mkdir(parents=True, exist_ok=True)
    copie = dossier_temporaire / "CV_reference_test.docx"
    copie.write_bytes(stockage.FICHIER_CV.read_bytes())
    resultat = mise_en_page.ajuster_sur_une_page(copie, convertir, profil=mise_en_page.PROFIL_CV)
    if resultat.mesure is not None:
        stockage.memoriser_niveau_cv(f"{stockage.empreinte_cv()}:{resultat.methode}", resultat.niveau)
    return resultat
