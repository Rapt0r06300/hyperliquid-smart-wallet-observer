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

cls
echo ============================================================
echo   HYPERSMART - UTILISER LA BIBLIOTHEQUE FULL/COLD
echo   PAPER STRICT - AUCUN ORDRE REEL
echo ============================================================
echo.

echo [1/6] Verification de la Release privee...
"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_bridge status --root "%~dp0."
if errorlevel 1 goto :erreur

echo.
echo [2/6] Recuperation et verification des petits manifestes...
"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_bridge catalog --root "%~dp0."
if errorlevel 1 goto :erreur

echo.
echo [3/6] Construction de la carte des 150 000+ fichiers...
"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_catalog --root "%~dp0."
if errorlevel 1 goto :erreur

echo.
echo [4/6] Calcul du lot exact pour Copy-Vault + Lead-Lag + Cross-Venue...
"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_bridge prepare --root "%~dp0." --preset economic-core
if errorlevel 1 goto :erreur

echo.
echo ============================================================
echo   Le plan ci-dessus indique le vrai volume a telecharger.
echo   Chaque asset sera verifie par SHA-256.
echo   La progression sera affichee environ chaque seconde.
echo ============================================================
echo.
set /p "CONFIRM=Ecris OUI pour telecharger, reconstruire et lancer le replay : "
if /I not "%CONFIRM%"=="OUI" (
  echo.
  echo [ANNULE] Rien de lourd n'a ete telecharge.
  goto :fin_ok
)

echo.
echo [5/6] Telechargement et reconstruction du lot economique...
"%HYPERSMART_PYTHON%" -m hl_observer.ops.dataset_bridge prepare --root "%~dp0." --preset economic-core --download --max-download-gib 0 --heartbeat-seconds 1
if errorlevel 1 goto :erreur

echo.
echo [6/6] Replay des trois moteurs sur les donnees reconstruites...
call "%~dp0ANALYSER_DONNEES_HYPERSMART.cmd"
if errorlevel 1 goto :erreur

echo.
echo ============================================================
echo   TERMINE
echo ============================================================
echo   Petit rapport pret pour GitHub :
echo   docs\research\datasets\DERNIER_REPLAY_176GO.md
echo   docs\research\datasets\DERNIER_REPLAY_176GO.json
echo.
echo   Donnees lourdes : data\hypersmart_datasets\
echo   Elles restent ignorees par Git.
echo ============================================================
goto :fin_ok

:erreur
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" set "RC=1"
echo.
echo ============================================================
echo   NO_GO - une etape a echoue avec le code %RC%
echo   Rien n'est invente et aucun ordre reel n'a ete envoye.
echo ============================================================
if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
endlocal & exit /b %RC%

:fin_ok
if /I not "%HYPERSMART_NO_PAUSE%"=="1" pause
endlocal & exit /b 0
