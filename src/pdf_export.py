"""
Conversion d'un .docx généré en .pdf, pour livrer directement des fichiers
prêts à envoyer.

Trois méthodes sont tentées dans l'ordre (la première qui fonctionne sur la
machine de l'utilisateur est utilisée) :

1. Microsoft Word (via docx2pdf / COM), si Word est installé — la plus
   fidèle et 100% locale.
2. LibreOffice (soffice, en ligne de commande), si installé — 100% locale
   aussi, sans avoir besoin de Word.
3. iLovePDF (API en ligne), si une clé gratuite est configurée dans .env —
   pour qui n'a ni Word ni LibreOffice. ATTENTION : dans ce cas, le contenu
   du .docx (donc ton CV et ta lettre) est envoyé aux serveurs d'iLovePDF
   pour la conversion. Palier gratuit : 2 500 crédits/mois, soit environ
   250 conversions (10 crédits par fichier Word -> PDF).

La méthode qui a fonctionné est mémorisée pendant que l'app tourne et
retentée en premier aux conversions suivantes : on ne repaie pas à chaque
fois le délai d'échec des méthodes indisponibles.

Si aucune des trois n'est disponible/configurée, une erreur claire est
levée : l'appelant garde alors le .docx comme solution de repli, il n'y a
jamais de candidature bloquée faute de convertisseur PDF.
"""

from __future__ import annotations

import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path
from typing import Callable


class ErreurConversionPDF(Exception):
    """Erreur lisible à afficher telle quelle dans l'interface."""


METHODE_WORD = "Microsoft Word"
METHODE_LIBREOFFICE = "LibreOffice"
METHODE_ILOVEPDF = "iLovePDF (en ligne)"


def _word_disponible() -> bool:
    """Vérifie si Word est utilisable via COM, SANS le lancer (contrairement à
    une tentative de conversion qui échouerait après avoir fait apparaître/
    clignoter une fenêtre Word à l'écran à chaque génération). Sur Windows,
    on regarde juste si la classe COM "Word.Application" est enregistrée
    dans le registre : si Word n'est pas installé, ou si seule la version
    Microsoft Store d'Office l'est (elle ne supporte pas l'automatisation
    COM), cette classe est absente et Word ne serait de toute façon jamais
    utilisable ici — inutile de tenter de le lancer."""
    if os.name != "nt":
        # Pas de vérification fiable équivalente ailleurs : sur Mac, docx2pdf
        # pilote Word s'il est installé ; sur Linux, Word n'existe pas.
        return os.uname().sysname == "Darwin" and Path("/Applications/Microsoft Word.app").exists()

    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, r"Word.Application\CLSID"):
            return True
    except OSError:
        return False


def _via_word(chemin_docx: Path, chemin_pdf: Path) -> None:
    if not _word_disponible():
        raise ErreurConversionPDF(
            "Microsoft Word non détecté (classe COM \"Word.Application\" non "
            "enregistrée) : soit non installé, soit une version (ex: "
            "Microsoft Store) qui ne supporte pas l'automatisation."
        )

    from docx2pdf import convert  # dépendance optionnelle (Windows/Mac + Word installé)

    convert(str(chemin_docx), str(chemin_pdf))


def _trouver_soffice() -> str | None:
    """Cherche l'exécutable LibreOffice.

    D'abord dans le PATH, puis dans les emplacements d'installation standards :
    sur Windows, l'installeur LibreOffice n'ajoute PAS soffice.exe au PATH par
    défaut, donc shutil.which() échoue même quand LibreOffice est bien
    installé et fonctionne normalement depuis le menu Démarrer.
    """
    depuis_path = shutil.which("soffice") or shutil.which("soffice.exe")
    if depuis_path:
        return depuis_path

    emplacements_courants = [
        r"C:\Program Files\LibreOffice\program\soffice.exe",
        r"C:\Program Files (x86)\LibreOffice\program\soffice.exe",
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
        "/opt/libreoffice/program/soffice",
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]
    for chemin in emplacements_courants:
        if Path(chemin).exists():
            return chemin
    return None


# Délai maximal accordé à LibreOffice pour convertir un fichier. Une
# conversion normale prend quelques secondes ; un délai court permet de
# détecter rapidement un LibreOffice bloqué — ex: boîte de dialogue native
# qui attend un clic à cause d'une installation ou d'un profil corrompu
# (message « bootstrap.ini est défectueux ») — et de passer à la méthode
# suivante sans laisser l'utilisateur planté devant un spinner immobile.
DELAI_LIBREOFFICE_SECONDES = 45
DELAI_NETTOYAGE_SECONDES = 10  # marge laissée pour tuer/nettoyer après un blocage


