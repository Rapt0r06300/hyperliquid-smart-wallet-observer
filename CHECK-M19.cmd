@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #395 / M-19 -- les 7 garde-fous ANTI-OVERFIT etaient TOUS MORTS.
REM   Le gate de deflation est branche dans les DEUX chemins de scenario_search.
REM   SUITE COMPLETE + SAFETY. ASCII PUR, pas de pause -> check_m19.txt
REM ==================================================================================
echo DEBUT > check_m19.txt
echo === SUITE COMPLETE === >> check_m19.txt
python -m pytest -q -p no:cacheprovider --tb=short >> check_m19.txt 2>&1
echo. >> check_m19.txt
echo === SAFETY (no-real-trade) === >> check_m19.txt
python -m hl_observer safety-audit >> check_m19.txt 2>&1
echo FIN >> check_m19.txt
exit /b 0
