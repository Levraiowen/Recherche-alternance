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
import io
import json
import time
import unicodedata
import zipfile
from dataclasses import dataclass
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
DOSSIER_CVS = DOSSIER_DATA / "cvs"
DOSSIER_SAUVEGARDES = RACINE / "sauvegardes"

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


class ErreurStockage(OSError):
    """Fichier de données momentanément inaccessible : message lisible."""


# Sous Windows, un antivirus ou OneDrive peut verrouiller un fichier une
# fraction de seconde : on réessaie avant d'abandonner (sans jamais rien
# effacer ni réécrire à cause d'une simple erreur de lecture).
DELAIS_REESSAI = (0.1, 0.2, 0.4, 0.8)


def _avec_reessais(action, chemin: Path):
    for delai in (*DELAIS_REESSAI, None):
        try:
            return action()
        except FileNotFoundError:
            raise
        except OSError as exc:
            if delai is None:
                raise ErreurStockage(
                    f"Impossible d'accéder à {chemin.name} (fichier utilisé par un autre programme : antivirus, "
                    f"OneDrive... ?). Réessaie dans un instant. Détail : {exc}"
                ) from exc
            time.sleep(delai)
    return None  # jamais atteint


def _assurer_dossiers() -> None:
    DOSSIER_DATA.mkdir(parents=True, exist_ok=True)
    DOSSIER_OUTPUTS.mkdir(parents=True, exist_ok=True)


def _ecrire_json_atomique(chemin: Path, donnees: Any) -> None:
    """Écrit un fichier JSON de façon atomique (fichier temporaire puis
    remplacement d'un seul coup), pour ne jamais laisser un fichier à moitié
    écrit sur le disque si l'app est interrompue en pleine écriture."""
    chemin.parent.mkdir(parents=True, exist_ok=True)
    tmp = chemin.with_name(chemin.name + ".tmp")
    texte = json.dumps(donnees, ensure_ascii=False, indent=2)
    _avec_reessais(lambda: tmp.write_text(texte, encoding="utf-8"), chemin)
    _avec_reessais(lambda: tmp.replace(chemin), chemin)  # remplacement atomique (Windows, Linux, Mac)


