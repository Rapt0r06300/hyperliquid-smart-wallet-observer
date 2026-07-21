@echo off
REM ============================================================================
REM  RECHERCHE DE SCENARIO (replay A/B optimise) — 20/07
REM ============================================================================
REM  Grille SL/TP/horizon -> chaque config jugee sur DEUX moities temporelles
REM  disjointes (embargo anti-fuite) + stress des couts x1,5 + PLATEAU des
REM  voisins (un pic isole n'est jamais promu). Donnees chargees UNE fois.
REM  Reprise possible : l'etat survit dans runtime\replay\recherche_scenario_etat.json
REM  (supprime ce fichier pour repartir de zero).
REM
REM  Ne touche PAS a la session en cours (lecture seule des shards consolides).
REM  REPLAY-only : aucun ordre, aucune promesse — un verdict aux barres ecrites.
REM ============================================================================
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
REM 21/07 — CONSOLIDER D'ABORD, TOUJOURS : les consolides vivaient a 41 h d'age pendant que
REM les shards frais s'empilaient a cote. La recherche merite les donnees d'AUJOURD'HUI.
echo  [1/2] Consolidation des shards (candidats + marks, historique inclus)...
python -m hl_observer.runtime.replay_recorder --base runtime\replay
echo.
echo  [2/2] Recherche de PEPITES — TOUS les modules (carry, copy, arbitrage, cross-venue)...
echo        grille LARGE, portes inchangees (2 moities + stress x1,5 + plateau), 1 etat/module
python -c "import json;from hl_observer.backtesting.recherche_scenario import chercher_toutes;r=chercher_toutes('.');print();print(json.dumps({s:{k:v for k,v in x.items() if k!='essais'} for s,x in r.items()},ensure_ascii=False,indent=1));print();print('>>> rapport : runtime\\replay\\PEPITES.md')"
echo.
pause
