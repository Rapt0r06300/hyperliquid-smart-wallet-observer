@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set PYTHONPATH=src
echo.
echo  ECOUTE DU FLUX PUBLIC HYPERLIQUID -- 4 heures (lecture seule, aucun ordre).
echo  Sous 30 min, aucun debit n est mesurable : le snapshot initial fausse tout.
echo  Ctrl-C a tout moment pour passer au verdict sur ce qui a ete capte.
echo.
python tools\mesurer_flux_market_making.py --minutes 240
echo.
pause
