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

if "%~1"=="" goto :menu
if /I "%~1"=="status" goto :status
if /I "%~1"=="catalog" goto :catalog
if /I "%~1"=="carte" goto :carte
if /I "%~1"=="copy-vault" goto :copy
if /I "%~1"=="lead-lag" goto :leadlag
if /I "%~1"=="cross-venue" goto :cross
if /I "%~1"=="moteurs" goto :moteurs
if /I "%~1"=="moteurs-download" goto :moteurs_download
if /I "%~1"=="tout" goto :tout

echo [ERREUR] Choix inconnu: %~1
goto :usage

:menu
echo.
echo ============================================================
echo   DONNEES HYPERSMART - BIBLIOTHEQUE FULL/COLD
echo ============================================================
echo   1 - Verifier que la grosse Release est accessible
echo   2 - Recuperer seulement les petits manifestes
echo   3 - Faire la carte complete des 150 000+ fichiers
echo   4 - Voir le plan Copy-Vault sans telecharger
echo   5 - Voir le plan Lead-Lag sans telecharger
echo   6 - Voir le plan Cross-Venue sans telecharger
echo   7 - Voir le lot exact pour les 3 moteurs sans telecharger
echo   8 - Telecharger et reconstruire le lot exact pour les 3 moteurs
echo.
set /p "CHOIX=Choix : "
if "%CHOIX%"=="1" goto :status
if "%CHOIX%"=="2" goto :catalog
if "%CHOIX%"=="3" goto :carte
if "%CHOIX%"=="4" goto :copy
if "%CHOIX%"=="5" goto :leadlag
if "%CHOIX%"=="6" goto :cross
if "%CHOIX%"=="7" goto :moteurs
if "%CHOIX%"=="8" goto :moteurs_download
echo Choix invalide.
pause
exit /b 2

:status
"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_bridge status --root "%~dp0."
goto :fin

:catalog
"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_bridge catalog --root "%~dp0."
goto :fin

:carte
"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_catalog --root "%~dp0."
goto :fin

:copy
"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_bridge prepare --root "%~dp0." --family copy-vault
goto :fin

:leadlag
"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_bridge prepare --root "%~dp0." --family lead-lag
goto :fin

:cross
"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_bridge prepare --root "%~dp0." --family cross-venue
goto :fin

:moteurs
"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_bridge prepare --root "%~dp0." --preset economic-core
goto :fin

:moteurs_download
echo.
echo ATTENTION : cette etape telecharge les assets GitHub qui contiennent les donnees
 echo necessaires a Copy-Vault, Lead-Lag et Cross-Venue. Les SHA-256 seront verifies.
set /p "CONFIRM=Ecris OUI pour continuer : "
if /I not "%CONFIRM%"=="OUI" (
  echo Annule. Rien n'a ete telecharge.
  goto :fin_ok
)
"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_bridge prepare --root "%~dp0." --preset economic-core --download --max-download-gib 0
goto :fin

:tout
"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_bridge prepare --root "%~dp0." --max-download-gib 0
goto :fin

:usage
echo Usage: PREPARER_DONNEES_HYPERSMART.cmd [status^|catalog^|carte^|copy-vault^|lead-lag^|cross-venue^|moteurs^|moteurs-download^|tout]
exit /b 2

:fin_ok
set "RC=0"
goto :affiche_fin

:fin
set "RC=%ERRORLEVEL%"

:affiche_fin
echo.
if "%RC%"=="0" (
  echo [OK] Operation terminee.
) else (
  echo [ERREUR] Operation echouee avec le code %RC%.
)
if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
endlocal & exit /b %RC%
