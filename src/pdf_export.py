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
   pour la conversion. Palier gratuit : 250 conversions/mois, aucune carte
   bancaire requise (voir README pour créer une clé).

Si aucune des trois n'est disponible/configurée, une erreur claire est
levée : l'appelant (app.py) garde alors le .docx comme solution de repli,
il n'y a jamais de candidature bloquée faute de convertisseur PDF.
"""

import os
import shutil
import signal
import subprocess
import tempfile
from pathlib import Path


class ErreurConversionPDF(Exception):
    """Erreur lisible à afficher telle quelle dans l'interface."""


def _word_disponible() -> bool:
    """Vérifie si Word est utilisable via COM, SANS le lancer (contrairement à
    une tentative de conversion qui échouerait après avoir fait apparaître/
    clignoter une fenêtre Word à l'écran à chaque génération). Sur Windows,
    on regarde juste si la classe COM "Word.Application" est enregistrée
    dans le registre : si Word n'est pas installé, ou si seule la version
    Microsoft Store d'Office l'est (elle ne s'enregistre pas de la même
    façon que la version bureau classique et ne supporte pas l'automatisation
    COM), cette classe est absente et Word ne serait de toute façon jamais
    utilisable ici — inutile de tenter de le lancer."""
    if os.name != "nt":
        return True  # pas de vérification fiable équivalente sur Mac/Linux : on tente normalement

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
            "Microsoft Store) qui ne supporte pas l'automatisation. L'app "
            "passe directement aux méthodes suivantes sans essayer de lancer Word."
        )

    from docx2pdf import convert  # dépendance optionnelle (Windows/Mac + Word installé)

    convert(str(chemin_docx), str(chemin_pdf))


