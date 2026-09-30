@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #598 -- les 2 tests UI exigeaient un edge INVENTE. On leur donne une VRAIE mesure,
REM   et on verrouille l'invariant : SANS mesure, le bot REFUSE.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_598_fix.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_598_fix.txt"
echo === les 2 tests UI + le nouvel invariant === >> "%~dp0rapports\check_598_fix.txt"
python -m pytest -q --tb=short -p no:cacheprovider tests\test_ui_simulation_v9_filters.py tests\test_ui_simulation_persistence.py >> "%~dp0rapports\check_598_fix.txt" 2>&1
echo. >> "%~dp0rapports\check_598_fix.txt"
echo === non-regression edge : Q1 + G2 === >> "%~dp0rapports\check_598_fix.txt"
python -m pytest -q --tb=line -p no:cacheprovider tests\test_edge_source_q1.py tests\test_measured_edge_table.py tests\test_risk_guards_no_limbo.py >> "%~dp0rapports\check_598_fix.txt" 2>&1
echo. >> "%~dp0rapports\check_598_fix.txt"
echo === safety-audit === >> "%~dp0rapports\check_598_fix.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_598_fix.txt" 2>&1
echo FIN >> "%~dp0rapports\check_598_fix.txt"
exit /b 0
