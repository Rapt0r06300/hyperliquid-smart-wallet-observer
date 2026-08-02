@echo off
setlocal EnableExtensions DisableDelayedExpansion
REM ============================================================================
REM HyperSmart portable release - Windows 10/11 x64 - PAPER/READ-ONLY ONLY
REM Publishes no ZIP until two deterministic builds, extracted validation,
REM both launchers, full tests, safety audits and RELEASE_READY all pass.
REM ============================================================================
cd /d "%~dp0"

call "%~dp0tools\portable_env.cmd"
if errorlevel 1 (
  echo [REFUSE] Runtime unique tools\python indisponible.
  endlocal & exit /b 30
)
if not defined HYPERSMART_PYTHON (
  echo [REFUSE] HYPERSMART_PYTHON non defini.
  endlocal & exit /b 31
)

set "PYTHONPATH=%~dp0src;%~dp0tools;%~dp0"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONNOUSERSITE=1"
set "PIP_NO_INDEX=1"
set "HL_ENABLE_MAINNET_EXECUTION=0"
set "HL_ENABLE_TESTNET_EXECUTION=0"
set "REAL_MAINNET_TRADING=false"
set "TESTNET_EXECUTION_ENABLED=false"

echo.
echo ==============================================================================
echo   RELEASE PORTABLE HYPERSMART - validation extraite complete
echo   Deux builds reproductibles ^| tests ^| launchers ^| audits ^| CI exacte
echo   Sortie finale hors projet uniquement ^(Bureau par defaut^)
echo ==============================================================================
echo.

"%HYPERSMART_PYTHON%" -m hl_observer.ops.portable_release --racine "%~dp0." %*
set "RC=%ERRORLEVEL%"

echo.
if "%RC%"=="0" (
  echo [OK] Archive conservee : toutes les portes RELEASE_READY sont vertes.
) else (
  echo [REFUSE] Aucune archive candidate conservee ^(code %RC%^).
  echo          Consulte RELEASE_FAILED.json dans le dossier de sortie.
)
echo.

if defined CI (
  endlocal & exit /b %RC%
)
pause
endlocal & exit /b %RC%
