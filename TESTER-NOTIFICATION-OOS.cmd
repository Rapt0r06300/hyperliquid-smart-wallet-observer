@echo off
REM Teste UNIQUEMENT l'affichage de l'alerte (fenetre + son systeme).
REM Ne cree AUCUNE sentinelle et NE MODIFIE AUCUN compteur reel.
cd /d "%~dp0"
python tools\verif_checkpoint_oos_shadow.py --test-notification
