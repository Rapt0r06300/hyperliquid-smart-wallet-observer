@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   LOT P* -- #292 (le panneau de securite mentait) + #318 (la fraicheur etait fabriquee)
REM   SUITE COMPLETE + SAFETY. ASCII PUR, pas de pause -> check_p.txt
REM ==================================================================================
echo DEBUT > check_p.txt
echo === SUITE COMPLETE === >> check_p.txt
python -m pytest -q -p no:cacheprovider --tb=short >> check_p.txt 2>&1
echo. >> check_p.txt
echo === SAFETY (no-real-trade) === >> check_p.txt
python -m hl_observer safety-audit >> check_p.txt 2>&1
echo FIN >> check_p.txt
exit /b 0
