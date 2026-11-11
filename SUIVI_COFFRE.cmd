@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
title ALINA SMART FLOW - SUIVI COFFRE

set "SC_PYTHON="
set "SC_PY_ARGS="
if exist "%~dp0tools\python\python.exe" set "SC_PYTHON=%~dp0tools\python\python.exe"
if not defined SC_PYTHON if exist "%~dp0.venv\Scripts\python.exe" set "SC_PYTHON=%~dp0.venv\Scripts\python.exe"
if not defined SC_PYTHON (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "SC_PYTHON=py"
    set "SC_PY_ARGS=-3"
  )
)
if not defined SC_PYTHON set "SC_PYTHON=python"

echo.
echo ================================================================
echo   ALINA SMART FLOW - SUIVI COFFRE
echo   Avancement de la certification -^> coffre : %%, debit, ETA.
echo   Fonctionne meme si la certif tourne en tache de fond.
echo   q = quitter (lecture seule).
echo ================================================================
echo.

"%SC_PYTHON%" %SC_PY_ARGS% "%~dp0tools\suivi_coffre.py" --intervalle 1
endlocal & exit /b %ERRORLEVEL%
