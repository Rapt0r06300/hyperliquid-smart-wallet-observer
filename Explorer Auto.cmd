@echo off
chcp 65001 >nul
title Explorer AUTONOME (auto-decouverte + inference) - PAPER
cd /d "%~dp0"
set "PYTHONPATH=src"
echo.
echo ============================================================
echo   EXPLORER AUTONOME
echo   - tourne seul, se repare seul, decouvre + infere seul
echo   - PAPER / lecture seule (aucune cle, aucun ordre)
echo   - laisse cette fenetre ouverte ; Ctrl+C pour arreter
echo ============================================================
echo.
:boucle
python "tools\explorer_autonome.py" --root "%~dp0."
echo.
echo [auto] processus termine de maniere inattendue - relance dans 10s (Ctrl+C pour stopper).
timeout /t 10 >nul
goto boucle
