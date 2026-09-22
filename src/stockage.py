"""
Lecture/écriture des données persistées de l'app (profil, historique).

Tout est stocké en local dans le dossier data/ (fichiers JSON + le CV .docx
d'origine). Le contenu du CV et de l'annonce n'est envoyé qu'au fournisseur
IA actif au moment de générer une candidature (Gemini par défaut, ou
Anthropic si FOURNISSEUR_IA=anthropic dans .env — voir ai_client.py), et au
service iLovePDF UNIQUEMENT si ni Word ni LibreOffice ne sont disponibles et
qu'une clé iLovePDF est configurée (voir pdf_export.py et le README).
"""

import json
from datetime import datetime
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_DATA = RACINE / "data"
DOSSIER_OUTPUTS = RACINE / "outputs"

FICHIER_PROFIL = DOSSIER_DATA / "profil.json"
FICHIER_HISTORIQUE = DOSSIER_DATA / "historique.json"
FICHIER_CV = DOSSIER_DATA / "cv_original.docx"

# Windows plafonne un chemin complet à 260 caractères par défaut : sans cette
# limite, un nom d'entreprise ou de poste très long combiné au reste du
# chemin (dossier + horodatage + nom de fichier) pourrait le dépasser et
# faire échouer l'enregistrement silencieusement.
LONGUEUR_MAX_SLUG = 60

PROFIL_PAR_DEFAUT: dict[str, Any] = {
    "nom": "Owen Charpentier",
    "adresse": "",
    "code_postal": "",
    "ville": "",
    "telephone": "",
    "email": "",
    "linkedin": "",
    "github": "",
    "contexte_academique": (
        "Étudiant en Licence 3 Professionnelle Data Mining à l'Université "
        "Gustave Eiffel (CFA Descartes), à la recherche d'une alternance de "
        "12 mois comme Data Analyst."
    ),
}


def _assurer_dossiers() -> None:
    DOSSIER_DATA.mkdir(parents=True, exist_ok=True)
    DOSSIER_OUTPUTS.mkdir(parents=True, exist_ok=True)


def _ecrire_json_atomique(chemin: Path, donnees: Any) -> None:
    """Écrit un fichier JSON de façon atomique (fichier temporaire puis
    remplacement d'un seul coup), pour ne jamais laisser un fichier à moitié
    écrit sur le disque si l'app est interrompue en pleine écriture (ex:
    plantage, coupure de courant) — un fichier à moitié écrit est un JSON
    invalide, ce qui ferait planter l'app entière au prochain démarrage."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(chemin)  # remplacement atomique (Windows, Linux, Mac)


def _lire_json_ou_repli(chemin: Path, valeur_repli: Any) -> Any:
    """Lit un fichier JSON ; s'il est corrompu (JSON invalide — ex: écriture
    interrompue par le passé, ou édition manuelle ratée), le met de côté
    (renommé, jamais perdu ni écrasé) et repart de `valeur_repli` plutôt que
    de faire planter toute l'app à cause d'un seul fichier abîmé."""
    if not chemin.exists():
        return valeur_repli
    try:
        return json.loads(chemin.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        sauvegarde = chemin.with_name(
            f"{chemin.stem}.corrompu-{datetime.now().strftime('%Y%m%d_%H%M%S')}{chemin.suffix}"
        )
        try:
            chemin.replace(sauvegarde)
        except OSError:
            pass  # tant pis pour la sauvegarde : on continue quand même avec le repli
        return valeur_repli


def charger_profil() -> dict[str, Any]:
    _assurer_dossiers()
    profil = _lire_json_ou_repli(FICHIER_PROFIL, dict(PROFIL_PAR_DEFAUT))
    # Complète les clés manquantes si le format par défaut a évolué depuis
    for cle, valeur in PROFIL_PAR_DEFAUT.items():
        profil.setdefault(cle, valeur)
    return profil


def enregistrer_profil(profil: dict[str, Any]) -> None:
    _assurer_dossiers()
    _ecrire_json_atomique(FICHIER_PROFIL, profil)


def cv_present() -> bool:
    return FICHIER_CV.exists()


def enregistrer_cv(donnees: bytes, nom_original: str) -> None:
    """Enregistre le CV importé comme référence permanente (data/cv_original.docx)."""
    _assurer_dossiers()
    FICHIER_CV.write_bytes(donnees)
    meta = charger_profil()
    meta["_cv_nom_original"] = nom_original
    meta["_cv_importe_le"] = datetime.now().isoformat(timespec="seconds")
    enregistrer_profil(meta)


def charger_historique() -> list[dict[str, Any]]:
    _assurer_dossiers()
    return _lire_json_ou_repli(FICHIER_HISTORIQUE, [])


def ajouter_historique(entree: dict[str, Any]) -> None:
    _assurer_dossiers()
    historique = charger_historique()
    historique.insert(0, entree)  # plus récent en premier
    _ecrire_json_atomique(FICHIER_HISTORIQUE, historique)


def supprimer_historique(index: int) -> None:
    """Retire une entrée de l'historique par sa position (0 = la plus
    récente). Ne touche PAS aux fichiers PDF/Word sur le disque, seulement à
    la liste : une candidature déjà envoyée reste retrouvable dans outputs/
    même après avoir été retirée de cette liste."""
    _assurer_dossiers()
    historique = charger_historique()
    if 0 <= index < len(historique):
        historique.pop(index)
        _ecrire_json_atomique(FICHIER_HISTORIQUE, historique)


def dossier_candidature(entreprise: str, *, sous_dossier: str = "") -> Path:
    """Dossier de sortie pour une candidature.

    `sous_dossier`, s'il est fourni, isole chaque génération dans son propre
    sous-dossier (ex: un horodatage). Sans ça, deux candidatures pour la même
    entreprise — deux postes différents, ou simplement deux essais successifs
    en ajustant les remarques pour l'IA — écraseraient silencieusement les
    mêmes fichiers sur le disque, ce qui corromprait aussi l'historique :
    une ancienne entrée pointerait alors vers le contenu de la nouvelle
    génération, sans aucun avertissement.
    """
    _assurer_dossiers()
    slug = slugifier_nom_fichier(entreprise) or "Candidature"
    dossier = DOSSIER_OUTPUTS / slug
    if sous_dossier:
        dossier = dossier / sous_dossier
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def slugifier_nom_fichier(texte: str) -> str:
    """Nettoie un texte (nom d'entreprise, de poste...) pour un usage sûr
    dans un nom de fichier/dossier Windows, et le tronque à une longueur
    raisonnable (voir LONGUEUR_MAX_SLUG)."""
    interdits = '<>:"/\\|?*'
    nettoye = "".join(c for c in texte if c not in interdits)
    nettoye = " ".join(nettoye.split())  # espaces multiples -> un seul
    nettoye = nettoye.strip(" .")
    return nettoye[:LONGUEUR_MAX_SLUG].strip(" .")
