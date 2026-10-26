@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
pushd "%~dp0"
if errorlevel 1 goto :bad_location

rem One-click code-only bidirectional Git reconciliation.
rem AlinaSync alone downloads/validates/unpacks SAFE shards.
rem No forced push, reset, clean, stash or automatic deletion of data.
set "GIT_LFS_SKIP_SMUDGE=1"
set "ALINA_ROOT=%~dp0"
set "ALINA_BOOTSTRAP=%TEMP%\alina-code-sync-bootstrap-main"
set "ALINA_BOOTSTRAP_REF=main"
set "ALINA_ENGINE_REQUIRED_BUILD=2026-10-26-status-inventory-v2"
set "HYPERSMART_GIT="
set "HYPERSMART_PYTHON="
set "HYPERSMART_PY_ARGS="
set "SYNC_OPTION="
set "RC=1"

if /I "%~1"=="--dry-run" set "SYNC_OPTION=--dry-run"
if /I "%~1"=="dry-run" set "SYNC_OPTION=--dry-run"
if /I "%~1"=="--wip-only" set "SYNC_OPTION=--wip-only"
if /I "%~1"=="wip" set "SYNC_OPTION=--wip-only"
if /I "%~1"=="--portable-self-check" set "SYNC_OPTION=--portable-self-check"
if not "%~1"=="" if not defined SYNC_OPTION goto :bad_option
if not "%~2"=="" goto :bad_option

echo ============================================================
echo  ALINA SMART FLOW - SYNCHRONISATION GITHUB ET CODE LOCAL
echo  Double clic : sauvegarde WIP, fusion prudente et push
echo  AUCUN telechargement de shards : reserve a AlinaSync
echo  Aucun push force, reset ni effacement des donnees
echo ============================================================
echo [LANCEUR 1/6] Racine du depot et mode d'execution
echo Depot : %ALINA_ROOT%
if /I "%SYNC_OPTION%"=="--dry-run" echo Mode : simulation en lecture seule
if /I "%SYNC_OPTION%"=="--wip-only" echo Mode : checkpoint local uniquement
if not defined SYNC_OPTION echo Mode : synchronisation prudente vers GitHub main

rem Prefer embedded Git, then standard Windows installation locations.
if exist "%ALINA_ROOT%tools\git\cmd\git.exe" set "HYPERSMART_GIT=%ALINA_ROOT%tools\git\cmd\git.exe"
if not defined HYPERSMART_GIT if exist "%ProgramFiles%\Git\cmd\git.exe" set "HYPERSMART_GIT=%ProgramFiles%\Git\cmd\git.exe"
if not defined HYPERSMART_GIT if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe" set "HYPERSMART_GIT=%LOCALAPPDATA%\Programs\Git\cmd\git.exe"
if not defined HYPERSMART_GIT for %%G in (git.exe) do if not "%%~$PATH:G"=="" set "HYPERSMART_GIT=%%~$PATH:G"
if defined HYPERSMART_GIT goto :git_ready

rem If only this CMD was copied from GitHub, the local installer may be
rem missing. Bootstrap just the pinned Git installer CODE into %TEMP%;
rem do not touch/overwrite any local source files.
echo [INFO] Git absent. Preparation du Git portable officiel...
set "ALINA_INSTALLER=%ALINA_ROOT%tools\install_portable_git.ps1"
if exist "%ALINA_INSTALLER%" goto :install_git
call :prepare_bootstrap
if errorlevel 1 goto :missing_git
set "ALINA_INSTALLER=%ALINA_BOOTSTRAP%\install_portable_git.ps1"
call :download_source "tools/install_portable_git.ps1" "%ALINA_INSTALLER%"
if errorlevel 1 goto :missing_git

:install_git
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%ALINA_INSTALLER%" -ProjectRoot "%ALINA_ROOT%."
if errorlevel 1 goto :missing_git
if not exist "%ALINA_ROOT%tools\git\cmd\git.exe" goto :missing_git
set "HYPERSMART_GIT=%ALINA_ROOT%tools\git\cmd\git.exe"

:git_ready
echo [LANCEUR 2/6] Verification de Git
echo Git : %HYPERSMART_GIT%
"%HYPERSMART_GIT%" --version
if errorlevel 1 goto :missing_git

rem Locate Python without changing the system configuration.
echo [LANCEUR 3/6] Recherche de Python 3.10 ou plus
if exist "%ALINA_ROOT%tools\python\python.exe" set "HYPERSMART_PYTHON=%ALINA_ROOT%tools\python\python.exe"
if defined HYPERSMART_PYTHON goto :python_ready
where py.exe >nul 2>nul
if errorlevel 1 goto :try_python
set "HYPERSMART_PYTHON=py"
set "HYPERSMART_PY_ARGS=-3"
goto :python_ready

:try_python
where python.exe >nul 2>nul
if errorlevel 1 goto :missing_python
set "HYPERSMART_PYTHON=python"

:python_ready
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>nul
if errorlevel 1 goto :missing_python
echo Python : %HYPERSMART_PYTHON% %HYPERSMART_PY_ARGS%
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% --version

