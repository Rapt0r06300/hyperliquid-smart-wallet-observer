@echo off
REM ============================================================================
REM  COLLECTEUR DE MARKS — le prix futur sans lequel aucun replay ne mesure rien
REM ============================================================================
REM  Mesure du 19/07 : 30 148 candidats sur 106 coins, mais des marks sur 2 coins
REM  seulement -> 29 %% des candidats rejouables. BTC, ETH, SOL, ZEC avaient des
REM  candidats et AUCUN prix futur.
REM
REM  Ce collecteur lit `allMids` (endpoint PUBLIC /info, LECTURE SEULE) toutes les
REM  60 s et ecrit un mark par coin utile. Lance AUTOMATIQUEMENT par
REM  LANCER_HYPERSMART.cmd ; ce fichier sert a le relancer seul si besoin.
REM
REM  Securite : 0 ordre, 0 cle, 0 signature. Un prix observe n'est pas une position.
REM ============================================================================
cd /d "%~dp0"
title Collecteur de marks (replay)
set "PYTHONPATH=%~dp0src"
python tools\ecrire_marks_tous_coins.py --root "%~dp0." --intervalle 60
echo.
echo Le collecteur s'est arrete. Appuyez sur une touche pour fermer.
pause >nul
