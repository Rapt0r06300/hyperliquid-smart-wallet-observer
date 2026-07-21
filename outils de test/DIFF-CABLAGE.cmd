@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   Pourquoi le nombre de modules MORTS a-t-il bouge ? On MESURE, on ne devine pas.
REM   ASCII PUR, pas de "chcp". Sans pause : tout va dans diff_cablage.txt.
REM   Lecture seule. Aucun ordre, aucune cle, aucune signature.
REM ==================================================================================
python tools\diff_cablage.py > "%~dp0rapports\diff_cablage.txt" 2>&1
exit /b 0
