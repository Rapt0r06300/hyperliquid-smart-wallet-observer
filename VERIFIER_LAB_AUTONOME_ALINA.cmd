@echo off
setlocal EnableExtensions
REM Diagnostic explicite du laboratoire autonome Alina.
REM CHECK UNIQUEMENT : aucun ordre reel, aucune signature, aucune collecte live.
cd /d "%~dp0"
call "%~dp0tools\portable_env.cmd"
if errorlevel 1 (
  echo [ALINA-LAB-CHECK] Python portable invalide. Abandon fail-closed.
  endlocal & exit /b 30
)
if not defined HYPERSMART_PYTHON (
  echo [ALINA-LAB-CHECK] HYPERSMART_PYTHON absent. Abandon fail-closed.
  endlocal & exit /b 31
)
set "PYTHONPATH=%~dp0src;%~dp0tools"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "REAL_MAINNET_TRADING=false"
set "TESTNET_ONLY=true"

"%HYPERSMART_PYTHON%" "%~dp0tools\alina_autonomous_lab.py" check
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" (
  echo [ALINA-LAB-CHECK] Diagnostic refuse ^(code %RC%^).
  endlocal & exit /b %RC%
)

echo [ALINA-LAB-CHECK] Diagnostic PAPER/READ-ONLY valide.
endlocal & exit /b 0
