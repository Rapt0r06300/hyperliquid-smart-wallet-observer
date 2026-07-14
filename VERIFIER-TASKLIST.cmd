@echo off
setlocal
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   TASKLIST.md contient-il les 543 taches, sans en oublier UNE seule ?
REM   Lu depuis Windows (le sandbox tronque le fichier et MENT).
REM   ASCII PUR, pas de pause -> verif_tasklist.txt
REM ==================================================================================
echo DEBUT > verif_tasklist.txt
python tools\verifier_tasklist.py >> verif_tasklist.txt 2>&1
echo FIN >> verif_tasklist.txt
exit /b 0
