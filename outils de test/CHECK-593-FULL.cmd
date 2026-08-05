@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   T3e (#593) -- SUITE COMPLETE + SAFETY. La suite ciblee cache des rouges :
REM   c'est la lecon de G2 (8 rouges) et du 13/07 (3 rouges). ASCII PUR, pas de pause.
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_593_full.txt"
echo === SUITE COMPLETE === >> "%~dp0rapports\check_593_full.txt"
python -m pytest -q -p no:cacheprovider --tb=line >> "%~dp0rapports\check_593_full.txt" 2>&1
echo. >> "%~dp0rapports\check_593_full.txt"
echo === SAFETY (no-real-trade) === >> "%~dp0rapports\check_593_full.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_593_full.txt" 2>&1
echo FIN >> "%~dp0rapports\check_593_full.txt"
exit /b 0
