@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   G1 - LA RECHERCHE 150 M LIT-ELLE LE FUTUR ?
REM   Test DIFFERENTIEL : on TORTURE les donnees, on ne lit pas le code.
REM   ASCII PUR, pas de "chcp", pas de pause -> g1_lookahead.txt
REM   Lecture seule. Aucun ordre, aucune cle, aucune signature.
REM ==================================================================================
(
  echo === [1/2] Le detecteur sait-il attraper un TRICHEUR ? ===
  python -m pytest -q --tb=short -p no:cacheprovider tests\test_lookahead_differential.py
  echo.
  echo === [2/2] La VRAIE recherche, sur les VRAIES donnees ===
  python tools\g1_lookahead_differentiel.py
) > g1_lookahead.txt 2>&1
exit /b 0
