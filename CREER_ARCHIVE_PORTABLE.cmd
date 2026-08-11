@echo off
setlocal EnableExtensions DisableDelayedExpansion
REM ============================================================================
REM HyperSmart portability - Windows 10/11 x64 - PAPER/READ-ONLY ONLY.
REM Default: complete disaster-recovery folder clone, including durable history.
REM --application-seule creates the smaller clean-start ZIP.
REM --release-stricte keeps the CI-bound official release pipeline.
REM --sortie-dir <dir> builds the strict verified ZIP into an explicit directory.
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

if /I "%~1"=="--portable-self-check" goto :portable_self_check

echo.
echo ==============================================================================
echo   PORTABILITE HYPERSMART - Windows 10/11 x64
echo   Defaut : clone de secours COMPLET ^(code + Git + donnees + logs + historique^)
echo   SQLite copie par Backup API ^| identite machine regeneree au premier lancement
echo   Sortie courte hors projet choisie automatiquement si aucun chemin n'est fourni
echo ==============================================================================
echo.

if /I "%~1"=="--sortie-dir" goto :release_output
if /I "%~1"=="--release-stricte" goto :release_stricte
if /I "%~1"=="--application-seule" goto :application_seule
if /I "%~1"=="--verifier-clone" goto :verifier_clone
if /I "%~1"=="--dry-run" goto :clone_dry_run
if not "%~1"=="" goto :clone_destination

"%HYPERSMART_PYTHON%" -m hl_observer.ops.portable_clone --racine "%~dp0."
set "RC=%ERRORLEVEL%"
goto :resultat

:clone_destination
"%HYPERSMART_PYTHON%" -m hl_observer.ops.portable_clone ^
  --racine "%~dp0." --destination "%~1"
set "RC=%ERRORLEVEL%"
goto :resultat

:clone_dry_run
"%HYPERSMART_PYTHON%" -m hl_observer.ops.portable_clone --racine "%~dp0." --dry-run
set "RC=%ERRORLEVEL%"
goto :resultat

:verifier_clone
if "%~2"=="" (
  echo [REFUSE] Chemin du clone manquant.
  set "RC=32"
  goto :resultat
)
"%HYPERSMART_PYTHON%" -m hl_observer.ops.portable_clone --verify "%~2"
set "RC=%ERRORLEVEL%"
goto :resultat

:application_seule
"%HYPERSMART_PYTHON%" -m hl_observer.ops.archive_portable ^
  --racine "%~dp0." --mode-developpement
set "RC=%ERRORLEVEL%"
goto :resultat

:release_output
if "%~2"=="" (
  echo [REFUSE] Dossier de sortie release manquant apres --sortie-dir.
  set "RC=33"
  goto :resultat
)
if not "%~3"=="" (
  echo [REFUSE] Arguments supplementaires inattendus apres --sortie-dir.
  set "RC=34"
  goto :resultat
)
"%HYPERSMART_PYTHON%" -m hl_observer.ops.portable_release ^
  --racine "%~dp0." --sortie-dir "%~2"
set "RC=%ERRORLEVEL%"
goto :resultat

:release_stricte
"%HYPERSMART_PYTHON%" -m hl_observer.ops.portable_release --racine "%~dp0."
set "RC=%ERRORLEVEL%"

goto :resultat

:portable_self_check
"%HYPERSMART_PYTHON%" -c "import hl_observer.ops.portable_clone, hl_observer.ops.archive_portable; print('PORTABLE_ARCHIVE_CHECK_OK')"
set "RC=%ERRORLEVEL%"
goto :resultat

:resultat

echo.
if "%RC%"=="0" (
  echo [OK] Operation portable terminee et reverifiee.
  echo      Sur le PC cible : ouvre le dossier puis double-clique LANCER_HYPERSMART.cmd.
) else (
  echo [REFUSE] Aucun clone final incomplet n'a ete publie ^(code %RC%^).
  echo          Ferme HyperSmart si un writer ou une session est encore actif.
)
echo.

if defined CI (
  endlocal & exit /b %RC%
)
pause
endlocal & exit /b %RC%
