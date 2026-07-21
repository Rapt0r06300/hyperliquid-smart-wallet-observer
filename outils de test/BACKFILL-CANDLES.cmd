@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   BACKFILL D'HISTORIQUE -- « data-limited » etait une blessure AUTO-INFLIGEE.
REM
REM   `candleSnapshot(coin, interval, startTime, endTime)` etait DEJA ecrit, DEJA
REM   autorise -- et on ne s'en servait que pour les bougies RECENTES.
REM   On telecharge donc 30 JOURS d'historique de prix. Gratuitement.
REM
REM   Avant : 18,9 h.  Apres : ~720 h.
REM
REM   Aucun ordre reel. Lecture publique seule (endpoint /info).
REM   ASCII PUR, pas de pause -> "%~dp0rapports\backfill.txt"
REM ==================================================================================
python tools\backfill_candles.py --jours 30 --intervalle 1m > "%~dp0rapports\backfill.txt" 2>&1
exit /b 0
