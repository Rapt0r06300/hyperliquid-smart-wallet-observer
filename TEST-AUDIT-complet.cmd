@echo off
REM ==================================================================
REM   AUDIT COMPLET HYPERSMART  --  double-clique ou lance-le d'ici
REM
REM   33 controles : syntaxe, imports, imports circulaires, signatures,
REM   code mort, exceptions avalees, aleatoire non seede, coherence de
REM   la config, reglages morts, planchers fail-open, secrets, execution
REM   reelle, securite, tests non isoles, tests sans assertion, tests
REM   desactives, reseau dans les tests, doublons, modules orphelins,
REM   dettes, multiprocessing, codes de refus, modules sans test, docs,
REM   ressources, lint, typage, reconciliation PnL, SUITE DE TESTS,
REM   couverture fichier par fichier, tests flaky, doctor.
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
