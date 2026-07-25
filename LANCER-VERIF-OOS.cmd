@echo off
REM ============================================================================
REM  Runner du VERIFICATEUR OOS SHADOW — 100%% LOCAL, LECTURE SEULE.
REM  Lance par le Planificateur de taches Windows toutes les 30 min.
REM  Ne lit que des fichiers locaux, met a jour status.json et cree la sentinelle
REM  CHECKPOINT_OOS_ATTEINT.txt une seule fois quand B atteint 30.
REM  AUCUN modele Claude, AUCUN appel API, AUCUN reseau, AUCUNE modif du runtime.
REM ============================================================================
cd /d "%~dp0"
if not exist "runtime\rapports\checkpoint_oos_shadow" mkdir "runtime\rapports\checkpoint_oos_shadow"
python tools\verif_checkpoint_oos_shadow.py >> "runtime\rapports\checkpoint_oos_shadow\verif.log" 2>&1
