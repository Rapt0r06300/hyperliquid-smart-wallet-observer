@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   T3d - Le hot path P4/P5 est-il VRAIMENT mort ? Preuve par EXECUTION.
REM   ASCII PUR, pas de "chcp". Sans pause : tout va dans t3d_preuve.txt.
REM   Lecture seule. On IMPORTE seulement : aucun serveur, aucune socket, aucun ordre.
REM ==================================================================================
python tools\prouver_hot_path.py > "%~dp0rapports\t3d_preuve.txt" 2>&1
exit /b 0
