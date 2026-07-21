@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   LA PROFONDEUR DU CARNET — *un edge sur un carnet de 3 $ n'existe pas.*
REM
REM   LE DERNIER RISQUE NON MESURE. Il peut annuler les 3 carrys.
REM
REM   PURR / PUMP / HYPE sont de PETITS marches. Leur funding est eleve PRECISEMENT
REM   parce que les detenir est dangereux et que peu de gens veulent le faire.
REM   ***Le funding EST le prix de ce risque.***
REM
REM   Si le carnet est mince, le slippage mange l'edge -- et il le mange 4 FOIS :
REM   spot achat + spot vente + perp vente + perp achat.
REM
REM   -> ON MARCHE DANS LE CARNET, niveau par niveau. On ne prend JAMAIS le meilleur
REM      prix en supposant qu'il tient pour toute la taille. *C'est exactement
REM      l'illusion qui a fabrique le faux +31 bps de T1 (bid-ask bounce).*
REM
REM   Lecture seule. Aucun ordre reel. ASCII PUR -> "%~dp0rapports\la_profondeur.txt"
REM ==================================================================================

echo ============ 1. LES TESTS DU CARNET ============ > "%~dp0rapports\la_profondeur.txt"
python -m pytest -q tests\test_spot_depth.py >> "%~dp0rapports\la_profondeur.txt" 2>&1

echo. >> "%~dp0rapports\la_profondeur.txt"
echo ============ 2. LA PROFONDEUR REELLE (spot + perp, 4 jambes) ============ >> "%~dp0rapports\la_profondeur.txt"
python tools\profondeur_spot.py >> "%~dp0rapports\la_profondeur.txt" 2>&1

echo. >> "%~dp0rapports\la_profondeur.txt"
echo ============ 3. SECURITE ============ >> "%~dp0rapports\la_profondeur.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\la_profondeur.txt" 2>&1
exit /b 0
