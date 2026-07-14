@echo off
REM ============================================================
REM  PIPELINE REPRODUCTIBLE EN UNE COMMANDE (IDEA-79)
REM  Rejoue toute la recherche : tests -> analyses -> rapports.
REM  100%% lecture seule / paper. Aucun ordre reel.
REM ============================================================
cd /d "%~dp0.."
set PYTHONPATH=src

echo [1/4] Tests (le code doit etre vert avant toute analyse)...
python -m pytest -q
if errorlevel 1 goto :failed

echo.
echo [2/4] Analyse par segments (edge net apres couts, hors-echantillon)...
python tools\analysis\_seg_analysis.py

echo.
echo [3/4] Scan de mecanismes + controle aleatoire...
python tools\analysis\_mechanism_scan.py

echo.
echo [4/4] Modele predictif (OOS + controle aleatoire)...
python tools\analysis\_predictor_experiment.py

echo.
echo ============================================================
echo   PIPELINE TERMINE. Rapports dans docs\audit\
echo ============================================================
exit /b 0

:failed
echo ECHEC DES TESTS — pipeline interrompu.
exit /b 1
