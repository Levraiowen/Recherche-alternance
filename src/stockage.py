"""
Lecture/écriture des données persistées de l'app (profil, historique,
réglages de mise en page).

Tout est stocké en local dans le dossier data/ (fichiers JSON + le CV .docx
d'origine). Le contenu du CV et de l'annonce n'est envoyé qu'au fournisseur
IA actif au moment de générer une candidature (Gemini par défaut, ou
Anthropic si FOURNISSEUR_IA=anthropic dans .env — voir ai_client.py), et au
service iLovePDF UNIQUEMENT si ni Word ni LibreOffice ne sont disponibles et
qu'une clé iLovePDF est configurée (voir pdf_export.py et le README).
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parent.parent
DOSSIER_DATA = RACINE / "data"
DOSSIER_OUTPUTS = RACINE / "outputs"

FICHIER_PROFIL = DOSSIER_DATA / "profil.json"
FICHIER_HISTORIQUE = DOSSIER_DATA / "historique.json"
FICHIER_CV = DOSSIER_DATA / "cv_original.docx"
FICHIER_MISE_EN_PAGE = DOSSIER_DATA / "mise_en_page.json"

# Windows plafonne un chemin complet à 260 caractères par défaut. Pire cas :
# ...\outputs\<entreprise 50>\<poste 40>_<horodatage>\Lettre_Motivation_<nom>_(<entreprise 50>).docx
# reste sous cette limite avec un dossier de projet sur le Bureau.
LONGUEUR_MAX_SLUG = 50
LONGUEUR_MAX_SLUG_POSTE = 40

PROFIL_PAR_DEFAUT: dict[str, Any] = {
    "nom": "",
    "adresse": "",
    "code_postal": "",
    "ville": "",
    "telephone": "",
    "email": "",
    "linkedin": "",
    "github": "",
    "contexte_academique": "",
}


def _assurer_dossiers() -> None:
    DOSSIER_DATA.mkdir(parents=True, exist_ok=True)
    DOSSIER_OUTPUTS.mkdir(parents=True, exist_ok=True)


def _ecrire_json_atomique(chemin: Path, donnees: Any) -> None:
    """Écrit un fichier JSON de façon atomique (fichier temporaire puis
    remplacement d'un seul coup), pour ne jamais laisser un fichier à moitié
    écrit sur le disque si l'app est interrompue en pleine écriture."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_text(json.dumps(donnees, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(chemin)  # remplacement atomique (Windows, Linux, Mac)


def _lire_json_ou_repli(chemin: Path, valeur_repli: Any) -> Any:
    """Lit un fichier JSON ; s'il est corrompu (JSON invalide), le met de
    côté (renommé, jamais perdu ni écrasé) et repart de `valeur_repli`
    plutôt que de faire planter toute l'app à cause d'un seul fichier."""
    if not chemin.exists():
        return valeur_repli
    try:
        donnees = json.loads(chemin.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        sauvegarde = chemin.with_name(
            f"{chemin.stem}.corrompu-{datetime.now().strftime('%Y%m%d_%H%M%S')}{chemin.suffix}"
        )
        try:
            chemin.replace(sauvegarde)
        except OSError:
            pass  # tant pis pour la sauvegarde : on continue quand même avec le repli
        return valeur_repli
    if not isinstance(donnees, type(valeur_repli)):
        return valeur_repli  # structure inattendue (ex: liste au lieu d'objet)
    return donnees


# ---------------------------------------------------------------------------
# Profil
# ---------------------------------------------------------------------------


def charger_profil() -> dict[str, Any]:
    _assurer_dossiers()
    profil = _lire_json_ou_repli(FICHIER_PROFIL, dict(PROFIL_PAR_DEFAUT))
    for cle, valeur in PROFIL_PAR_DEFAUT.items():
        profil.setdefault(cle, valeur)
    return profil


def enregistrer_profil(profil: dict[str, Any]) -> None:
    _assurer_dossiers()
    _ecrire_json_atomique(FICHIER_PROFIL, profil)


def profil_incomplet(profil: dict[str, Any]) -> list[str]:
    """Champs indispensables à l'en-tête d'une lettre qui sont encore vides."""
    libelles = {"nom": "nom", "adresse": "adresse", "ville": "ville", "telephone": "téléphone", "email": "email"}
    return [libelle for cle, libelle in libelles.items() if not str(profil.get(cle, "")).strip()]


# ---------------------------------------------------------------------------
# CV de référence
# ---------------------------------------------------------------------------


def cv_present() -> bool:
    return FICHIER_CV.exists()


def empreinte_cv() -> str:
    """Empreinte du CV de référence : change dès que le fichier change."""
    if not FICHIER_CV.exists():
        return ""
    return hashlib.sha256(FICHIER_CV.read_bytes()).hexdigest()[:16]


def enregistrer_cv(donnees: bytes, nom_original: str) -> None:
    """Enregistre le CV importé comme référence permanente (data/cv_original.docx)."""
    _assurer_dossiers()
    tmp = FICHIER_CV.with_name(FICHIER_CV.name + ".tmp")
    tmp.write_bytes(donnees)
    tmp.replace(FICHIER_CV)
    meta = charger_profil()
    meta["_cv_nom_original"] = nom_original
    meta["_cv_importe_le"] = datetime.now().isoformat(timespec="seconds")
    enregistrer_profil(meta)


# ---------------------------------------------------------------------------
# Réglage de mise en page mémorisé pour le CV (évite de reconvertir plusieurs
# fois le CV à chaque candidature : on repart du niveau qui a suffi la
# dernière fois pour CE fichier de référence)
# ---------------------------------------------------------------------------


def niveau_cv_memorise(empreinte: str) -> int:
    reglages = _lire_json_ou_repli(FICHIER_MISE_EN_PAGE, {})
    valeur = reglages.get("cv", {}).get(empreinte, 0)
    return valeur if isinstance(valeur, int) and valeur >= 0 else 0


def memoriser_niveau_cv(empreinte: str, niveau: int) -> None:
    if not empreinte:
        return
    reglages = _lire_json_ou_repli(FICHIER_MISE_EN_PAGE, {})
    # Une seule entrée utile : celle du CV de référence actuel.
    reglages["cv"] = {empreinte: int(niveau)}
    _ecrire_json_atomique(FICHIER_MISE_EN_PAGE, reglages)


# ---------------------------------------------------------------------------
# Historique
# ---------------------------------------------------------------------------


def chemin_relatif(chemin: Path | str | None) -> str | None:
    """Chemin stocké dans l'historique : relatif au dossier du projet quand
    c'est possible, pour que l'historique reste valable si le dossier du
    projet est déplacé ou renommé."""
    if not chemin:
        return None
    chemin = Path(chemin)
    try:
        return chemin.resolve().relative_to(RACINE).as_posix()
    except ValueError:
        return str(chemin)


def resoudre_chemin(chemin: str | None) -> Path | None:
    """Inverse de chemin_relatif (accepte aussi les anciens chemins absolus)."""
    if not chemin:
        return None
    candidat = Path(chemin)
    if candidat.is_absolute():
        if candidat.exists():
            return candidat
        # Ancien chemin absolu d'un dossier de projet déplacé : on retente
        # à partir de "outputs/..." dans le dossier actuel.
        parties = candidat.parts
        if "outputs" in parties:
            return RACINE.joinpath(*parties[parties.index("outputs"):])
        return candidat
    return RACINE / candidat


def identifiant_entree(entree: dict[str, Any]) -> str:
    return str(entree.get("id") or f"{entree.get('date', '')}|{entree.get('entreprise', '')}")


def charger_historique() -> list[dict[str, Any]]:
    _assurer_dossiers()
    historique = _lire_json_ou_repli(FICHIER_HISTORIQUE, [])
    return [e for e in historique if isinstance(e, dict)]


def ajouter_historique(entree: dict[str, Any]) -> None:
    _assurer_dossiers()
    historique = charger_historique()
    historique.insert(0, entree)  # plus récent en premier
    _ecrire_json_atomique(FICHIER_HISTORIQUE, historique)


def mettre_a_jour_historique(identifiant: str, modifications: dict[str, Any]) -> bool:
    historique = charger_historique()
    for entree in historique:
        if identifiant_entree(entree) == identifiant:
            entree.update(modifications)
            _ecrire_json_atomique(FICHIER_HISTORIQUE, historique)
            return True
    return False


def supprimer_historique(identifiant: str) -> None:
    """Retire une entrée de l'historique. Ne touche PAS aux fichiers PDF/Word
    sur le disque : une candidature déjà envoyée reste retrouvable dans
    outputs/ même après avoir été retirée de cette liste."""
    historique = charger_historique()
    restant = [e for e in historique if identifiant_entree(e) != identifiant]
    if len(restant) != len(historique):
        _ecrire_json_atomique(FICHIER_HISTORIQUE, restant)


def normaliser_nom(texte: str) -> str:
    """« L'Oréal France » et « l’oreal  france » -> « l oreal france »."""
    caracteres = []
    for c in unicodedata.normalize("NFKD", texte or ""):
        if unicodedata.combining(c):
            continue  # accent détaché de sa lettre par la décomposition NFKD
        caracteres.append(c.lower() if c.isalnum() else " ")
    return " ".join("".join(caracteres).encode("ascii", "ignore").decode().split())


def candidatures_precedentes(entreprise: str, *, sauf: str | None = None) -> list[dict[str, Any]]:
    """Candidatures déjà générées pour la même entreprise (pour éviter de
    postuler deux fois sans s'en rendre compte)."""
    cible = normaliser_nom(entreprise)
    if not cible:
        return []
    return [
        e for e in charger_historique()
        if normaliser_nom(e.get("entreprise", "")) == cible and identifiant_entree(e) != sauf
    ]


# ---------------------------------------------------------------------------
# Dossiers et noms de fichiers
# ---------------------------------------------------------------------------


def dossier_candidature(entreprise: str, *, sous_dossier: str = "") -> Path:
    """Dossier de sortie pour une candidature.

    `sous_dossier` (ex: poste + horodatage) isole chaque génération : sans
    ça, deux candidatures pour la même entreprise écraseraient
    silencieusement les mêmes fichiers, et une ancienne entrée de
    l'historique pointerait vers le contenu de la nouvelle génération.
    """
    _assurer_dossiers()
    slug = slugifier_nom_fichier(entreprise) or "Candidature"
    dossier = DOSSIER_OUTPUTS / slug
    if sous_dossier:
        dossier = dossier / sous_dossier
    dossier.mkdir(parents=True, exist_ok=True)
    return dossier


def slugifier_nom_fichier(texte: str, longueur_max: int = LONGUEUR_MAX_SLUG) -> str:
    """Nettoie un texte (nom d'entreprise, de poste...) pour un usage sûr
    dans un nom de fichier/dossier Windows, et le tronque à une longueur
    raisonnable (voir LONGUEUR_MAX_SLUG)."""
    interdits = '<>:"/\\|?*'
    nettoye = "".join(c for c in (texte or "") if c not in interdits and c.isprintable())
    nettoye = " ".join(nettoye.split())  # espaces multiples -> un seul
    nettoye = nettoye.strip(" .")
    return nettoye[:longueur_max].strip(" .")
