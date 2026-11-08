@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
title RAPPORT COLLECTEURS - erreurs + ameliorations
set "PYTHONPATH=src"
set "CV_PYTHON=python"
if exist ".venv\Scripts\python.exe" set "CV_PYTHON=.venv\Scripts\python.exe"
echo.
echo Generation du rapport detaille de tous les collecteurs...
"%CV_PYTHON%" "tools\rapport_collecteurs.py" --root "%~dp0."
echo.
if exist "runtime\logs\rapport_collecteurs.log" (
  echo Ouverture du rapport...
  start "" notepad "runtime\logs\rapport_collecteurs.log"
) else (
  echo [ERREUR] Rapport non genere.
)
pause
endlocal
