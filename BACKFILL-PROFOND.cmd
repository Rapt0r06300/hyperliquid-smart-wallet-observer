@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   LA VRAIE PROFONDEUR.
REM
REM   Hyperliquid plafonne `candleSnapshot` a ~5 000 bougies par coin, quel que soit le
REM   startTime demande. En 1 minute -> 3,5 jours. La profondeur s'obtient donc en
REM   CHANGEANT D'INTERVALLE :
REM       15m -> ~52 jours     1h -> ~208 jours
REM
REM   Aucun ordre reel. Lecture publique seule (/info).
REM   ASCII PUR, pas de pause -> backfill_profond.txt
REM ==================================================================================
echo === 15m (visee : ~52 jours) === > backfill_profond.txt
python tools\backfill_candles.py --jours 60 --intervalle 15m >> backfill_profond.txt 2>&1
echo. >> backfill_profond.txt
echo === 1h (visee : ~200 jours) === >> backfill_profond.txt
python tools\backfill_candles.py --jours 240 --intervalle 1h >> backfill_profond.txt 2>&1
exit /b 0
