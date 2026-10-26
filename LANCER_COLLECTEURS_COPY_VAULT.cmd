@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || (
  echo [ERREUR] Impossible d'ouvrir le depot local.
  pause
  exit /b 2
)
chcp 65001 >nul

set "CV_PYTHON="
set "CV_PY_ARGS="
if exist "%~dp0tools\python\python.exe" set "CV_PYTHON=%~dp0tools\python\python.exe"
if not defined CV_PYTHON if exist "%~dp0.venv\Scripts\python.exe" set "CV_PYTHON=%~dp0.venv\Scripts\python.exe"
if not defined CV_PYTHON (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "CV_PYTHON=py"
    set "CV_PY_ARGS=-3"
  )
)
if not defined CV_PYTHON goto :python_missing

"%CV_PYTHON%" %CV_PY_ARGS% -c "import httpx, websockets" >nul 2>nul
if errorlevel 1 goto :dependencies_missing

set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "REAL_MAINNET_TRADING=false"
set "TESTNET_ONLY=true"
set "HYPERSMART_EXPERIMENTAL_PAPER=0"
set "PYTHONPATH=%~dp0src;%~dp0tools;%PYTHONPATH%"

echo.
echo ================================================================
echo   ALINA SMART FLOW - COLLECTE COPY-VAULT
echo   Sources observees : fills leaders, vaults, L2/BBO, prix et backfills
echo   Checkpoints causaux : ecriture dediee sous bail de campagne
echo   Replay historique : seuls les shards valides SAFE sont admissibles
echo   Les observations locales restent brutes jusqu'a validation/admission SAFE
echo   Duree : campagnes de 6 jours, renouvelees automatiquement
echo   Arret : Ctrl+C; workers crees sous bail arretes sous 120 s max
echo   Les collecteurs deja geres par LANCER_HYPERSMART restent sous son controle
echo   Moteur principal / paper experimental : non demarres
echo   Ordres : aucun ^| execution mainnet/testnet : desactivee
echo   Journal : runtime\logs\economic-collector-watchdog.jsonl
echo ================================================================
echo.

:campagne
"%CV_PYTHON%" %CV_PY_ARGS% "%~dp0tools\watch_economic_collectors.py" --root "%~dp0." --profile copy-vault --interval-s 30 --duration-s 518400 --lease-duration-s 120
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" goto :campagne

echo.
if "%RC%"=="130" (
  echo [ARRET] Interruption demandee. Le bail cesse d'etre renouvele; les workers lies s'arretent a son expiration ^(120 s max^).
) else (
  echo [ERREUR] Le superviseur a retourne le code %RC%. Consulte le journal indique ci-dessus.
)
echo.
pause
endlocal & exit /b %RC%

:python_missing
echo [ERREUR] Python 3 introuvable. Installe Python 3 ou le runtime embarque du depot.
set "RC=30"
pause
endlocal & exit /b %RC%

:dependencies_missing
echo [ERREUR] Dependances requises absentes : httpx et websockets.
echo Le lanceur n'installe rien automatiquement. Utilise l'environnement Python du labo.
set "RC=31"
pause
endlocal & exit /b %RC%
