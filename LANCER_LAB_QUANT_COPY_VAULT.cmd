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
set "REAL_MAINNET_TRADING=false"
set "TESTNET_ONLY=true"
set "ALINA_QUANT_CPU_PERCENT=65"

echo.
echo ================================================================
echo   ALINA SMART FLOW - LAB QUANT COPY-VAULT
echo   Double clic : inventaire + freeze + tests locaux detailles
echo   PAPER / READ-ONLY - aucune collecte ou transaction
echo ================================================================
echo.

set "ALINA_LAB_PYTHON="
set "ALINA_LAB_PY_ARGS="
if exist "%~dp0tools\python\python.exe" set "ALINA_LAB_PYTHON=%~dp0tools\python\python.exe"
if not defined ALINA_LAB_PYTHON (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "ALINA_LAB_PYTHON=py"
    set "ALINA_LAB_PY_ARGS=-3"
  )
)
if not defined ALINA_LAB_PYTHON (
  echo [ERREUR] Aucun Python compatible n'a ete trouve.
  echo Aucun runtime ne sera telecharge ou installe automatiquement.
  echo Preparez tools\python ou installez/configurez Python 3, puis relancez ce fichier.
  if /I not "%ALINA_QUANT_NO_PAUSE%"=="1" pause
  endlocal & exit /b 30
)

"%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% -c "import pytest, typer" >nul 2>nul
if errorlevel 1 (
  echo [ERREUR] Runtime de test incomplet : pytest et typer sont obligatoires.
  echo Installez le projet avec : py -3 -m pip install -e ".[dev]"
  if /I not "%ALINA_QUANT_NO_PAUSE%"=="1" pause
  endlocal & exit /b 31
)

"%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% -c "import xdist" >nul 2>nul
if errorlevel 1 echo [INFO] pytest-xdist absent : repli serie sur un coeur.

if /I "%~1"=="research" (
  if "%~2"=="" (
    echo [ERREUR] Usage : LANCER_LAB_QUANT_COPY_VAULT.cmd research "CHEMIN_WORKSPACE_FULL_COLD"
    echo Un dossier SAFE decompresse seul ne prouve pas la compatibilite economique.
    if /I not "%ALINA_QUANT_NO_PAUSE%"=="1" pause
    endlocal & exit /b 2
  )
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\alina_quant_lab_console.py" --research --dataset-root "%~2"
) else if /I "%~1"=="preflight" (
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\alina_quant_lab_console.py" --preflight-only
) else (
  "%ALINA_LAB_PYTHON%" %ALINA_LAB_PY_ARGS% "%~dp0tools\alina_quant_lab_console.py"
)
set "RC=%ERRORLEVEL%"
echo.
if /I "%~1"=="preflight" (
  echo [INFO] Pre-verification terminee; les tests n'ont pas ete lances.
) else if "%RC%"=="0" (
  echo [FIN] Commande terminee sans echec. Un resultat economique doit etre verifie dans les rapports.
) else (
  echo [ATTENTION] Code %RC%. Lisez le rapport et les journaux affiches ci-dessus.
)
echo.
if /I not "%ALINA_QUANT_NO_PAUSE%"=="1" pause
endlocal & exit /b %RC%
