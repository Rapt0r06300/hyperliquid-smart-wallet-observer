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
echo  [2/2] Recherche de scenario (deux moities + stress + plateau)...
python -c "import json;from hl_observer.backtesting.recherche_scenario import chercher;r=chercher('.');print(json.dumps({k:v for k,v in r.items() if k!='essais'},ensure_ascii=False,indent=1));print();print('essais juges :',r.get('n_essais_total'));print('etat/reprise : runtime\\replay\\recherche_scenario_etat.json')"
echo.
pause
