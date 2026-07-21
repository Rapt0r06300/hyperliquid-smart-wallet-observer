@echo off
REM ============================================================================
REM  RECHERCHE DE PEPITES — le laboratoire du bot (21/07)
REM ============================================================================
REM  CE QU'IL FAIT, EN FRANCAIS SIMPLE :
REM
REM   [1/3] Il RASSEMBLE toutes les donnees enregistrees (candidats + prix),
REM         y compris les archives — rien n'est jamais perdu.
REM
REM   [2/3] Il CHERCHE, module par module (jamais melanges) :
REM           - carry        : ~600 reglages SL/TP/horizon x 4 sous-populations
REM           - copywallet   : idem, sur les 262 000+ signaux enregistres
REM           - arbitrage    : idem, sur ce qui existe
REM           - cross-venue  : ses propres seuils de dispersion (4 jambes)
REM         Methodes : crible multi-fidelite (successive halving), grille large,
REM         raffinage grossier->fin, folds purges CPCV (rang OR/ARGENT),
REM         portes anti-mensonge (2 moities+embargo, couts x1,5, plateau).
REM
REM   [3/3] Il ECRIT les rapports et DIT quoi faire :
REM           runtime\replay\RESULTATS_RECHERCHE.md  <- LE fichier a envoyer a Claude
REM           runtime\replay\PEPITES.md              <- le resume court
REM         Et il termine par : « FAIS CA avec le carry... / ARRETE de chercher
REM         ici... / PATIENCE... » — une phrase par module.
REM
REM  BON A SAVOIR :
REM   - Ctrl-C = PAUSE SANS PERTE : tout essai juge est sauvegarde ; a la
REM     prochaine ouverture il reprend exactement ou il en etait.
REM   - Ca peut durer des heures (copywallet surtout). C'est normal : chaque
REM     ligne « essai N » a l'ecran = un reglage juge honnetement.
REM   - Une PEPITE n'est PAS une promesse de gain : c'est un reglage qui a
REM     SURVECU a toutes les portes — il devra encore le prouver en paper.
REM   - 100%% lecture seule. 0 ordre reel, 0 cle, 0 signature.
REM ============================================================================
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"

echo.
echo  [1/4] Rassemblement de toutes les donnees (candidats + prix, archives incluses)...
python -m hl_observer.runtime.replay_recorder --base runtime\replay
echo.
echo  [2/4] Audit QUALITE des donnees (un replay ne vaut jamais mieux que ses donnees)...
python tools\qualite_donnees_replay.py .
echo.
echo  [3/4] Recherche module par module (Ctrl-C = pause sans perte, reprise auto)...
echo.
python -c "from hl_observer.backtesting.recherche_scenario import chercher_toutes; chercher_toutes('.')"
echo.
echo  [4/4] Verification des rapports :
if not exist "runtime\replay\RESULTATS_RECHERCHE.md" (
  echo   !! AUCUN RAPPORT : un module a plante avant la fin. Envoie CETTE fenetre a Claude.
) else (
  echo   Rapports ecrits :
)
echo         - runtime\replay\RESULTATS_RECHERCHE.md  ^(a envoyer a Claude^)
echo         - runtime\replay\PEPITES.md              ^(resume court^)
echo         - runtime\replay\QUALITE_DONNEES.md      ^(sante des donnees^)
echo.
pause
