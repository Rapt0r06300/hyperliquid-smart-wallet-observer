@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   Verification complete apres H-160 / GH-02 (sonde de biais recursif).
REM   ASCII PUR, pas de pause -> check_h160.txt
REM ==================================================================================
echo DEBUT > check_h160.txt
echo === LA SUITE COMPLETE === >> check_h160.txt
python -m pytest -q --tb=line -p no:cacheprovider tests >> check_h160.txt 2>&1
echo. >> check_h160.txt
echo === safety-audit === >> check_h160.txt
python -m hl_observer safety-audit >> check_h160.txt 2>&1
echo FIN >> check_h160.txt
exit /b 0
