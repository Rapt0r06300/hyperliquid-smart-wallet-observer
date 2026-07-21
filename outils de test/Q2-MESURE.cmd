@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   Q2 - MESURE SUR LES VRAIS CARNETS ENREGISTRES.
REM   Le bug d'extrapolation a-t-il deja menti ? De combien le mid ment-il ?
REM   ASCII PUR, pas de "chcp", pas de pause -> "%~dp0rapports\q2_mesure.txt"
REM   Lecture seule. Aucun ordre, aucune cle, aucune signature.
REM ==================================================================================
python tools\mesurer_jambes_reelles.py --notional 500 > "%~dp0rapports\q2_mesure.txt" 2>&1
exit /b 0
