@echo off
setlocal enableextensions enabledelayedexpansion
chcp 65001 >nul
title ALINA SMART FLOW - CERTIFIER COFFRE-FORT
for %%R in ("%~dp0..\..") do set "CV_ROOT=%%~fR\"

rem --- Resolution de Python ---
set "CV_PYTHON="
if exist "%CV_ROOT%.venv\Scripts\python.exe" set "CV_PYTHON=%CV_ROOT%.venv\Scripts\python.exe"
if not defined CV_PYTHON for %%P in (python.exe py.exe) do if not defined CV_PYTHON set "CV_PYTHON=%%~$PATH:P"
if not defined CV_PYTHON set "CV_PYTHON=python"
set "PYTHONUNBUFFERED=1"

rem --- Arguments : (defaut) TOUT le projet ; --data = seulement runtime\data ; --reset = remet l affichage a zero ---
set "MODE=--tout"
set "RESET="
for %%A in (%*) do (
  if /I "%%~A"=="--data" set "MODE="
  if /I "%%~A"=="--reset" set "RESET=--reset-affichage"
  if /I "%%~A"=="--help" goto :help
  if /I "%%~A"=="-h" goto :help
)

echo.
echo === Certification du coffre-fort "donnees certifiees" (tier LOCAL) ===
if defined MODE (echo   Source : TOUT le dossier projet) else (echo   Source : runtime\data uniquement)
if defined RESET echo   Reset affichage : les flux vivants seront remis a zero apres scellage verifie.
echo   PAPER / LECTURE SEULE - aucun reseau, aucun ordre.
echo.

rem Ouvre l'ecran de suivi (%% avancement, debit, ETA) dans une fenetre separee.
if exist "%CV_ROOT%tools\launchers\SUIVI_COFFRE.cmd" start "" "%CV_ROOT%tools\launchers\SUIVI_COFFRE.cmd"

"%CV_PYTHON%" "%CV_ROOT%tools\sceller_coffre_local.py" --root "%CV_ROOT%." %MODE% %RESET%
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo [OK] Coffre-fort a jour.
  echo   Index   : runtime\coffre_certifie\COFFRE_INDEX.json
  echo   Journal : runtime\coffre_certifie\CERTIF_JOURNAL.jsonl
) else (
  echo [ERREUR] Certification interrompue ^(code %RC%^). Voir le log runtime\logs\coffre_certifie\.
)
endlocal & exit /b %RC%

:help
echo Usage : Certificateur Coffre Fort.cmd [--data] [--reset]
echo   (defaut)   certifie TOUTES les donnees du projet et les depose dans le coffre-fort
echo   --data     limite a runtime\data (collecte courante)
echo   --reset    remet les flux vivants a zero apres un scellage verifie (affichage repart de 0)
endlocal & exit /b 0
