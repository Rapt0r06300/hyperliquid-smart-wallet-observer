@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   G2 - LA SUITE COMPLETE. Le noyau touche 5 fichiers de production : il faut
REM   prouver qu'il n'a rien casse ailleurs. ASCII PUR, pas de pause -> "%~dp0rapports\g2_regression.txt"
REM ==================================================================================
(
  echo === SUITE COMPLETE ===
  python -m pytest -q --tb=line -p no:cacheprovider
  echo.
  echo === SECURITE : aucun ordre reel possible ===
  python -m hl_observer safety-audit
) > "%~dp0rapports\g2_regression.txt" 2>&1
exit /b 0
