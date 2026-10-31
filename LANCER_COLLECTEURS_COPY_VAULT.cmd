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
if not defined CV_PYTHON (
  where python >nul 2>nul
  if not errorlevel 1 set "CV_PYTHON=python"
)
if not defined CV_PYTHON goto :python_missing

"%CV_PYTHON%" %CV_PY_ARGS% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto :python_version

"%CV_PYTHON%" %CV_PY_ARGS% -c "import fastapi,httpx,numpy,pandas,psutil,pydantic,requests,rich,scipy,sqlalchemy,typer,uvicorn,websocket,websockets,yaml" >nul 2>nul
if errorlevel 1 goto :dependencies_missing

echo Python runtime valide : %CV_PYTHON% %CV_PY_ARGS%
"%CV_PYTHON%" %CV_PY_ARGS% --version
echo Dependances runtime verifiees; aucune installation ni collecte SAFE automatique.

set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "REAL_MAINNET_TRADING=false"
set "TESTNET_ONLY=true"
set "HYPERSMART_EXPERIMENTAL_PAPER=0"
set "PYTHONPATH=%~dp0src;%~dp0tools;%PYTHONPATH%"

echo.
echo ================================================================
echo   ALINA SMART FLOW - COLLECTE COPY-VAULT
echo   Wallets/fills leaders publics : Hyperliquid; marches publics : Hyperliquid, Binance, Bybit, OKX, Gate.io, Bitget
echo   Sources : vaults/fills, L2/BBO, trades/prix, checkpoints et backfills disponibles
echo   Donnees brutes : runtime\data; elles ne sont pas encore des preuves SAFE
echo   SAFE AlinaSync : runtime\recovery\full\usable\shards
echo   Le labo relit ces SAFE, verifie hashes puis cree son workspace par run
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

:python_version
echo [ERREUR] Python 3.11 ou plus recent est requis par le depot.
set "RC=32"
pause
endlocal & exit /b %RC%

:dependencies_missing
echo [ERREUR] Dependances runtime manquantes. Utilise le .venv du depot ou reinstalle les dependances de pyproject.toml.
echo Le lanceur n'installe rien automatiquement. Utilise l'environnement Python du labo.
set "RC=31"
pause
endlocal & exit /b %RC%
