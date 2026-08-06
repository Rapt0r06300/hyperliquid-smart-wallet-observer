@echo off
setlocal EnableExtensions
REM ============================================================
REM  ANALYSER_BACKTESTS_REPLAYS.cmd
REM  Analyse EXCLUSIVEMENT la derniere session COMPLETE cataloguee (jamais un scan global de la racine).
REM  Selection+verification (checksums) -> laboratoire scope a CETTE session -> rapport neuf namespace.
REM  PAPER STRICT : 0 ordre reel, 0 cle privee, 0 signature, aucun /exchange.
REM ============================================================
cd /d "%~dp0"
REM item 6 : MEME Python que le runtime (portable), ERRORLEVEL verifie IMMEDIATEMENT, aucun repli systeme.
call "%~dp0tools\portable_env.cmd"
if errorlevel 1 (
  echo   [PYTHON] portable_env a echoue : aucun runtime Python portable valide. Abandon.
  if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
  endlocal & exit /b 30
)
if not defined HYPERSMART_PYTHON (
  echo   [PYTHON] HYPERSMART_PYTHON non defini par portable_env. Abandon.
  if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
  endlocal & exit /b 31
)
call "%~dp0tools\hyperlab_env.cmd"

REM Smoke portable borne, non interactif : utilise exclusivement Python embarque.
if /I "%~1"=="portable-smoke" goto :portable_smoke
goto :analyse_principale

:portable_smoke
"%HYPERSMART_PYTHON%" -m hl_observer.ops.portable_smoke --root "%~dp0." --json
set "RC=%ERRORLEVEL%"
endlocal & exit /b %RC%

:analyse_principale

echo.
echo ============================================================
echo   LABORATOIRE ALPHA - paper strict (0 ordre reel)
echo   Analyse d'UNE session COMPLETE, verifiee, isolee.
echo ============================================================
echo.

REM item 11 : SEUIL DE FRAICHEUR configurable. Par defaut, une session de plus de 48 h est refusee
REM clairement (donnee trop vieille = analyse trompeuse). Surchargeable via HYPERSMART_AGE_MAX_S
REM (0 ou vide = pas de limite d'age ; ex. 3600 = 1 h). --autoriser-complete-ancienne leve le refus.
if "%HYPERSMART_AGE_MAX_S%"=="" set "HYPERSMART_AGE_MAX_S=172800"
set "OPT_AGE="
if not "%HYPERSMART_AGE_MAX_S%"=="0" set "OPT_AGE=--age-max-s %HYPERSMART_AGE_MAX_S%"
REM item 2 : PORTE D'ENTREE — selectionne la DERNIERE session COMPLETE, RECALCULE les checksums, refuse
REM ACTIVE/QUARANTINED, et EMET le run_id selectionne (SESSION_SELECTIONNEE.txt) pour scoper le lab.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.analyser_session --root "%~dp0." --emit-run-id %OPT_AGE%
if errorlevel 1 (
  echo.
  echo   [ANALYSE_SESSION] NO_GO : aucune session COMPLETE FRAICHE a analyser ^(voir la raison exacte ci-dessus^).
  echo   - Aucune/again : lance LANCER_HYPERSMART.cmd, collecte, puis arrete-le proprement ^(session COMPLETE^).
  echo   - Session trop VIEILLE ^(seuil actuel %HYPERSMART_AGE_MAX_S% s^) : recolte a nouveau, ou releve le seuil
  echo     via HYPERSMART_AGE_MAX_S ^(0 = pas de limite^), ou passe --autoriser-complete-ancienne.
  echo   Detail : runtime\reports\backtest_replay\ANALYSE_SESSION.md
  echo.
  pause
  endlocal & exit /b 5
)
set "SEL=%~dp0runtime\reports\backtest_replay\SESSION_SELECTIONNEE.txt"
if not exist "%SEL%" (
  echo   [ANALYSE_SESSION] run_id selectionne introuvable. Abandon.
  echo   ^(selection reussie mais le pointeur SESSION_SELECTIONNEE.txt n'a pas ete ecrit^)
  if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
  endlocal & exit /b 6
)
set "RUN_ID="
set /p RUN_ID=<"%SEL%"
if "%RUN_ID%"=="" (
  echo   [ANALYSE_SESSION] run_id vide. Abandon.
  if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
  endlocal & exit /b 6
)
set "SESSION_DIR=%~dp0runtime\data\sessions\%RUN_ID%"
echo   [ANALYSE_SESSION] GO : session COMPLETE = %RUN_ID%. Analyse EXCLUSIVE de ses artefacts verifies.
echo.

REM Budget MAXIMAL par defaut (item 11) : --budget 0 = grille entiere. Surchargeable HYPERSMART_LAB_BUDGET.
if "%HYPERSMART_LAB_BUDGET%"=="" set "HYPERSMART_LAB_BUDGET=0"
REM item 6 : fenetre RAM du replay TOUJOURS bornee. 0 (defaut) = budget AUTOMATIQUE borne calcule sur
REM la RAM disponible (jamais illimite, jamais d'OOM) ; une valeur > 0 impose un plafond explicite.
if "%HYPERSMART_MAX_RAM_EVENTS%"=="" set "HYPERSMART_MAX_RAM_EVENTS=0"
"%HYPERSMART_PYTHON%" -m hl_observer.ops.lab_alpha --root "%~dp0." --session-dir "%SESSION_DIR%" ^
   --source REEL --budget %HYPERSMART_LAB_BUDGET% --max-ram-events %HYPERSMART_MAX_RAM_EVENTS%
set "RC=%ERRORLEVEL%"

REM item 6 : si le run COURANT a echoue, on N'OUVRE JAMAIS un ancien rapport. On propage le code.
if not "%RC%"=="0" (
  echo.
  echo   [LAB] Le run a ECHOUE ^(code %RC%^). Aucun ancien rapport n'est ouvert. Voir le journal :
  echo   runtime\reports\backtest_replay\%RUN_ID%\journal_lab.log
  echo.
  pause
  endlocal & exit /b %RC%
)
set "RAP=%~dp0runtime\reports\backtest_replay\%RUN_ID%\RAPPORT_LATEST.md"
if exist "%RAP%" (
  echo.
  echo   Rapport NEUF de cette session : "%RAP%"
  start "" "%RAP%"
) else (
  echo   ATTENTION: rapport du run courant introuvable. Voir runtime\reports\backtest_replay\%RUN_ID%\journal_lab.log
  set "RC=7"
)
echo.
echo Termine (code %RC%). Appuyez sur une touche pour fermer.
pause >nul
endlocal & exit /b %RC%
