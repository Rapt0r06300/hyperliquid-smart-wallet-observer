@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #595 : le regime est BRANCHE dans la recherche (causal, seuil du TRAIN seul).
REM   #596 : la VRAIE couverture -- celle des LIGNES executees.
REM   ASCII PUR, pas de pause -> check_595_596.txt
REM ==================================================================================
echo DEBUT > check_595_596.txt
echo === 1 sur 4 : le regime, branche et causal === >> check_595_596.txt
python -m pytest -q --tb=short -p no:cacheprovider tests\test_regime_wiring.py >> check_595_596.txt 2>&1
echo. >> check_595_596.txt
echo === 2 sur 4 : NON-REGRESSION du moteur de recherche (le plus important) === >> check_595_596.txt
python -m pytest -q --tb=short -p no:cacheprovider tests\test_scenario_search.py tests\test_scenario_db.py tests\test_scenario_grid.py tests\test_validation_gates.py tests\test_regime_label.py tests\test_regime_detection.py >> check_595_596.txt 2>&1
echo. >> check_595_596.txt
echo === 3 sur 4 : couverture de LIGNES (peut prendre plusieurs minutes) === >> check_595_596.txt
python tools\couverture_de_lignes.py >> check_595_596.txt 2>&1
echo. >> check_595_596.txt
echo === 4 sur 4 : safety-audit === >> check_595_596.txt
python -m hl_observer safety-audit >> check_595_596.txt 2>&1
echo FIN >> check_595_596.txt
exit /b 0
