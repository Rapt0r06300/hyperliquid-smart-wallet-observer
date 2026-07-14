@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   DIAG-BORNES - diagnostic JETABLE. ASCII PUR, pas de "chcp".
REM   Ecrit le resultat dans diag_bornes.txt pour qu'il soit relisible.
REM ==================================================================================
python tools\diag_bornes.py > diag_bornes.txt 2>&1
type diag_bornes.txt
pause
