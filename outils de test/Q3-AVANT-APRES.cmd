@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   Q3 - LE PRIX AVAIT-IL DEJA BOUGE AVANT QUE LE FILL SOIT PUBLIC ?
REM   La CAUSE mecanique du "pas d'edge en copy-trading". Markout de T-300s a T+300s.
REM   ASCII PUR, pas de "chcp", pas de pause -> "%~dp0rapports\q3_avant_apres.txt"
REM   Lecture seule. Aucun ordre, aucune cle, aucune signature.
REM ==================================================================================
python tools\q3_avant_apres_le_signal.py > "%~dp0rapports\q3_avant_apres.txt" 2>&1
exit /b 0
