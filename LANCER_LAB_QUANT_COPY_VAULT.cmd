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

echo.
echo ================================================================
echo   ALINA SMART FLOW - LAB QUANT COPY-VAULT
echo   Double clic : inventaire + freeze + tests locaux detailles
echo   PAPER / READ-ONLY - aucune collecte ou transaction
echo ================================================================
echo.

where py >nul 2>nul
if errorlevel 1 (
  echo [ERREUR] Python Launcher Windows introuvable.
  echo Aucun runtime ne sera telecharge ou installe automatiquement.
  echo Installez/configurez Python et pytest, puis relancez ce fichier.
  if /I not "%ALINA_QUANT_NO_PAUSE%"=="1" pause
  endlocal & exit /b 30
)

py -3 -c "import pytest" >nul 2>nul
if errorlevel 1 (
  echo [ERREUR] pytest absent du Python 3 local. Aucun paquet ne sera installe.
  echo Le rapport ne peut pas etre lance tant que pytest n'est pas disponible.
  if /I not "%ALINA_QUANT_NO_PAUSE%"=="1" pause
  endlocal & exit /b 31
)

if /I "%~1"=="preflight" (
  py -3 "%~dp0tools\alina_quant_lab_console.py" --preflight-only
) else (
  py -3 "%~dp0tools\alina_quant_lab_console.py"
)
set "RC=%ERRORLEVEL%"
echo.
if /I "%~1"=="preflight" (
  echo [INFO] Pre-verification terminee; les tests n'ont pas ete lances.
) else if "%RC%"=="0" (
  echo [FIN] Tests termines sans echec. Cela ne prouve pas la rentabilite.
) else (
  echo [ATTENTION] Code %RC%. Lisez le rapport et les journaux affiches ci-dessus.
)
echo.
if /I not "%ALINA_QUANT_NO_PAUSE%"=="1" pause
endlocal & exit /b %RC%
