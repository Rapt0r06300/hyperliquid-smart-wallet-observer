@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #395 / M-19 -- les 7 garde-fous ANTI-OVERFIT etaient TOUS MORTS.
REM   Le gate de deflation est branche dans les DEUX chemins de scenario_search.
REM   SUITE COMPLETE + SAFETY. ASCII PUR, pas de pause -> "%~dp0rapports\check_m19.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_m19.txt"
echo === SUITE COMPLETE === >> "%~dp0rapports\check_m19.txt"
python -m pytest -q -p no:cacheprovider --tb=short >> "%~dp0rapports\check_m19.txt" 2>&1
echo. >> "%~dp0rapports\check_m19.txt"
echo === SAFETY (no-real-trade) === >> "%~dp0rapports\check_m19.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_m19.txt" 2>&1
echo FIN >> "%~dp0rapports\check_m19.txt"
exit /b 0
