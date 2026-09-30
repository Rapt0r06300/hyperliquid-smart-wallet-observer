@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   1. BACKFILL 30 jours d'historique (candleSnapshot -- deja ecrit, jamais utilise)
REM   2. SUITE COMPLETE + SAFETY
REM   ASCII PUR, pas de pause -> "%~dp0rapports\check_data.txt"
REM ==================================================================================
echo DEBUT > "%~dp0rapports\check_data.txt"
echo === 1. BACKFILL 30 JOURS === >> "%~dp0rapports\check_data.txt"
python tools\backfill_candles.py --jours 30 --intervalle 1m >> "%~dp0rapports\check_data.txt" 2>&1
echo. >> "%~dp0rapports\check_data.txt"
echo === 2. SUITE COMPLETE === >> "%~dp0rapports\check_data.txt"
python -m pytest -q -p no:cacheprovider --tb=short >> "%~dp0rapports\check_data.txt" 2>&1
echo. >> "%~dp0rapports\check_data.txt"
echo === 3. SAFETY (no-real-trade) === >> "%~dp0rapports\check_data.txt"
python -m hl_observer safety-audit >> "%~dp0rapports\check_data.txt" 2>&1
echo FIN >> "%~dp0rapports\check_data.txt"
exit /b 0
