@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   Lot IDEA -- SUITE COMPLETE + SAFETY. La suite ciblee cache des rouges (lecon G2).
REM   ASCII PUR, pas de pause -> check_idea.txt
REM ==================================================================================
echo DEBUT > check_idea.txt
echo === SUITE COMPLETE === >> check_idea.txt
python -m pytest -q -p no:cacheprovider --tb=line >> check_idea.txt 2>&1
echo. >> check_idea.txt
echo === SAFETY (no-real-trade) === >> check_idea.txt
python -m hl_observer safety-audit >> check_idea.txt 2>&1
echo FIN >> check_idea.txt
exit /b 0