def _lire_json_ou_repli(chemin: Path, valeur_repli: Any) -> Any:
    """Lit un fichier JSON ; s'il est corrompu (JSON invalide), le met de
    côté (renommé, jamais perdu ni écrasé) et repart de `valeur_repli`
    plutôt que de faire planter toute l'app à cause d'un seul fichier.
    Un fichier simplement inaccessible (verrouillé) n'est PAS considéré comme
    corrompu : ErreurStockage est levée et rien n'est modifié."""
    try:
        brut = _avec_reessais(chemin.read_bytes, chemin)
    except FileNotFoundError:
        return valeur_repli
    try:
        donnees = json.loads(brut.decode("utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError):
        sauvegarde = chemin.with_name(
            f"{chemin.stem}.corrompu-{datetime.now().strftime('%Y%m%d_%H%M%S')}{chemin.suffix}"
        )
        try:
            chemin.replace(sauvegarde)
        except OSError as exc:
            # Fichier illisible qu'on n'a pas pu mettre de côté : surtout ne
            # pas repartir de zéro, la prochaine écriture l'écraserait.
            raise ErreurStockage(
                f"{chemin.name} est illisible et n'a pas pu être mis de côté ({exc}). Ferme les programmes qui "
                "pourraient l'utiliser, puis relance l'app."
            ) from exc
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
# CV de référence (un CV principal + d'éventuels CV supplémentaires, ex: un
# CV « Data » et un CV « Marketing », choisis au moment de générer)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CVReference:
    nom: str  # nom affiché
    chemin: Path
    principal: bool


def cv_present() -> bool:
    return FICHIER_CV.exists()


def empreinte_fichier(chemin: Path) -> str:
    """Empreinte d'un fichier : change dès que son contenu change."""
    try:
        return hashlib.sha256(chemin.read_bytes()).hexdigest()[:16]
    except OSError:
        return ""


def empreinte_cv() -> str:
    """Empreinte du CV principal."""
    return empreinte_fichier(FICHIER_CV) if FICHIER_CV.exists() else ""


def enregistrer_cv(donnees: bytes, nom_original: str) -> None:
    """Enregistre le CV importé comme référence principale (data/cv_original.docx)."""
    _assurer_dossiers()
    tmp = FICHIER_CV.with_name(FICHIER_CV.name + ".tmp")
    tmp.write_bytes(donnees)
    tmp.replace(FICHIER_CV)
    meta = charger_profil()
    meta["_cv_nom_original"] = nom_original
    meta["_cv_importe_le"] = datetime.now().isoformat(timespec="seconds")
    enregistrer_profil(meta)


def nom_cv_valide(nom: str) -> str:
    """Nom de fichier sûr pour un CV supplémentaire (sans extension)."""
    return slugifier_nom_fichier(Path(nom or "").stem if (nom or "").lower().endswith(".docx") else nom, 40)


def lister_cvs() -> list[CVReference]:
    """CV principal en premier, puis les CV supplémentaires par ordre alphabétique."""
    cvs: list[CVReference] = []
    if FICHIER_CV.exists():
        nom = Path(charger_profil().get("_cv_nom_original") or "CV principal").stem
        cvs.append(CVReference(nom=f"{nom} (principal)", chemin=FICHIER_CV, principal=True))
    if DOSSIER_CVS.exists():
        for chemin in sorted(DOSSIER_CVS.glob("*.docx"), key=lambda c: c.stem.lower()):
            cvs.append(CVReference(nom=chemin.stem, chemin=chemin, principal=False))
    return cvs


def ajouter_cv(donnees: bytes, nom: str) -> Path:
    """Ajoute (ou remplace) un CV supplémentaire, ex: « CV Marketing »."""
    nom_sur = nom_cv_valide(nom)
    if not nom_sur:
        raise ValueError("Nom de CV invalide.")
    DOSSIER_CVS.mkdir(parents=True, exist_ok=True)
    chemin = DOSSIER_CVS / f"{nom_sur}.docx"
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_bytes(donnees)
    tmp.replace(chemin)
    return chemin


def supprimer_cv(nom: str) -> None:
    """Supprime un CV supplémentaire (jamais le CV principal)."""
    chemin = DOSSIER_CVS / f"{nom_cv_valide(nom)}.docx"
    if chemin.parent == DOSSIER_CVS and chemin.exists():
        chemin.unlink()


# ---------------------------------------------------------------------------
# Réglage de mise en page mémorisé par CV (évite de reconvertir plusieurs
# fois le CV à chaque candidature : on repart du niveau qui a suffi la
# dernière fois pour CE fichier de référence et CE convertisseur)
# ---------------------------------------------------------------------------

ENTREES_MISE_EN_PAGE_MAX = 12


def niveau_cv_memorise(cle: str) -> int:
    try:
        reglages = _lire_json_ou_repli(FICHIER_MISE_EN_PAGE, {})
    except OSError:
        return 0  # simple optimisation : on repart du niveau 0
    memoire = reglages.get("cv", {})
    if not isinstance(memoire, dict):
        return 0
    valeur = memoire.get(cle)
    if valeur is None and ":" not in cle:
        # Convertisseur pas encore connu : on reprend le réglage le plus
        # récent connu pour ce CV, quel que soit le convertisseur.
        valeur = next((v for k, v in reversed(memoire.items()) if k.split(":")[0] == cle), None)
    return valeur if isinstance(valeur, int) and valeur >= 0 else 0


def memoriser_niveau_cv(cle: str, niveau: int) -> None:
    if not cle:
        return
    try:
        _memoriser_niveau_cv(cle, niveau)
    except OSError:
        pass  # simple optimisation : ne jamais faire échouer une candidature pour ça


def _memoriser_niveau_cv(cle: str, niveau: int) -> None:
    reglages = _lire_json_ou_repli(FICHIER_MISE_EN_PAGE, {})
    memoire = reglages.get("cv", {})
    if not isinstance(memoire, dict):
        memoire = {}
    memoire.pop(cle, None)
    memoire[cle] = int(niveau)  # réinséré en dernier = le plus récent
    while len(memoire) > ENTREES_MISE_EN_PAGE_MAX:
        memoire.pop(next(iter(memoire)))
    reglages["cv"] = memoire
    _ecrire_json_atomique(FICHIER_MISE_EN_PAGE, reglages)


# ---------------------------------------------------------------------------
# Sauvegardes des données personnelles (profil, historique, CV)
# ---------------------------------------------------------------------------

SAUVEGARDES_A_GARDER = 15
TAILLE_MAX_FICHIER_RESTAURE = 25 * 1024 * 1024  # 25 Mo par fichier
NOMS_RESTAURABLES = {"profil.json", "historique.json", "cv_original.docx", "mise_en_page.json"}


def _fichiers_donnees() -> list[Path]:
    if not DOSSIER_DATA.exists():
        return []
    return sorted(
        f for f in DOSSIER_DATA.rglob("*")
        if f.is_file() and not f.name.endswith(".tmp") and ".corrompu-" not in f.name
    )


def exporter_donnees() -> bytes:
    """Archive zip (en mémoire) de toutes les données personnelles de l'app."""
    tampon = io.BytesIO()
    with zipfile.ZipFile(tampon, "w", zipfile.ZIP_DEFLATED) as archive:
        for fichier in _fichiers_donnees():
            archive.write(fichier, fichier.relative_to(DOSSIER_DATA).as_posix())
    return tampon.getvalue()


def creer_sauvegarde() -> Path | None:
    """Écrit une sauvegarde datée dans sauvegardes/ et ne garde que les plus récentes."""
    if not _fichiers_donnees():
        return None
    DOSSIER_SAUVEGARDES.mkdir(parents=True, exist_ok=True)
    chemin = DOSSIER_SAUVEGARDES / f"sauvegarde_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.zip"
    tmp = chemin.with_name(chemin.name + ".tmp")
    tmp.write_bytes(exporter_donnees())
    tmp.replace(chemin)
    for ancienne in sorted(DOSSIER_SAUVEGARDES.glob("sauvegarde_*.zip"))[:-SAUVEGARDES_A_GARDER]:
        try:
            ancienne.unlink()
        except OSError:
            pass
    return chemin


def sauvegarde_automatique() -> Path | None:
    """Une sauvegarde par jour au maximum (appelée au démarrage de l'app)."""
    aujourd_hui = datetime.now().strftime("%Y-%m-%d")
    if DOSSIER_SAUVEGARDES.exists() and any(DOSSIER_SAUVEGARDES.glob(f"sauvegarde_{aujourd_hui}_*.zip")):
        return None
    try:
        return creer_sauvegarde()
    except OSError:
        return None  # une sauvegarde ratée ne doit jamais empêcher d'utiliser l'app


def _nom_restaurable(nom: str) -> bool:
    if nom in NOMS_RESTAURABLES:
        return True
    morceaux = nom.split("/")
    return (
        len(morceaux) == 2 and morceaux[0] == "cvs" and morceaux[1].endswith(".docx")
        and nom_cv_valide(morceaux[1]) + ".docx" == morceaux[1]
    )


ENTREES_MAX_SAUVEGARDE = 200  # une sauvegarde de l'app en contient une dizaine
TAILLE_MAX_SAUVEGARDE = 100 * 1024 * 1024  # 100 Mo décompressés au total


def _docx_lisible(donnees: bytes) -> bool:
    try:
        from docx import Document

        Document(io.BytesIO(donnees))
    except Exception:  # noqa: BLE001 - tout fichier illisible est refusé
        return False
    return True


def restaurer_sauvegarde(contenu: bytes) -> list[str]:
    """Restaure une sauvegarde exportée par l'app. Seuls les fichiers connus
    de l'app sont acceptés (aucun chemin arbitraire : protection contre les
    archives piégées), tout est vérifié AVANT d'écrire quoi que ce soit, et
    l'état actuel est d'abord sauvegardé."""
    global _cache_historique
    try:
        archive = zipfile.ZipFile(io.BytesIO(contenu))
    except (zipfile.BadZipFile, ValueError, OSError) as exc:
        raise ValueError("Ce fichier n'est pas une sauvegarde valide (archive zip illisible).") from exc
    a_restaurer: dict[str, bytes] = {}
    with archive:
        entrees = [info for info in archive.infolist() if not info.is_dir()]
        if len(entrees) > ENTREES_MAX_SAUVEGARDE:
            raise ValueError("Cette archive contient beaucoup trop de fichiers pour être une sauvegarde de l'app.")
        total = 0
        for info in entrees:
            if not _nom_restaurable(info.filename):
                continue  # fichier inconnu ou chemin suspect : ignoré
            total += info.file_size
            if info.file_size > TAILLE_MAX_FICHIER_RESTAURE or total > TAILLE_MAX_SAUVEGARDE:
                raise ValueError(f"Fichier trop volumineux dans la sauvegarde : {info.filename}")
            try:
                donnees = archive.read(info)  # taille bornée par l'en-tête, contrôle d'intégrité (CRC)
            except (zipfile.BadZipFile, zipfile.LargeZipFile, OSError, EOFError, RuntimeError,
                    NotImplementedError, ValueError) as exc:
                raise ValueError(f"Sauvegarde endommagée ({info.filename}) : {exc}") from exc
            except Exception as exc:  # noqa: BLE001 - ex: zlib.error sur des données compressées abîmées
                raise ValueError(f"Sauvegarde endommagée ({info.filename}).") from exc
            if info.filename.endswith(".json"):
                try:
                    json.loads(donnees.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError(f"Fichier corrompu dans la sauvegarde : {info.filename}") from exc
            elif not _docx_lisible(donnees):
                raise ValueError(f"CV invalide dans la sauvegarde : {info.filename}")
            a_restaurer[info.filename] = donnees
    if not a_restaurer:
        raise ValueError("Aucune donnée de l'app trouvée dans cette archive.")
    creer_sauvegarde()
    _cache_historique = None
    for nom, donnees in a_restaurer.items():
        destination = DOSSIER_DATA.joinpath(*nom.split("/"))
        destination.parent.mkdir(parents=True, exist_ok=True)
        tmp = destination.with_name(destination.name + ".tmp")
        _avec_reessais(lambda tmp=tmp, donnees=donnees: tmp.write_bytes(donnees), destination)
        _avec_reessais(lambda tmp=tmp, destination=destination: tmp.replace(destination), destination)
    return sorted(a_restaurer)


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


# L'interface consulte l'historique plusieurs fois par affichage : on ne
# relit le fichier que s'il a changé (identifiant, date de modification à la
# nanoseconde et taille), et chaque appel reçoit ses propres copies des
# entrées (modifier une entrée renvoyée ne touche jamais le cache).
_cache_historique: tuple[Path, tuple[int, int, int], list[dict[str, Any]]] | None = None


def _signature_fichier(chemin: Path) -> tuple[int, int, int] | None:
    try:
        infos = chemin.stat()
    except OSError:
        return None
    return (infos.st_ino, infos.st_mtime_ns, infos.st_size)


def charger_historique() -> list[dict[str, Any]]:
    """Candidatures enregistrées, la plus récente en premier."""
    global _cache_historique
    _assurer_dossiers()
    signature = _signature_fichier(FICHIER_HISTORIQUE)
    cache = _cache_historique
    if signature is not None and cache is not None and cache[0] == FICHIER_HISTORIQUE and cache[1] == signature:
        entrees = cache[2]
    else:
        entrees = [e for e in _lire_json_ou_repli(FICHIER_HISTORIQUE, []) if isinstance(e, dict)]
        _cache_historique = (FICHIER_HISTORIQUE, signature, entrees) if signature is not None else None
    return [dict(e) for e in entrees]


def _enregistrer_historique(historique: list[dict[str, Any]]) -> None:
    global _cache_historique
    _cache_historique = None
    _ecrire_json_atomique(FICHIER_HISTORIQUE, historique)


def ajouter_historique(entree: dict[str, Any]) -> None:
    _assurer_dossiers()
    historique = charger_historique()
    historique.insert(0, entree)  # plus récent en premier
    _enregistrer_historique(historique)


def mettre_a_jour_historique(identifiant: str, modifications: dict[str, Any]) -> bool:
    historique = charger_historique()
    for entree in historique:
        if identifiant_entree(entree) == identifiant:
            entree.update(modifications)
            _enregistrer_historique(historique)
            return True
    return False


def supprimer_historique(identifiant: str) -> None:
    """Retire une entrée de l'historique. Ne touche PAS aux fichiers PDF/Word
    sur le disque : une candidature déjà envoyée reste retrouvable dans
    outputs/ même après avoir été retirée de cette liste."""
    historique = charger_historique()
    restant = [e for e in historique if identifiant_entree(e) != identifiant]
    if len(restant) != len(historique):
        _enregistrer_historique(restant)


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
