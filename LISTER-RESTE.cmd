@echo off
setlocal
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   Extrait TOUTES les taches non cochees de TASKLIST.md -> RESTE-A-FAIRE.txt
REM   ASCII PUR, pas de pause.
REM ==================================================================================
python tools\lister_reste.py > lister_reste_log.txt 2>&1
exit /b 0
