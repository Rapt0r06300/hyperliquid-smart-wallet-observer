@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #127 IMPROVE-20 : le regime, sans lire le futur.
REM   + non-regression sur les gates de validation et la recherche de scenarios.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_127.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_127.txt"
echo === 1 sur 3 : regime causal + gate qui declare sa degradation === >> "%~dp0rapports\check_127.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_regime_label.py >> "%~dp0rapports\check_127.txt" 2>&1
echo. >> "%~dp0rapports\check_127.txt"
echo === 2 sur 3 : non-regression gates + regime existants === >> "%~dp0rapports\check_127.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_validation_gates.py tests\test_regime_detection.py tests\test_regime_models.py tests\test_scenario_search.py >> "%~dp0rapports\check_127.txt" 2>&1
echo. >> "%~dp0rapports\check_127.txt"
echo === 3 sur 3 : safety-audit === >> "%~dp0rapports\check_127.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_127.txt" 2>&1
echo FIN >> "%~dp0rapports\check_127.txt"
exit /b 0
