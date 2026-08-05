@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   H-05 (#410) + H-30 (#435) : la coupe train/test FUYAIT (aucune purge, aucun embargo).
REM   Purge + embargo branches dans les DEUX chemins de scenario_search.
REM   SUITE COMPLETE + SAFETY. ASCII PUR, pas de pause -> "%~dp0rapports\check_h.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_h.txt"
echo === SUITE COMPLETE === >> "%~dp0rapports\check_h.txt"
python -m pytest -q -p no:cacheprovider --tb=short >> "%~dp0rapports\check_h.txt" 2>&1
echo. >> "%~dp0rapports\check_h.txt"
echo === SAFETY (no-real-trade) === >> "%~dp0rapports\check_h.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_h.txt" 2>&1
echo FIN >> "%~dp0rapports\check_h.txt"
exit /b 0
