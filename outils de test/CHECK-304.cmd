@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   QUI est le 304e module mort ? On ne releve pas le plafond, on l'identifie.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_304.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_304.txt"
python tools\qui_est_le_304e_mort.py >> "%~dp0rapports\check_304.txt" 2>&1
echo FIN >> "%~dp0rapports\check_304.txt"
exit /b 0
