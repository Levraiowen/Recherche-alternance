@echo off
setlocal
cd /d "%~dp0"

title Candidatures alternance
echo ============================================
echo   Generateur de candidatures - alternance
echo ============================================
echo.

if exist ".venv\Scripts\activate.bat" (
    call ".venv\Scripts\activate.bat"
) else (
    echo (Pas d'environnement virtuel .venv trouve : utilisation de Python global.)
)

echo.
echo Demarrage de l'application... le navigateur va s'ouvrir automatiquement.
echo.
echo IMPORTANT : laisse cette fenetre ouverte tant que tu utilises l'app.
echo Pour l'arreter : ferme cette fenetre, ou appuie sur Ctrl+C.
echo.

streamlit run app.py
set EXITCODE=%errorlevel%

if "%EXITCODE%"=="0" (
    echo.
    echo Application fermee proprement. Cette fenetre va se refermer...
    timeout /t 2 >nul
    exit
)

echo.
echo ------------------------------------------------------------
echo L'application s'est arretee de maniere inattendue (code %EXITCODE%).
echo Si un message d'erreur s'affiche au-dessus, c'est probablement
echo ca qui explique pourquoi : relis-le avant de refermer.
echo ------------------------------------------------------------
pause
