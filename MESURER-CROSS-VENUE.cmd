@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   #365 / H-137 -- FUNDING CROSS-VENUE, SUR LE **MEME COIN**.
REM
REM   X-04 a tue le perp<->perp entre coins DIFFERENTS (0/120).
REM   La loi qui en sort : UNE COUVERTURE NE VAUT QUE SI C'EST LE MEME ACTIF.
REM   -> HL perp <-> Binance perp sur le MEME coin obeit a cette loi.
REM
REM   Hyperliquid nous donne le funding de Binance et Bybit via {"type":"predictedFundings"}.
REM
REM   ⚠️ ON NE PEUT PAS TRADER SUR BINANCE. Cet outil MESURE, il ne capture rien.
REM
REM   Lecture seule. Aucun ordre. Aucune cle. Aucune signature.
REM   ASCII PUR, pas de pause -> funding_cross_venue.txt
REM ==================================================================================
python tools\mesurer_funding_cross_venue.py > funding_cross_venue.txt 2>&1
exit /b 0
