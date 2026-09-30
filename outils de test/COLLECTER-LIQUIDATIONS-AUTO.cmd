@echo off
REM ============================================================================
REM  COLLECTEUR DE LIQUIDATIONS — sans lui, la mesure #3 est impossible A JAMAIS
REM ============================================================================
REM  Constat du 19/07 : "snapshots": 0 -> AUCUN_HISTORIQUE_LA_MESURE_EST_IMPOSSIBLE.
REM  Le message disait "laisse tourner plus longtemps". C'etait un MAUVAIS conseil :
REM  rien n'ecrivait ces donnees. On pouvait attendre un mois, toujours 0.
REM
REM  Ce collecteur lit 3 endpoints PUBLICS (leaderboard, clearinghouseState,
REM  allMids), construit la carte des liquidations avec les modules EXISTANTS et
REM  la persiste dans runtime\data\liquidation_map.sqlite3. Toutes les 5 min.
REM  Lance AUTOMATIQUEMENT par LANCER_HYPERSMART.cmd.
REM
REM  Securite : lecture seule. 0 ordre, 0 cle, 0 signature. Observer ou d'autres
REM  seront liquides n'est pas prendre une position.
REM ============================================================================
cd /d "%~dp0.."
title Collecteur de liquidations (mesure #3)
set "PYTHONPATH=%~dp0src"
python tools\collecter_liquidations.py --root "%~dp0..\." --intervalle 300
echo.
echo Le collecteur s'est arrete. Appuyez sur une touche pour fermer.
pause >nul
