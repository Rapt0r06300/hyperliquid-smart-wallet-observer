@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   T3e (#593) -- SUITE COMPLETE + SAFETY. La suite ciblee cache des rouges :
REM   c'est la lecon de G2 (8 rouges) et du 13/07 (3 rouges). ASCII PUR, pas de pause.
REM ==================================================================================
echo DEBUT > check_593_full.txt
echo === SUITE COMPLETE === >> check_593_full.txt
python -m pytest -q -p no:cacheprovider --tb=line >> check_593_full.txt 2>&1
echo. >> check_593_full.txt
echo === SAFETY (no-real-trade) === >> check_593_full.txt
python -m hl_observer safety-audit >> check_593_full.txt 2>&1
echo FIN >> check_593_full.txt
exit /b 0
