@echo off
REM Teste UNIQUEMENT l'affichage de l'alerte (fenetre + son systeme).
REM Ne cree AUCUNE sentinelle et NE MODIFIE AUCUN compteur reel.
cd /d "%~dp0"
echo ============================================================
echo  TEST NOTIFICATION OOS  (fenetre + son, aucun effet de bord)
echo ============================================================
echo Dossier : %CD%
where python
echo.
echo Lancement de --test-notification ...
python tools\verif_checkpoint_oos_shadow.py --test-notification
echo.
echo Code de sortie python : %ERRORLEVEL%
echo (Si une fenetre "HyperSmart (test)" est apparue et que tu as entendu le son, c'est OK.)
echo.
pause