def _tuer_processus_bloque(processus: subprocess.Popen) -> None:
    """Tue un processus qui n'a pas répondu dans les temps, sans jamais
    bloquer indéfiniment — même si un enfant du processus a survécu et garde
    les tubes stdout/stderr ouverts (ex: boîte de dialogue bloquante ouverte
    dans un processus séparé par soffice.exe)."""
    processus.kill()
    if os.name == "nt":
        # /T tue aussi les processus enfants démarrés par celui-ci.
        try:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(processus.pid)],
                capture_output=True,
                timeout=DELAI_NETTOYAGE_SECONDES,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(processus.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            pass
    try:
        processus.communicate(timeout=DELAI_NETTOYAGE_SECONDES)
    except subprocess.TimeoutExpired:
        pass  # tant pis pour la sortie : mieux vaut abandonner que d'attendre indéfiniment


def _diagnostiquer_installation(soffice: str) -> str | None:
    """Vérification rapide de l'installation LibreOffice avant de lancer une
    conversion : un fichier bootstrap.ini tronqué/vide (installation
    corrompue) ne se révélerait sinon qu'après le délai d'attente complet."""
    bootstrap = Path(soffice).parent / "bootstrap.ini"
    try:
        taille = bootstrap.stat().st_size
    except OSError:
        return None  # impossible de vérifier : on tente quand même
    if taille < 100:
        return (
            f"Le fichier de configuration LibreOffice ({bootstrap}) fait "
            f"seulement {taille} octet(s) : installation corrompue (erreur "
            "« bootstrap.ini est défectueux »). Pour corriger : termine tout "
            "processus soffice dans le Gestionnaire des tâches, désinstalle "
            r"LibreOffice, supprime C:\Program Files\LibreOffice s'il reste, "
            "redémarre le PC puis réinstalle."
        )
    return None


def _libreoffice_desactive() -> bool:
    return os.environ.get("DESACTIVER_LIBREOFFICE", "").strip().lower() in ("1", "true", "oui", "yes")


def _via_libreoffice(chemin_docx: Path, chemin_pdf: Path) -> None:
    if _libreoffice_desactive():
        raise ErreurConversionPDF("LibreOffice désactivé (DESACTIVER_LIBREOFFICE=1 dans .env).")

    soffice = _trouver_soffice()
    if not soffice:
        raise ErreurConversionPDF(
            "LibreOffice (soffice) introuvable, ni dans le PATH ni dans son "
            r"emplacement d'installation standard (C:\Program Files\LibreOffice\)."
        )

    diagnostic = _diagnostiquer_installation(soffice)
    if diagnostic:
        raise ErreurConversionPDF(diagnostic)

    # Profil utilisateur isolé et temporaire : évite les blocages si
    # LibreOffice est déjà ouvert par ailleurs, ou si une conversion
    # précédente a laissé un verrou. Nettoyage manuel (plutôt que
    # TemporaryDirectory) car un fichier peut rester verrouillé juste après un
    # kill() : ignore_errors=True évite de masquer la vraie erreur.
    profil_tmp = tempfile.mkdtemp(prefix="soffice_profile_")
    dossier_sortie = tempfile.mkdtemp(prefix="soffice_out_")
    try:
        processus = subprocess.Popen(
            [
                soffice,
                f"-env:UserInstallation={Path(profil_tmp).as_uri()}",
                "--headless",
                "--norestore",
                "--nologo",
                "--convert-to",
                "pdf",
                "--outdir",
                dossier_sortie,
                str(chemin_docx),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            # POSIX seulement (ignoré sur Windows) : permet de tuer tout le
            # groupe de processus dans _tuer_processus_bloque.
            start_new_session=True,
        )
        try:
            sortie, erreur = processus.communicate(timeout=DELAI_LIBREOFFICE_SECONDES)
        except subprocess.TimeoutExpired:
            _tuer_processus_bloque(processus)
            raise ErreurConversionPDF(
                f"LibreOffice ne répond pas (bloqué plus de {DELAI_LIBREOFFICE_SECONDES}s). "
                "C'est en général le signe d'une installation ou d'un profil "
                "LibreOffice corrompu (ex: message « bootstrap.ini est "
                "défectueux », ou une boîte de dialogue qui attend un clic)."
            ) from None

        genere = Path(dossier_sortie) / (chemin_docx.stem + ".pdf")
        if processus.returncode != 0 or not genere.exists():
            detail = (erreur or sortie or "").strip() or (
                f"aucun message renvoyé ; code de retour {processus.returncode}, "
                f"fichier attendu {'trouvé' if genere.exists() else 'introuvable'}"
            )
            raise ErreurConversionPDF(f"Échec de la conversion LibreOffice : {detail}")
        shutil.move(str(genere), str(chemin_pdf))
    finally:
        shutil.rmtree(profil_tmp, ignore_errors=True)
        shutil.rmtree(dossier_sortie, ignore_errors=True)


def _via_ilovepdf(chemin_docx: Path, chemin_pdf: Path) -> None:
    cle_publique = os.environ.get("ILOVEPDF_PUBLIC_KEY", "").strip()
    cle_privee = os.environ.get("ILOVEPDF_SECRET_KEY", "").strip()
    if not cle_publique or not cle_privee:
        raise ErreurConversionPDF(
            "Clé iLovePDF non configurée (ILOVEPDF_PUBLIC_KEY / ILOVEPDF_SECRET_KEY dans .env)."
        )

    try:
        from ilovepdf import OfficePdfTask
        from ilovepdf.exceptions import AuthException, ProcessException
    except ImportError as exc:
        raise ErreurConversionPDF(
            "Le module Python « ilovepdf » n'est pas installé dans l'environnement "
            "de l'app. Relance l'app via Lancer.bat (il installe automatiquement "
            "les dépendances manquantes) ou lance : pip install -r requirements.txt"
        ) from exc

    chemin_pdf.parent.mkdir(parents=True, exist_ok=True)
    dossier_sortie = tempfile.mkdtemp(prefix="ilovepdf_out_")
    try:
        tache = OfficePdfTask(public_key=cle_publique, secret_key=cle_privee)
        tache.add_file(str(chemin_docx))
        tache.execute()
        tache.set_output_filename(chemin_pdf.name)
        tache.download(dossier_sortie)
        telecharge = Path(dossier_sortie) / chemin_pdf.name
        if not telecharge.exists():
            candidats = list(Path(dossier_sortie).glob("*.pdf"))
            if not candidats:
                raise ErreurConversionPDF("iLovePDF n'a renvoyé aucun fichier PDF.")
            telecharge = candidats[0]
        shutil.move(str(telecharge), str(chemin_pdf))
    except AuthException as exc:
        raise ErreurConversionPDF(
            f"Clé iLovePDF invalide ou refusée (vérifie ILOVEPDF_PUBLIC_KEY / "
            f"ILOVEPDF_SECRET_KEY dans .env) : {exc}"
        ) from exc
    except ProcessException as exc:
        texte = str(exc)
        if "Too Many Requests" in texte or "credits" in texte.lower():
            raise ErreurConversionPDF(
                "Crédits gratuits iLovePDF épuisés pour ce mois-ci (2 500 crédits, "
                "environ 250 conversions). Réessaie le mois prochain, ou utilise "
                "LibreOffice (gratuit, local et illimité)."
            ) from exc
        raise ErreurConversionPDF(f"Erreur iLovePDF lors du traitement : {exc}") from exc
    except OSError as exc:  # inclut les erreurs réseau de requests (ConnectionError...)
        raise ErreurConversionPDF(
            f"Impossible de joindre iLovePDF (connexion Internet ?) : {exc}"
        ) from exc
    finally:
        shutil.rmtree(dossier_sortie, ignore_errors=True)


_METHODES: tuple[tuple[str, Callable[[Path, Path], None]], ...] = (
    (METHODE_WORD, _via_word),
    (METHODE_LIBREOFFICE, _via_libreoffice),
    (METHODE_ILOVEPDF, _via_ilovepdf),
)

# Méthode ayant fonctionné en dernier (pendant que l'app tourne) : essayée en
# premier la fois suivante.
_methode_preferee: str | None = None


def convertir_en_pdf(chemin_docx: Path) -> tuple[Path, str]:
    """Convertit un .docx en .pdf de même nom (seule l'extension change).

    Renvoie (chemin du PDF, nom de la méthode utilisée). Lève
    ErreurConversionPDF si aucune méthode n'a fonctionné ; le .docx n'est
    jamais modifié.
    """
    global _methode_preferee
    chemin_pdf = chemin_docx.with_suffix(".pdf")
    chemin_pdf.unlink(missing_ok=True)  # ne jamais livrer un ancien PDF par erreur

    methodes = list(_METHODES)
    if _methode_preferee:
        methodes.sort(key=lambda m: m[0] != _methode_preferee)

    erreurs: list[str] = []
    for nom, methode in methodes:
        try:
            methode(chemin_docx, chemin_pdf)
        except Exception as exc:  # noqa: BLE001 - on tente la méthode suivante
            erreurs.append(f"• {nom} : {exc}")
            continue
        if chemin_pdf.exists() and chemin_pdf.stat().st_size > 0:
            _methode_preferee = nom
            return chemin_pdf, nom
        erreurs.append(f"• {nom} : aucun fichier PDF produit")

    _methode_preferee = None
    raise ErreurConversionPDF(
        "Conversion PDF impossible : ni Microsoft Word, ni LibreOffice, ni une "
        "clé iLovePDF valide n'ont fonctionné. Options : installer LibreOffice "
        "(gratuit, 100% local : https://fr.libreoffice.org/telecharger/), ou "
        "configurer ILOVEPDF_PUBLIC_KEY/ILOVEPDF_SECRET_KEY dans .env (clé "
        "gratuite sur developer.ilovepdf.com, le fichier part alors sur leurs "
        "serveurs). Le fichier Word (.docx) reste disponible au téléchargement.\n\n"
        "Détail par méthode :\n" + "\n".join(erreurs)
    )
