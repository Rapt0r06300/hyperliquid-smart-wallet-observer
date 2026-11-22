@echo off
chcp 65001 >nul
setlocal EnableExtensions
rem ===================================================================
rem   ETA DONNEES LABO - combien de temps encore collecter ?
rem ===================================================================
rem   Affiche un ETA VIVANT, recalcule a chaque rafraichissement d apres
rem   le DEBIT reel de la collecte -- pas une date fixe.
rem
rem   Ce qui bloque le labo (mesure du 22/11/2026) : le nombre de
rem   JOURNEES UTC distinctes et DENSES de signaux evaluables, pas un
rem   volume d octets. Une journee ne s acquiert qu une fois par jour
rem   calendaire, et SEULEMENT si le debit la rend dense : si le debit
rem   tombe, la journee en cours cesse de compter et l ETA RECULE.
rem
rem   LECTURE SEULE : aucun collecteur n est demarre ni arrete.
rem   q ou Ctrl+C pour quitter.
rem ===================================================================
set "ETA_ROOT=%~dp0"
set "ETA_PYTHON="
if exist "%ETA_ROOT%tools\python\python.exe" set "ETA_PYTHON=%ETA_ROOT%tools\python\python.exe"
if not defined ETA_PYTHON if exist "%ETA_ROOT%.venv\Scripts\python.exe" set "ETA_PYTHON=%ETA_ROOT%.venv\Scripts\python.exe"
if not defined ETA_PYTHON (
  where python >nul 2>nul
  if not errorlevel 1 set "ETA_PYTHON=python"
)
if not defined ETA_PYTHON (
  echo [REFUS] Aucun Python trouve : on ne peut pas mesurer, donc on n affiche rien.
  echo    Un ETA sans mesure serait une invention.
  endlocal
  exit /b 2
)
"%ETA_PYTHON%" "%ETA_ROOT%tools\eta_donnees_labo.py" --racine "%ETA_ROOT%." %*
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%
