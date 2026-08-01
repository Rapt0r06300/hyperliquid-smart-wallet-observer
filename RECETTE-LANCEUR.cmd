@echo off
setlocal
cd /d "%~dp0"
REM ============================================================================
REM  RECETTE E2E DU LANCEUR (item 13) — verification LIVE sur Windows.
REM  A lancer APRES avoir demarre LANCER_HYPERSMART.cmd (laisse-le tourner ~1-2 min
REM  pour que les collecteurs produisent des heartbeats et de vrais evenements).
REM  Strictement lecture seule : 0 ordre, 0 cle, 0 signature, aucun endpoint d'execution reelle.
REM ============================================================================
call "%~dp0tools\portable_env.cmd" 1>nul 2>nul
set "PYTHONPATH=%~dp0src;%~dp0tools;%PYTHONPATH%"
echo.
echo   === RECETTE E2E : verification de l'etat reel du lanceur ===
echo.
REM 1) Verdict compose : preflight + preuve de vie + registre PID + zero orphelin + paper strict.
python -m hl_observer.ops.recette_lanceur "%~dp0."
set "CODE=%ERRORLEVEL%"
echo.
if "%CODE%"=="0" (
  echo   [RECETTE] PASS : le lanceur recolte reellement, prouve chaque flux, reste paper strict.
) else (
  echo   [RECETTE] FAIL : voir les lignes ECHEC ci-dessus (source non prouvee, orphelin, ou preflight NO-GO^).
)
echo.
echo   --- Verification MANUELLE de la relance apres panne (recovery^) ---
echo   1. Ouvre le Gestionnaire des taches, repere un collecteur (ex. boucle_collecteur.cmd bbo-collector^).
echo   2. Termine-le. Attends ~30-60 s : le superviseur du lanceur doit le RELANCER tout seul.
echo   3. Relance cette recette : la preuve de vie doit repasser READY (le flux tue est revenu^).
echo   4. Pour un arret propre + zero orphelin : dans la fenetre du lanceur, tape Q puis Entree,
echo      ou lance :  python -m hl_observer.ops.registre_pids arreter "%~dp0."
echo.
pause
endlocal
exit /b %CODE%
