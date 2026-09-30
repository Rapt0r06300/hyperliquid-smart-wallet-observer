@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   LOT P* -- #292 (le panneau de securite mentait) + #318 (la fraicheur etait fabriquee)
REM   SUITE COMPLETE + SAFETY. ASCII PUR, pas de pause -> "%~dp0rapports\check_p.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_p.txt"
echo === SUITE COMPLETE === >> "%~dp0rapports\check_p.txt"
python -m pytest -q -p no:cacheprovider --tb=short >> "%~dp0rapports\check_p.txt" 2>&1
echo. >> "%~dp0rapports\check_p.txt"
echo === SAFETY (no-real-trade) === >> "%~dp0rapports\check_p.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_p.txt" 2>&1
echo FIN >> "%~dp0rapports\check_p.txt"
exit /b 0
