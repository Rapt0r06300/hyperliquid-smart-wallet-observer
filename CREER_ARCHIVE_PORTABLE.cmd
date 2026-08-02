@echo off
setlocal EnableExtensions DisableDelayedExpansion
REM ============================================================================
REM HyperSmart portable package - Windows 10/11 x64 - PAPER/READ-ONLY ONLY.
REM Default: complete local portable copy, internally hashed and re-extracted.
REM Optional: --release-stricte keeps the CI-bound official release pipeline.
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
echo   COPIE PORTABLE HYPERSMART - autonome et verifiee
echo   Sources ^| Python ^| dependances ^| manifestes SHA-256 ^| extraction testee
echo   Sortie finale hors projet uniquement ^(Bureau par defaut^)
echo ==============================================================================
echo.

if /I "%~1"=="--release-stricte" goto :release_stricte

"%HYPERSMART_PYTHON%" -m hl_observer.ops.archive_portable ^
  --racine "%~dp0." --mode-developpement %*
set "RC=%ERRORLEVEL%"
goto :resultat

:release_stricte
"%HYPERSMART_PYTHON%" -m hl_observer.ops.portable_release --racine "%~dp0."
set "RC=%ERRORLEVEL%"

:resultat

echo.
if "%RC%"=="0" (
  echo [OK] Archive portable creee et reverifiee sur le Bureau.
) else (
  echo [REFUSE] Aucune archive incomplete n'a ete conservee ^(code %RC%^).
  echo          Ferme HyperSmart si un writer ou une session est encore actif.
)
echo.

if defined CI (
  endlocal & exit /b %RC%
)
pause
endlocal & exit /b %RC%
