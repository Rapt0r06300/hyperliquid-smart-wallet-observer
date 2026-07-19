@echo off
REM ============================================================================
REM  COMPARER LE FUNDING HYPERLIQUID vs BINANCE (2e venue) -- LECTURE SEULE.
REM  Liste les carries cross-venue candidats. 0 cle, 0 ordre, aucune execution.
REM  Hyperliquid reste la seule venue des decisions paper.
REM ============================================================================
cd /d "%~dp0.."
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
python tools\comparer_funding_venues.py --coins HYPE,PURR,BTC,ETH,SOL,AZTEC
echo.
pause
