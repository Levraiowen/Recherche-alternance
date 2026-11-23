"""
Assemble une candidature complète à partir du contenu généré par l'IA :
lettre Word + CV adapté, puis export PDF garanti sur une page chacun.

Séparé de l'interface (app.py) pour pouvoir être testé et réutilisé tel
quel, par exemple pour régénérer les fichiers après une retouche manuelle
du texte sans rappeler l'IA.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

import mise_en_page
import pdf_export
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
    progression: Callable[[str], None] | None = None,
    en_parallele: bool | None = None,
) -> ResultatCandidature:
    """Crée les deux fichiers Word dans `dossier`, puis leurs PDF sur une
    page (en parallèle quand le convertisseur le permet). Une erreur de
    conversion PDF n'empêche jamais d'obtenir les .docx (elle est simplement
    rapportée dans `erreurs_pdf`). `progression(message)` est appelé à chaque
    étape, depuis le fil d'exécution de l'appelant uniquement."""
    signaler = progression or (lambda _message: None)
    cv_reference = cv_reference or stockage.FICHIER_CV
    nom_lettre, nom_cv = noms_fichiers(profil.get("nom", ""), resultat.entreprise)
    chemin_lettre = dossier / f"{nom_lettre}.docx"
    chemin_cv = dossier / f"{nom_cv}.docx"

    signaler("📄 Création des fichiers Word (lettre et CV adapté)...")
    generer_lettre(resultat=resultat, profil=profil, entreprise_adresse=entreprise_adresse,
                   chemin_sortie=chemin_lettre)
    rapport = appliquer_adaptations(cv_reference, chemin_cv, resultat.cv_adaptations)
    sortie = ResultatCandidature(chemin_lettre, chemin_cv, rapport)

    # Réglage mémorisé propre à CE CV de référence et, si on le connaît
    # déjà, à ce convertisseur (Word et LibreOffice ne mettent pas tout à
    # fait en page pareil).
    empreinte = stockage.empreinte_fichier(cv_reference)
    methode_connue = pdf_export.methode_preferee() if convertir is convertir_en_pdf else None
    niveau_depart = stockage.niveau_cv_memorise(f"{empreinte}:{methode_connue}" if methode_connue else empreinte)

    def faire_lettre() -> mise_en_page.ResultatMiseEnPage:
        return mise_en_page.ajuster_sur_une_page(chemin_lettre, convertir, profil=mise_en_page.PROFIL_LETTRE)

    def faire_cv() -> mise_en_page.ResultatMiseEnPage:
        return mise_en_page.ajuster_sur_une_page(
            chemin_cv, convertir, profil=mise_en_page.PROFIL_CV, niveau_depart=niveau_depart
        )

    if en_parallele is None:
        en_parallele = convertir is not convertir_en_pdf or pdf_export.conversion_parallele_possible()
    signaler("🖨️ Conversion en PDF et mise en page sur une page"
             + (" (lettre et CV en parallèle)..." if en_parallele else "..."))
    if en_parallele:
        with ThreadPoolExecutor(max_workers=2) as pool:
            futurs = {"lettre": pool.submit(faire_lettre), "cv": pool.submit(faire_cv)}
            for nom, futur in futurs.items():
                try:
                    setattr(sortie, nom, futur.result())
                except ErreurConversionPDF as exc:
                    if str(exc) not in sortie.erreurs_pdf:
                        sortie.erreurs_pdf.append(str(exc))
    else:
        try:
            sortie.lettre = faire_lettre()
            sortie.cv = faire_cv()
        except ErreurConversionPDF as exc:
            sortie.erreurs_pdf.append(str(exc))  # même convertisseur : inutile d'insister

    if empreinte and sortie.cv is not None and sortie.cv.mesure is not None:
        niveau = sortie.cv.niveau
        trop_resserre = mise_en_page.niveau_inferieur_suffirait(niveau, sortie.cv.mesure, mise_en_page.PROFIL_CV)
        if sortie.cv.une_page and trop_resserre:
            niveau -= 1  # la prochaine fois, on tente un cran plus aéré
        stockage.memoriser_niveau_cv(f"{empreinte}:{sortie.cv.methode}", niveau)
    return sortie


def verifier_cv_reference(
    dossier_temporaire: Path,
    convertir: Callable[[Path], tuple[Path, str]] = convertir_en_pdf,
    cv_reference: Path | None = None,
) -> mise_en_page.ResultatMiseEnPage:
    """Teste la mise en page d'un CV de référence tel quel (sans adaptation) :
    sert au bouton « Vérifier que mon CV tient sur 1 page » et initialise le
    niveau mémorisé pour les candidatures suivantes."""
    cv_reference = cv_reference or stockage.FICHIER_CV
    dossier_temporaire.mkdir(parents=True, exist_ok=True)
    copie = dossier_temporaire / "CV_reference_test.docx"
    copie.write_bytes(cv_reference.read_bytes())
    resultat = mise_en_page.ajuster_sur_une_page(copie, convertir, profil=mise_en_page.PROFIL_CV)
    if resultat.mesure is not None:
        stockage.memoriser_niveau_cv(f"{stockage.empreinte_fichier(cv_reference)}:{resultat.methode}",
                                     resultat.niveau)
    return resultat
