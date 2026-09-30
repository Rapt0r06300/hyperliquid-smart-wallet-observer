@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   H-181 - LE TOP-40 DE LA RECHERCHE EST-IL DISCERNABLE DU HASARD ?
REM   Controle par PERMUTATION : meme espace, meme couts, mais SANS edge.
REM   ASCII PUR, pas de "chcp", pas de pause -> "%~dp0rapports\h181_vainqueur.txt"
REM   Lecture seule. Aucun ordre, aucune cle, aucune signature.
REM ==================================================================================
(
  echo === [1/2] La malediction du vainqueur, demontree sur du bruit PUR ===
  python -m pytest -q --tb=short -p no:cacheprovider tests\test_overfit_selection.py
  echo.
  echo === [2/2] Sur les VRAIES donnees : reel contre hasard ===
  python tools\h181_malediction_du_vainqueur.py
) > "%~dp0rapports\h181_vainqueur.txt" 2>&1
exit /b 0
