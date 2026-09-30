@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   3 tests rouges vus par la suite COMPLETE (sous coverage). Sont-ils A MOI ?
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_3_rouges.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_3_rouges.txt"
python -m pytest -q --tb=long -p no:cacheprovider tests\test_risk_guards_no_limbo.py::test_le_nombre_de_modules_MORTS_ne_doit_JAMAIS_remonter >> "%~dp0rapports\check_3_rouges.txt" 2>&1
echo. >> "%~dp0rapports\check_3_rouges.txt"
echo === les 2 tests UI === >> "%~dp0rapports\check_3_rouges.txt"
python -m pytest -q --tb=line -p no:cacheprovider tests\test_ui_simulation_persistence.py tests\test_ui_simulation_v9_filters.py >> "%~dp0rapports\check_3_rouges.txt" 2>&1
echo FIN >> "%~dp0rapports\check_3_rouges.txt"
exit /b 0
