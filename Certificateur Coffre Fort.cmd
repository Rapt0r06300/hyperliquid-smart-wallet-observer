@echo off
setlocal enableextensions enabledelayedexpansion
chcp 65001 >nul
title ALINA SMART FLOW - CERTIFIER COFFRE-FORT
set "CV_ROOT=%~dp0"
set "ALINA_LAUNCH_RUN_ID=%DATE%_%TIME%_%RANDOM%_%RANDOM%"
set "ALINA_LAUNCH_MODE=certificate-all"
set "ALINA_LAUNCH_PYTHON=unresolved"

rem --- Resolution de Python ---
set "CV_PYTHON="
set "CV_PY_ARGS="
if exist "%CV_ROOT%tools\python\python.exe" set "CV_PYTHON=%CV_ROOT%tools\python\python.exe"
if not defined CV_PYTHON if exist "%CV_ROOT%.venv\Scripts\python.exe" set "CV_PYTHON=%CV_ROOT%.venv\Scripts\python.exe"
if not defined CV_PYTHON (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "CV_PYTHON=py"
    set "CV_PY_ARGS=-3"
  )
)
if not defined CV_PYTHON (
  where python >nul 2>nul
  if not errorlevel 1 set "CV_PYTHON=python"
)
set "ALINA_LAUNCH_PYTHON=%CV_PYTHON% %CV_PY_ARGS%"
set "ALINA_LAUNCH_OUTPUT_LOG=runtime/coffre_certifie/CERTIF_JOURNAL.jsonl"
set "PYTHONUNBUFFERED=1"
if not defined CV_PYTHON (
  set "ALINA_LAUNCH_PYTHON=unresolved"
  call "%CV_ROOT%tools\launcher_log.cmd" "Certificateur Coffre Fort" EXIT preflight "python-3-not-found" "30"
  echo [NO_GO] Python 3 introuvable. Aucune certification n'a ete lancee.
  endlocal & exit /b 30
)

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
call "%CV_ROOT%tools\launcher_log.cmd" "Certificateur Coffre Fort" START preflight "certification-request" ""

rem Ouvre l'ecran de suivi (%% avancement, debit, ETA) dans une fenetre separee.
if exist "%CV_ROOT%SUIVI_COFFRE.cmd" start "" "%CV_ROOT%SUIVI_COFFRE.cmd"

"%CV_PYTHON%" %CV_PY_ARGS% "%CV_ROOT%tools\sceller_coffre_local.py" --root "%CV_ROOT%." %MODE% %RESET%
set "RC=%ERRORLEVEL%"
call "%CV_ROOT%tools\launcher_log.cmd" "Certificateur Coffre Fort" RESULT certification "sceller_coffre_local.py" "%RC%"
echo.
if "%RC%"=="0" (
  echo [OK] Coffre-fort a jour.
  echo   Index   : runtime\coffre_certifie\COFFRE_INDEX.json
  echo   Journal : runtime\coffre_certifie\CERTIF_JOURNAL.jsonl
) else (
  echo [ERREUR] Certification interrompue ^(code %RC%^). Voir le log runtime\logs\coffre_certifie\.
)
call "%CV_ROOT%tools\launcher_log.cmd" "Certificateur Coffre Fort" EXIT completion "certification-finished" "%RC%"
endlocal & exit /b %RC%

:help
call "%CV_ROOT%tools\launcher_log.cmd" "Certificateur Coffre Fort" START help "usage-request" "0"
echo Usage : Certificateur Coffre Fort.cmd [--data] [--reset]
echo   (defaut)   certifie TOUTES les donnees du projet et les depose dans le coffre-fort
echo   --data     limite a runtime\data (collecte courante)
echo   --reset    remet les flux vivants a zero apres un scellage verifie (affichage repart de 0)
call "%CV_ROOT%tools\launcher_log.cmd" "Certificateur Coffre Fort" EXIT help "usage-returned" "0"
endlocal & exit /b 0
