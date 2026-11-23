@echo off
setlocal
cd /d "%~dp0"

title Candidatures alternance
echo ============================================
echo   Generateur de candidatures - alternance
echo ============================================
echo.

rem --- 1. Environnement Python isole (.venv), cree automatiquement au 1er lancement
if not exist ".venv\Scripts\python.exe" (
    echo Premier lancement : creation de l'environnement Python ^(.venv^)...
    where py >nul 2>&1
    if not errorlevel 1 (
        py -3 -m venv .venv
    ) else (
        python -m venv .venv
    )
)
if not exist ".venv\Scripts\python.exe" (
    echo.
    echo ERREUR : impossible de creer l'environnement Python.
    echo Installe Python 3.10 ou plus recent depuis https://www.python.org/downloads/
    echo en cochant "Add python.exe to PATH" pendant l'installation, puis relance.
    pause
    exit /b 1
)
call ".venv\Scripts\activate.bat"

rem --- 2. Dependances : installees ou mises a jour seulement si requirements.txt
rem ---    a change depuis la derniere fois (copie gardee dans .venv).
fc /b requirements.txt ".venv\requirements_installees.txt" >nul 2>&1
if errorlevel 1 (
    echo Installation / mise a jour des dependances, une minute environ...
    python -m pip install --upgrade pip >nul 2>&1
    python -m pip install -r requirements.txt
    if errorlevel 1 (
        echo.
        echo ERREUR pendant l'installation des dependances. Verifie ta connexion
        echo Internet puis relance ce fichier.
        pause
        exit /b 1
    )
    copy /y requirements.txt ".venv\requirements_installees.txt" >nul
)

echo.
echo Demarrage de l'application... le navigateur va s'ouvrir automatiquement.
echo.
echo IMPORTANT : laisse cette fenetre ouverte tant que tu utilises l'app.
echo Pour l'arreter : bouton "Fermer l'app" dans la page, ou ferme cette fenetre.
echo.

python -m streamlit run app.py
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
