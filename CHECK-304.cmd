@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   QUI est le 304e module mort ? On ne releve pas le plafond, on l'identifie.
REM   ASCII PUR, pas de pause -> check_304.txt
REM ==================================================================================
echo DEBUT > check_304.txt
python tools\qui_est_le_304e_mort.py >> check_304.txt 2>&1
echo FIN >> check_304.txt
exit /b 0
