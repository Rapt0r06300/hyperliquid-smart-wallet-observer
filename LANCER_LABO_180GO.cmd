@echo off
setlocal EnableExtensions
cd /d "%~dp0"

call "%~dp0tools\portable_env.cmd"
if errorlevel 1 (
  echo [ERREUR] Python portable introuvable.
  pause
  exit /b 30
)

set "PYTHONPATH=%~dp0src;%~dp0tools"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "REAL_MAINNET_TRADING=false"
set "TESTNET_ONLY=true"
set "HYPERSMART_ANALYSIS_LOCAL_ONLY=1"

if /I "%~1"=="plans" goto :plans
if not "%~1"=="" (
  set "SUITE=%~1"
  goto :suite
)

:menu
cls
echo ============================================================
echo   ALINA SMARTFLOW - LABORATOIRE DES ~180 GO
echo   FULL/COLD PRIVE - CACHE PARTAGE - WORKSPACES ISOLES
echo   PAPER STRICT - AUCUN ORDRE REEL
echo ============================================================
echo.
echo   1. Voir le plan de toute la bibliotheque
echo   2. economic-core       ^(controle rapide des 3 moteurs^)
echo   3. economic-full       ^(toutes les donnees Copy+Lead+Cross^)
echo   4. copy-vault-full     ^(famille Copy-Vault complete^)
echo   5. lead-lag-full       ^(famille Lead-Lag complete^)
echo   6. cross-venue-full    ^(famille Cross-Venue complete^)
echo   7. microstructure-full ^(L2, depth, bid/ask, carnets^)
echo   8. research-lab-full   ^(replays, backtests, historiques, scenarios^)
echo   9. full-archive        ^(archive complete ~180 Go^)
echo   0. Quitter
echo.
set /p "CHOIX=Choix : "

if "%CHOIX%"=="1" goto :plans
if "%CHOIX%"=="2" set "SUITE=economic-core"
if "%CHOIX%"=="3" set "SUITE=economic-full"
if "%CHOIX%"=="4" set "SUITE=copy-vault-full"
if "%CHOIX%"=="5" set "SUITE=lead-lag-full"
if "%CHOIX%"=="6" set "SUITE=cross-venue-full"
if "%CHOIX%"=="7" set "SUITE=microstructure-full"
if "%CHOIX%"=="8" set "SUITE=research-lab-full"
if "%CHOIX%"=="9" set "SUITE=full-archive"
if "%CHOIX%"=="0" goto :fin_ok
if not defined SUITE goto :menu
goto :suite

:plans
echo.
echo [PLAN] Lecture des manifestes et calcul de TOUTES les suites...
"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_bridge plan-all --root "%~dp0."
if errorlevel 1 goto :erreur
echo.
echo Rapports :
echo   runtime\reports\datasets\BIBLIOTHEQUE_180GO.md
echo   runtime\reports\datasets\BIBLIOTHEQUE_180GO.json
if not "%~1"=="" goto :fin_ok
pause
goto :menu

:suite
echo.
echo ============================================================
echo   SUITE SELECTIONNEE : %SUITE%
echo ============================================================
echo.
echo [1/3] Calcul exact des fichiers, assets, cache et volume restant...
"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_bridge prepare --root "%~dp0." --suite "%SUITE%"
if errorlevel 1 goto :erreur

echo.
echo Le plan ci-dessus est un APERCU : rien de lourd n'a encore ete telecharge.
echo Les assets deja presents dans le cache commun seront reutilises.
echo Chaque asset recupere sera controle avant reconstruction.
echo Le workspace de cette suite sera isole par un digest de selection.
echo.
set /p "CONFIRM=Ecris OUI pour telecharger/reutiliser le cache et reconstruire cette suite : "
if /I not "%CONFIRM%"=="OUI" (
  echo [ANNULE] Aucun gros telechargement lance.
  goto :fin_ok
)

if /I "%SUITE%"=="full-archive" (
  echo.
  echo ATTENTION : cette option peut demander presque toute l'archive FULL/COLD.
  set /p "CONFIRM_ALL=Ecris TOUT pour confirmer l'archive complete : "
  if /I not "%CONFIRM_ALL%"=="TOUT" (
    echo [ANNULE] Archive complete non telechargee.
    goto :fin_ok
  )
)

echo.
echo [2/3] Telechargement avec progression + reconstruction isolee...
"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_bridge prepare --root "%~dp0." --suite "%SUITE%" --download --max-download-gib 0 --heartbeat-seconds 1
if errorlevel 1 goto :erreur

echo.
echo [3/3] Suite reliee au projet principal.
echo.
if /I "%SUITE%"=="economic-core" goto :replay_eco
if /I "%SUITE%"=="economic-full" goto :replay_eco

echo Cette suite est maintenant disponible dans son workspace isole.
echo Elle alimente les recherches ciblees et les futurs replays dedies.
echo Pour les trois moteurs economiques ensemble, utilise economic-full.
goto :fin_ok

:replay_eco
echo Lancement du replay canonique Copy-Vault + Lead-Lag + Cross-Venue...
call "%~dp0ANALYSER_DONNEES_HYPERSMART.cmd" "%SUITE%"
if errorlevel 1 goto :erreur
echo.
echo [OK] Replay termine. Le verdict compact est dans :
echo   docs\research\datasets\DERNIER_REPLAY_DATASETS.md
echo   docs\research\datasets\DERNIER_REPLAY_DATASETS.json
goto :fin_ok

:erreur
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" set "RC=1"
echo.
echo ============================================================
echo   NO_GO - code %RC%
echo   Aucune donnee absente n'est inventee.
echo   Aucun ordre reel n'a ete envoye.
echo ============================================================
if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
endlocal & exit /b %RC%

:fin_ok
if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
endlocal & exit /b 0
