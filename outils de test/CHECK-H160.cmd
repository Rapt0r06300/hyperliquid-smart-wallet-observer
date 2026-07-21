@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   Verification complete apres H-160 / GH-02 (sonde de biais recursif).
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_h160.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_h160.txt"
echo === LA SUITE COMPLETE === >> "%~dp0rapports\check_h160.txt"
python -m pytest -q --tb=line -p no:cacheprovider tests >> "%~dp0rapports\check_h160.txt" 2>&1
echo. >> "%~dp0rapports\check_h160.txt"
echo === safety-audit === >> "%~dp0rapports\check_h160.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_h160.txt" 2>&1
echo FIN >> "%~dp0rapports\check_h160.txt"
exit /b 0