rem A user may only have updated this CMD, not its Python companion.
rem Download the *pinned code-only helper* into %TEMP% if absent.
rem Do not overwrite a local version modified by Codex or Claude.
set "ALINA_ENGINE=%ALINA_ROOT%tools\alina_git_code_sync.py"
if not exist "%ALINA_ENGINE%" goto :get_engine
rem Never overwrite local Codex/Claude changes to the sync engine.
rem If it predates safe conflict kits, use pinned, isolated code in TEMP.
findstr /C:"%ALINA_ENGINE_REQUIRED_BUILD%" "%ALINA_ENGINE%" >nul 2>nul
if not errorlevel 1 goto :engine_ready
echo [INFO] Moteur local ancien conserve. Utilisation temporaire du moteur recent.

:get_engine
echo [INFO] Chargement du moteur Git Sync seul; aucun shard...
call :prepare_bootstrap
if errorlevel 1 goto :missing_engine
set "ALINA_ENGINE=%ALINA_BOOTSTRAP%\alina_git_code_sync.py"
call :download_source "tools/alina_git_code_sync.py" "%ALINA_ENGINE%"
if errorlevel 1 goto :missing_engine
findstr /C:"%ALINA_ENGINE_REQUIRED_BUILD%" "%ALINA_ENGINE%" >nul 2>nul
if errorlevel 1 goto :invalid_engine

:engine_ready
echo [LANCEUR 4/6] Verification du moteur de synchronisation
echo Moteur : %ALINA_ENGINE%
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% -c "import ast,sys; ast.parse(open(sys.argv[1],'rb').read())" "%ALINA_ENGINE%" >nul 2>nul
if errorlevel 1 goto :invalid_engine
echo [OK] Version du moteur et syntaxe Python valides

if /I "%SYNC_OPTION%"=="--portable-self-check" goto :self_check

echo.
echo [LANCEUR 5/6] Demarrage du moteur; chaque commande Git sera detaillee ci-dessous
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% "%ALINA_ENGINE%" --root "%ALINA_ROOT%." --git "%HYPERSMART_GIT%" %SYNC_OPTION%
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :sync_failed
echo.
if /I "%SYNC_OPTION%"=="--dry-run" goto :dry_run_done
if /I "%SYNC_OPTION%"=="--wip-only" goto :wip_done
echo [OK] Synchronisation terminee et verifiee.
goto :finish

:dry_run_done
echo [DRY-RUN TERMINE] Controle reussi; aucun fichier Git modifie et aucun push effectue.
goto :finish

:wip_done
echo [CHECKPOINT TERMINE] Sauvegarde locale uniquement; aucun push effectue.
goto :finish

:self_check
echo [OK] Git et moteur Python disponibles et syntaxiquement valides.
set "RC=0"
goto :finish

:bad_option
echo [NO_GO] Option inconnue. Utiliser ce fichier en double clic sans argument.
set "RC=2"
goto :finish

:bad_location
echo [NO_GO] Impossible d'ouvrir le dossier du CMD.
set "RC=3"
goto :finish

:missing_git
echo [NO_GO] Git absent ou installation echouee. Aucune donnee modifiee.
set "RC=30"
goto :finish

:missing_python
echo [NO_GO] Python 3.10 ou plus est requis pour synchroniser sans risque.
set "RC=31"
goto :finish

:missing_engine
echo [NO_GO] Moteur manquant et telechargement du code impossible.
set "RC=32"
goto :finish

:invalid_engine
echo [NO_GO] Code du moteur Python incomplet ou invalide. Aucune synchro.
set "RC=33"
goto :finish

:sync_failed
echo [NO_GO] Aucune operation de force. Consulter le rapport Git Sync.
goto :finish

:prepare_bootstrap
if exist "%ALINA_BOOTSTRAP%\" exit /b 0
mkdir "%ALINA_BOOTSTRAP%" >nul 2>nul
if not exist "%ALINA_BOOTSTRAP%\" exit /b 43
exit /b 0

:download_source
rem Bootstrap only from canonical GitHub main. The caller verifies the engine build.
rem Only tools/*.ps1 and *.py source can be requested by this CMD.
echo [INFO] Chargement du composant de code %~1
powershell.exe -NoLogo -NoProfile -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest -UseBasicParsing -Uri 'https://raw.githubusercontent.com/Rapt0r06300/hyperliquid-smart-wallet-observer/%ALINA_BOOTSTRAP_REF%/%~1' -OutFile '%~2'; if ((Get-Item -LiteralPath '%~2').Length -lt 500) { throw 'Fichier incomplet' }"
if errorlevel 1 exit /b 44
if not exist "%~2" exit /b 44
exit /b 0

:finish
echo [LANCEUR 6/6] Fin du lanceur - code retour %RC%
if exist "%ALINA_ROOT%runtime\reports\git-sync\LAST_SYNC.json" echo Rapport detaille : %ALINA_ROOT%runtime\reports\git-sync\LAST_SYNC.json
if /I not "%HYPERSMART_PUSH_NO_PAUSE%"=="1" pause
popd
endlocal & exit /b %RC%
