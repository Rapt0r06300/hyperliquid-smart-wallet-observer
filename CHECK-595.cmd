@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #595 : le regime est BRANCHE dans la recherche (causal, seuil du TRAIN seul).
REM   Rapide. La couverture de lignes (#596) est dans COUVERTURE-LIGNES.cmd (long).
REM   ASCII PUR, pas de pause -> check_595.txt
REM ==================================================================================
echo DEBUT > check_595.txt
echo === 1 sur 3 : le regime, branche et causal === >> check_595.txt
python -m pytest -q --tb=short -p no:cacheprovider tests\test_regime_wiring.py >> check_595.txt 2>&1
echo. >> check_595.txt
echo === 2 sur 3 : NON-REGRESSION du moteur de recherche (le plus important) === >> check_595.txt
python -m pytest -q --tb=short -p no:cacheprovider tests\test_scenario_search.py tests\test_scenario_db.py tests\test_scenario_grid.py tests\test_validation_gates.py tests\test_regime_label.py tests\test_regime_detection.py >> check_595.txt 2>&1
echo. >> check_595.txt
echo === 3 sur 3 : safety-audit === >> check_595.txt
python -m hl_observer safety-audit >> check_595.txt 2>&1
echo FIN >> check_595.txt
exit /b 0
