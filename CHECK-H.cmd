@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   H-05 (#410) + H-30 (#435) : la coupe train/test FUYAIT (aucune purge, aucun embargo).
REM   Purge + embargo branches dans les DEUX chemins de scenario_search.
REM   SUITE COMPLETE + SAFETY. ASCII PUR, pas de pause -> check_h.txt
REM ==================================================================================
echo DEBUT > check_h.txt
echo === SUITE COMPLETE === >> check_h.txt
python -m pytest -q -p no:cacheprovider --tb=short >> check_h.txt 2>&1
echo. >> check_h.txt
echo === SAFETY (no-real-trade) === >> check_h.txt
python -m hl_observer safety-audit >> check_h.txt 2>&1
echo FIN >> check_h.txt
exit /b 0
