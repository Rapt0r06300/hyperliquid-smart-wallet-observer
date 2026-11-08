@echo off
chcp 65001 >nul
title Collecte Hyperliquid - TEMPS REEL
cd /d "%~dp0"
set "PYTHONPATH=src"
echo Demarrage de l'affichage temps reel... (Ctrl+C pour quitter)
python "toolsffichage_temps_reel.py" --root "%~dp0."
pause
