@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   ETAT REEL des 8 taches #112 -> #145. Prouve par EXECUTION, jamais par lecture.
REM   ASCII PUR, pas de "chcp", pas de pause -> "%~dp0rapports\etat_112_145.txt"
REM ==================================================================================
python tools\etat_112_145.py > "%~dp0rapports\etat_112_145.txt" 2>&1
exit /b 0