def _trouver_soffice() -> str | None:
    """Cherche l'exécutable LibreOffice.

    D'abord dans le PATH, puis dans les emplacements d'installation standards :
    sur Windows, l'installeur LibreOffice n'ajoute PAS soffice.exe au PATH par
    défaut (contrairement à beaucoup d'autres logiciels), donc shutil.which()
    échoue même quand LibreOffice est bien installé et fonctionne normalement
    depuis le menu Démarrer.
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
# conversion normale prend quelques secondes (un peu plus la toute première
# fois, le temps que LibreOffice initialise le profil temporaire) ; un délai
# court plutôt que plusieurs minutes permet de détecter rapidement un
# LibreOffice bloqué — ex: boîte de dialogue native qui attend un clic à
# cause d'une installation ou d'un profil corrompu (message « bootstrap.ini
# est défectueux » par exemple) — et de passer à la méthode suivante
# (iLovePDF) sans laisser l'utilisateur planté devant un spinner qui ne
# bouge plus.
DELAI_LIBREOFFICE_SECONDES = 30
DELAI_NETTOYAGE_SECONDES = 10  # marge laissée pour tuer/nettoyer après un blocage


def _tuer_processus_bloque(processus: "subprocess.Popen") -> None:
    """Tue un processus qui n'a pas répondu dans les temps, sans jamais
    bloquer indéfiniment — même si un enfant du processus a survécu et garde
    les tubes stdout/stderr ouverts (ex: soffice.exe qui aurait fait
    apparaître une boîte de dialogue bloquante dans un processus séparé : un
    simple kill() du processus principal ne la fermerait pas, et attendre sa
    fermeture bloquerait alors indéfiniment)."""
    processus.kill()
    if os.name == "nt":
        # /T tue aussi les processus enfants démarrés par celui-ci.
        # Best-effort : on ignore un éventuel échec de cette commande.
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
    """Vérification rapide et best-effort de l'installation LibreOffice avant
    de lancer une conversion. Sans ça, une installation cassée (fichier
    bootstrap.ini tronqué/vide, ex: écriture interrompue par un antivirus ou
    par une désinstallation/réinstallation qui n'a pas pu remplacer un
    fichier verrouillé par un ancien processus soffice.exe resté ouvert)
    ne se révèle qu'après avoir attendu DELAI_LIBREOFFICE_SECONDES pour rien.
    Renvoie un message d'erreur si un souci évident est détecté, sinon None
    (auquel cas la conversion est simplement tentée normalement)."""
    bootstrap = Path(soffice).parent / "bootstrap.ini"
    try:
        taille = bootstrap.stat().st_size
    except OSError:
        return None  # impossible de vérifier : pas grave, on tente quand même
    if taille < 100:
        return (
            f"Le fichier de configuration LibreOffice ({bootstrap}) fait "
            f"seulement {taille} octet(s) : il est tronqué ou vide, ce qui "
            "correspond exactement à l'erreur « bootstrap.ini est "
            "défectueux ». Une simple réinstallation ne suffit pas toujours "
            "si un ancien processus LibreOffice restait ouvert et verrouillait "
            "ce fichier pendant l'installation (il n'est alors pas remplacé). "
            "Pour corriger : dans le Gestionnaire des tâches, termine tout "
            "processus soffice.exe/soffice.bin, désinstalle LibreOffice, "
            r"vérifie que C:\Program Files\LibreOffice n'existe plus "
            "(supprime le dossier à la main sinon il reste des fichiers "
            "cassés), redémarre le PC, puis réinstalle."
        )
    return None


def _libreoffice_desactive() -> bool:
    return os.environ.get("DESACTIVER_LIBREOFFICE", "").strip().lower() in (
        "1", "true", "oui", "yes",
    )


def _via_libreoffice(chemin_docx: Path, chemin_pdf: Path) -> None:
    if _libreoffice_desactive():
        raise ErreurConversionPDF(
            "LibreOffice désactivé (DESACTIVER_LIBREOFFICE=1 dans .env) : "
            "passage direct à la méthode suivante."
        )

    soffice = _trouver_soffice()
    if not soffice:
        raise ErreurConversionPDF(
            "LibreOffice (soffice) introuvable, ni dans le PATH ni dans son "
            r"emplacement d'installation standard (C:\Program Files\LibreOffice\). "
            "Vérifie que l'installation est bien terminée, ou réinstalle-le."
        )

    diagnostic = _diagnostiquer_installation(soffice)
    if diagnostic:
        raise ErreurConversionPDF(diagnostic)

    # Profil utilisateur isolé et temporaire : évite les blocages si
    # LibreOffice est déjà ouvert par ailleurs, ou si une conversion
    # précédente a laissé un verrou. Nettoyage manuel (plutôt que
    # TemporaryDirectory) car un fichier peut rester verrouillé juste après un
    # kill() suite à un timeout : ignore_errors=True évite qu'un souci de
    # nettoyage n'écrase le message d'erreur qui nous intéresse vraiment.
    profil_tmp = tempfile.mkdtemp(prefix="soffice_profile_")
    try:
        processus = subprocess.Popen(
            [
                soffice,
                f"-env:UserInstallation=file://{Path(profil_tmp).as_posix()}",
                "--headless",
                "--norestore",
                "--convert-to",
                "pdf",
                "--outdir",
                str(chemin_pdf.parent),
                str(chemin_docx),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            # POSIX seulement (ignoré sans erreur sur Windows) : permet de
            # tuer tout le groupe de processus dans _tuer_processus_bloque
            # plutôt que juste le processus principal.
            start_new_session=True,
        )
        try:
            sortie, erreur = processus.communicate(timeout=DELAI_LIBREOFFICE_SECONDES)
        except subprocess.TimeoutExpired:
            _tuer_processus_bloque(processus)
            raise ErreurConversionPDF(
                "LibreOffice ne répond pas (bloqué plus de "
                f"{DELAI_LIBREOFFICE_SECONDES}s sans terminer). C'est en "
                "général le signe d'une installation ou d'un profil "
                "LibreOffice corrompu (ex: message « bootstrap.ini est "
                "défectueux », ou une boîte de dialogue qui attend un clic). "
                "L'app passe automatiquement à la méthode suivante. Pour "
                "corriger LibreOffice : désinstalle-le (Windows > "
                "Applications) puis réinstalle une version fraîche depuis "
                "https://fr.libreoffice.org/telecharger/."
            ) from None
    finally:
        shutil.rmtree(profil_tmp, ignore_errors=True)

    genere = chemin_docx.with_suffix(".pdf")
    if processus.returncode != 0 or not genere.exists():
        detail = (erreur or sortie or "").strip()
        if not detail:
            # LibreOffice n'a parfois rien écrit sur stdout/stderr (ex: plantage
            # silencieux) : sans ce repli, le message serait vide et donc
            # inexploitable pour diagnostiquer quoi que ce soit.
            detail = (
                f"(aucun message renvoyé par LibreOffice ; code de retour "
                f"{processus.returncode}, fichier attendu {genere} "
                f"{'trouvé' if genere.exists() else 'introuvable'})"
            )
        raise ErreurConversionPDF(f"Échec de la conversion LibreOffice : {detail}")

    if genere != chemin_pdf:
        genere.replace(chemin_pdf)


def _via_ilovepdf(chemin_docx: Path, chemin_pdf: Path) -> None:
    cle_publique = os.environ.get("ILOVEPDF_PUBLIC_KEY", "").strip()
    cle_privee = os.environ.get("ILOVEPDF_SECRET_KEY", "").strip()
    if not cle_publique or not cle_privee:
        raise ErreurConversionPDF(
            "Clé iLovePDF non configurée (ILOVEPDF_PUBLIC_KEY / "
            "ILOVEPDF_SECRET_KEY dans .env)."
        )

    from ilovepdf import OfficePdfTask
    from ilovepdf.exceptions import AuthException, ProcessException

    chemin_pdf.parent.mkdir(parents=True, exist_ok=True)

    try:
        tache = OfficePdfTask(public_key=cle_publique, secret_key=cle_privee)
        tache.add_file(str(chemin_docx))
        tache.execute()
        tache.set_output_filename(chemin_pdf.name)
        tache.download(str(chemin_pdf.parent))
    except AuthException as exc:
        raise ErreurConversionPDF(
            f"Clé iLovePDF invalide ou refusée (vérifie ILOVEPDF_PUBLIC_KEY / "
            f"ILOVEPDF_SECRET_KEY dans .env) : {exc}"
        ) from exc
    except ProcessException as exc:
        if "Too Many Requests" in str(exc):
            raise ErreurConversionPDF(
                "Quota gratuit iLovePDF atteint (250 conversions/mois sur le "
                "palier gratuit). Réessaie le mois prochain, ou installe "
                "LibreOffice pour une conversion locale illimitée."
            ) from exc
        raise ErreurConversionPDF(f"Erreur iLovePDF lors du traitement : {exc}") from exc


_METHODES = (_via_word, _via_libreoffice, _via_ilovepdf)


def convertir_en_pdf(chemin_docx: Path) -> Path:
    """Convertit un .docx en .pdf de même nom (seule l'extension change).

    Lève ErreurConversionPDF si aucune méthode de conversion n'est
    disponible sur la machine ; le .docx d'origine n'est jamais touché.
    """
    chemin_pdf = chemin_docx.with_suffix(".pdf")

    # Fichier de sortie temporaire et unique pour ne jamais réutiliser un
    # ancien PDF resté sur le disque si la conversion échoue en cours de route.
    erreurs: list[str] = []
    for methode in _METHODES:
        try:
            methode(chemin_docx, chemin_pdf)
        except Exception as exc:  # noqa: BLE001 - on tente la méthode suivante
            erreurs.append(f"{methode.__name__} : {exc}")
            continue
        if chemin_pdf.exists() and chemin_pdf.stat().st_size > 0:
            return chemin_pdf

    raise ErreurConversionPDF(
        "Conversion PDF impossible : ni Microsoft Word, ni LibreOffice, ni une "
        "clé iLovePDF valide n'ont été détectés. Trois options : installer "
        "LibreOffice (gratuit, 100% local : https://fr.libreoffice.org/telecharger/), "
        "ou configurer ILOVEPDF_PUBLIC_KEY/ILOVEPDF_SECRET_KEY dans .env (clé "
        "gratuite sur developer.ilovepdf.com, mais le fichier part alors sur "
        "leurs serveurs). Le fichier Word (.docx) reste disponible au "
        "téléchargement en attendant.\n" + "\n".join(erreurs)
    )
