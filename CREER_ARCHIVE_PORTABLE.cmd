@echo off
setlocal EnableExtensions
REM ============================================================
REM  CREER_ARCHIVE_PORTABLE.cmd   (items 20 & 22)
REM  Fabrique une archive PORTABLE de HyperSmart, puis LA RE-VERIFIE.
REM  Critere final : apres extraction sur un AUTRE PC Windows x64 compatible,
REM  double-clic LANCER_HYPERSMART.cmd -> recolte -> cloture -> double-clic
REM  ANALYSER_BACKTESTS_REPLAYS.cmd, SANS modifier aucun chemin ni installer
REM  Python/deps a la main.
REM  Automatique : preuve d'arret des writers, refus de toute session ACTIVE,
REM  checkpoint WAL des SQLite, exclusion PID/verrous/temporaires machine,
REM  conservation des sessions, neutralisation des chemins absolus, manifeste
REM  SHA-256 complet, archive versionnee, RE-VERIFICATION.
REM  PAPER STRICT : 0 ordre reel, 0 cle privee, 0 signature, aucun /exchange.
REM ============================================================
cd /d "%~dp0"
REM item 16 : MEME Python portable que le runtime, ERRORLEVEL verifie tout de suite, aucun repli systeme.
call "%~dp0tools\portable_env.cmd"
if errorlevel 1 (
  echo   [PYTHON] portable_env a echoue : aucun runtime Python portable valide. Abandon.
  endlocal & exit /b 30
)
if not defined HYPERSMART_PYTHON (
  echo   [PYTHON] HYPERSMART_PYTHON non defini par portable_env. Abandon.
  endlocal & exit /b 31
)
set "PYTHONPATH=%~dp0src;%~dp0tools"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "REAL_MAINNET_TRADING=false"
set "TESTNET_ONLY=true"

echo.
echo ============================================================
echo   ARCHIVE PORTABLE HyperSmart - paper strict (0 ordre reel)
echo ============================================================
echo.

REM item 20.2 : on tente d'abord de CLOTURER proprement la session courante (best-effort). Si un writer
REM est encore vivant, la cloture echoue (code 2) : on le SIGNALE, et l'archive refusera de toute facon.
echo   [1/2] Cloture propre de la session courante (si presente)...
"%HYPERSMART_PYTHON%" -m hl_observer.ops.session_harvest cloturer "%~dp0."
if errorlevel 1 (
  echo   [SESSION] La session courante n'a pas pu passer COMPLETE ^(writers encore actifs ?^).
  echo   Ferme d'abord LANCER_HYPERSMART.cmd proprement ^(touche Q^), puis relance cet outil.
)

echo.
echo   [2/2] Construction + re-verification de l'archive portable...
REM La version et le SHA git sont LUS par le module (VERSION + .git) ; sortie versionnee sous dist\.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.archive_portable --racine "%~dp0."
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo   [OK] Archive portable creee ET re-verifiee. Voir le dossier dist\.
  echo        Le manifeste PORTABLE_MANIFEST.json est embarque a la racine de l'archive.
) else if "%RC%"=="5" (
  echo   [REFUSE] Archive refusee : une session est ACTIVE ou un writer est encore vivant.
  echo            Ferme LANCER_HYPERSMART.cmd ^(touche Q^) pour cloturer la session, puis relance.
) else if "%RC%"=="4" (
  echo   [ECHEC] La re-verification de l'archive a echoue : NE PAS l'utiliser. Voir la sortie ci-dessus.
) else (
  echo   [ERREUR] Echec inattendu ^(code %RC%^). Voir la sortie ci-dessus.
)
echo.
pause
endlocal & exit /b %RC%
