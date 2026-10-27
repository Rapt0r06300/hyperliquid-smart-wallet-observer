@echo off
setlocal EnableExtensions
cd /d "%~dp0"
chcp 65001 >nul
set "PYTHONPATH=%~dp0src;%~dp0;%~dp0tools"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
echo.
echo ================================================================
echo   OKX COPY TRADERS - OBSERVATION PUBLIQUE EN CONTINU
echo   GET publics seulement - aucune cle, aucun ordre
echo   Selection gelee au demarrage; Ctrl+C arrete proprement
echo   Donnees d'observation, pas une preuve de rentabilite
echo ================================================================
echo.
set "OKX_PYTHON="
set "OKX_PY_ARGS="
if exist "%~dp0tools\python\python.exe" set "OKX_PYTHON=%~dp0tools\python\python.exe"
if not defined OKX_PYTHON (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "OKX_PYTHON=py"
    set "OKX_PY_ARGS=-3"
  )
)
if not defined OKX_PYTHON (
  echo [NO_GO] Python 3 introuvable; aucun telechargement automatique.
  set "RC=30"
  goto :done
)
"%OKX_PYTHON%" %OKX_PY_ARGS% -c "import pydantic, sqlalchemy, yaml" >nul 2>nul
if errorlevel 1 (
  echo [NO_GO] Dependances absentes. Installez le projet avec : py -3 -m pip install -e .
  set "RC=31"
  goto :done
)
"%OKX_PYTHON%" %OKX_PY_ARGS% "%~dp0tools\collect_okx_copy_traders.py" --network-read --follow
set "RC=%ERRORLEVEL%"
:done
echo.
if "%RC%"=="0" (
  echo [FIN] Observation arretee; selections et rapports restent conserves.
) else if "%RC%"=="130" (
  echo [ARRET PROPRE] Ctrl+C recu.
) else (
  echo [NO_GO] Code %RC%. Aucune rentabilite n'est prouvee.
)
pause
endlocal & exit /b %RC%
