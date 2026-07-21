@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #242 REFAIT SUR **208 JOURS** (au lieu de 18,9 h).
REM   Il etait mort « data-limited ». On avait l'historique a un appel de distance.
REM   ASCII PUR, pas de pause -> "%~dp0rapports\refaire_242.txt"
REM ==================================================================================
echo === #242 sur 208 JOURS (bougies 1h) === > "%~dp0rapports\refaire_242.txt"
python tools\mesurer_cointegration.py --source=bougies:1h >> "%~dp0rapports\refaire_242.txt" 2>&1
exit /b 0
