@echo off
REM ============================================================================
REM  VERIFIER LA SANTE DES DONNEES avant tout replay A/B ou mesure.
REM
REM  Le replay A/B ne vaut RIEN sur des donnees insuffisantes (c'est ce qui avait
REM  produit le faux "1 sur 1M"). Ce script dit, honnetement, si on a assez de
REM  donnees pour conclure -- SANS rien lancer d'autre. 100%% lecture seule.
REM ============================================================================
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"

echo.
echo === SANTE DU REPLAY (candidats + marks agreges depuis TOUS les shards) ===
python -c "from hl_observer.backtesting.replay_doctor import diagnostiquer_base, format_rapport; print(format_rapport(diagnostiquer_base('runtime/replay')))"

echo.
echo === HISTORIQUE DES LIQUIDATIONS (pour la mesure #3) ===
python -m hl_observer.market.liquidation_recorder --root .

echo.
echo === VERDICT MESURE #3 (edge post-liquidation, si assez de donnees) ===
python tools\mesurer_edge_liquidation.py --root .

echo.
echo Regle dure : tant que c'est INSUFFISANT, on NE conclut PAS -- on laisse le bot
echo tourner plus longtemps (voir docs\RUNBOOK_COLLECTE_DONNEES.md).
echo.
pause
