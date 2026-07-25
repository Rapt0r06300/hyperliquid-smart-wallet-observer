@echo off
REM ==================================================================
REM   AUDIT COMPLET HYPERSMART  --  double-clique ou lance-le d'ici
REM
REM   ~180 controles : syntaxe, imports, circulaires, signatures, code
REM   mort, exceptions avalees, aleatoire non seede, coherence config,
REM   reglages morts, planchers fail-open, secrets, execution reelle,
REM   securite, tests non isoles/sans assertion/desactives, reseau dans
REM   les tests, doublons, orphelins, dettes, multiprocessing, codes de
REM   refus, modules sans test, docs, ressources, lint, typage,
REM   reconciliation PnL, sante economique, verite des donnees, fuzzing,
REM   SUITE DE TESTS, couverture, flaky, doctor.
REM
REM   + LECONS DES 18-19/07 (nouveaux, tools\audit_controles_sup.py) :
REM     - unites : cumul multi-jours deguise en taux _24h_ (le bug x30)
REM     - interrupteurs du lanceur : valeurs sures + coherence superviseur
REM     - provenance : le panneau HL ne peut pas lire le moteur dYdX
REM     - UI honnete : pas de '>=1' rassurant quand la mesure manque
REM     - sante runtime (photo NON bloquante) : collecteurs, inputs, ledger
REM
REM   -> Ecrit "resultat-audit.md" a la racine : envoie-le a Claude.
REM
REM   Options :   ci_local.cmd --fast    (saute la 2e passe anti-flaky)
REM
REM   100%% LECTURE SEULE. Aucun ordre reel, aucun argent reel.
REM ==================================================================
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"

echo.
echo   Lancement de l'audit...
echo.
REM Outils qui rendent l'audit ROBUSTE (best effort, sans reseau ca passe quand meme) :
REM  - pytest-timeout : un test bloque est tue et signale, au lieu de figer l'audit
REM  - coverage       : couverture reelle fichier par fichier
python -m pip install -q pytest-timeout coverage 2>nul

python tools\audit_report.py %*
set "AUDIT_CODE=%ERRORLEVEL%"

echo.
if exist "resultat-audit.md" (
  echo Rapport ecrit : %~dp0resultat-audit.md
) else (
  echo ATTENTION : le rapport n'a pas ete ecrit.
)

if "%AUDIT_CODE%"=="0" (
  echo.
  echo   ============================================
  echo     TOUT EST VERT. Commit autorise.
  echo   ============================================
) else (
  echo.
  echo   ############################################
  echo     ECHECS DETECTES - NE PAS COMMITER
  echo     Envoie resultat-audit.md a Claude.
  echo   ############################################
)

echo.
pause
exit /b %AUDIT_CODE%
