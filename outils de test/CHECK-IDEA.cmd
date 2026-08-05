@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   Lot IDEA -- SUITE COMPLETE + SAFETY. La suite ciblee cache des rouges (lecon G2).
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_idea.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_idea.txt"
echo === SUITE COMPLETE === >> "%~dp0rapports\check_idea.txt"
python -m pytest -q -p no:cacheprovider --tb=line >> "%~dp0rapports\check_idea.txt" 2>&1
echo. >> "%~dp0rapports\check_idea.txt"
echo === SAFETY (no-real-trade) === >> "%~dp0rapports\check_idea.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_idea.txt" 2>&1
echo FIN >> "%~dp0rapports\check_idea.txt"
exit /b 0
