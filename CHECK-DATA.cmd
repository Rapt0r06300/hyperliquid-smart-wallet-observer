@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   1. BACKFILL 30 jours d'historique (candleSnapshot -- deja ecrit, jamais utilise)
REM   2. SUITE COMPLETE + SAFETY
REM   ASCII PUR, pas de pause -> check_data.txt
REM ==================================================================================
echo DEBUT > check_data.txt
echo === 1. BACKFILL 30 JOURS === >> check_data.txt
python tools\backfill_candles.py --jours 30 --intervalle 1m >> check_data.txt 2>&1
echo. >> check_data.txt
echo === 2. SUITE COMPLETE === >> check_data.txt
python -m pytest -q -p no:cacheprovider --tb=short >> check_data.txt 2>&1
echo. >> check_data.txt
echo === 3. SAFETY (no-real-trade) === >> check_data.txt
python -m hl_observer safety-audit >> check_data.txt 2>&1
echo FIN >> check_data.txt
exit /b 0
