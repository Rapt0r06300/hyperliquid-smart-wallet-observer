@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM  Pourquoi le noyau refuse-t-il le carry ? On lui demande sa PREUVE.
REM  ASCII PUR, pas de pause -> "%~dp0rapports\debug_noyau.txt"
python tools\debug_noyau_carry.py > "%~dp0rapports\debug_noyau.txt" 2>&1
exit /b 0
