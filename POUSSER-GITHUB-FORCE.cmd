@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
pushd "%~dp0"
if errorlevel 1 goto :bad_location

rem One-click code-only bidirectional Git reconciliation.
rem AlinaSync alone downloads/validates/unpacks SAFE shards.
rem No forced push, reset, clean, stash or automatic deletion of data.
rem A double-click window stays open by default so failures remain visible.
rem Set HYPERSMART_PUSH_NO_PAUSE=1 for CI/automation or cmd /c callers.
set "GIT_LFS_SKIP_SMUDGE=1"
set "ALINA_ROOT=%~dp0"
set "ALINA_BOOTSTRAP=%TEMP%\alina-code-sync-bootstrap-main"
rem Bootstrap only from the reviewed exact commit that carries this engine build.
rem The remote branch may advance independently; the hash check below keeps a
rem stale or tampered helper from being executed.
set "ALINA_BOOTSTRAP_REF=c1f2d33909a11ca8f37edd2460a40f9a280f4202"
set "ALINA_ENGINE_REQUIRED_BUILD=2026-11-01-safe-main-promotion-v13"
rem The local engine is intentionally pinned too: a same-build but modified
rem helper must not be executed silently.
set "ALINA_LOCAL_ENGINE_SHA256=4e0d0e6f74efffd18ea136dbb3ffe1a44ddf509e7841dd845a340d62bbfefaf3"
set "ALINA_ENGINE_SHA256=0f1f6c15bf620767eeff0181bf5305682e20d70a8a76f1517999bfa7d9434b5b"
set "ALINA_INSTALLER_SHA256=f7715589a563572b1374c35704e5914e6873f88b110e241b9c0b2bfe90a3f297"
set "HYPERSMART_GIT="
set "HYPERSMART_PYTHON="
set "HYPERSMART_PY_ARGS="
set "SYNC_OPTION="
set "RC=1"

if /I "%~1"=="--help" goto :help
if /I "%~1"=="-h" goto :help

if /I "%~1"=="--dry-run" set "SYNC_OPTION=--dry-run"
if /I "%~1"=="dry-run" set "SYNC_OPTION=--dry-run"
if /I "%~1"=="--plan" set "SYNC_OPTION=--dry-run"
if /I "%~1"=="--wip-only" set "SYNC_OPTION=--wip-only"
if /I "%~1"=="wip" set "SYNC_OPTION=--wip-only"
if /I "%~1"=="--promote-current-to-main" set "SYNC_OPTION=--promote-current-to-main"
if /I "%~1"=="--portable-self-check" set "SYNC_OPTION=--portable-self-check"
if /I "%~1"=="--benchmark" set "SYNC_OPTION=--benchmark"
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
if not errorlevel 1 (
  powershell.exe -NoLogo -NoProfile -Command "$ErrorActionPreference='Stop'; $sha256=[System.Security.Cryptography.SHA256]::Create(); $stream=[System.IO.File]::OpenRead('%ALINA_ENGINE%'); try { $actual=([BitConverter]::ToString($sha256.ComputeHash($stream))).Replace('-','').ToLowerInvariant() } finally { $stream.Dispose(); $sha256.Dispose() }; if ($actual -ne '%ALINA_LOCAL_ENGINE_SHA256%') { throw ('SHA-256 local inattendu: ' + $actual) }"
  if errorlevel 1 goto :invalid_engine
  goto :engine_ready
)
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
if /I "%SYNC_OPTION%"=="--benchmark" goto :benchmark

rem A double click from a Codex/WIP branch promotes it only by a guarded
rem fast-forward. Dry-run and WIP modes stay branch-local/read-only.
if not defined SYNC_OPTION (
  set "ALINA_ACTIVE_BRANCH="
  for /f "delims=" %%B in ('"%HYPERSMART_GIT%" -C "%ALINA_ROOT%." branch --show-current 2^>nul') do (
    set "ALINA_ACTIVE_BRANCH=%%B"
  )
  if defined ALINA_ACTIVE_BRANCH if /I not "%ALINA_ACTIVE_BRANCH%"=="main" set "SYNC_OPTION=--promote-current-to-main"
)
if /I "%SYNC_OPTION%"=="--promote-current-to-main" echo [INFO] Branche active %ALINA_ACTIVE_BRANCH%; promotion fast-forward securisee vers main.

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
echo PORTABLE_GITHUB_PUSH_CHECK_OK
set "RC=0"
goto :finish

:benchmark
echo [DIAGNOSTIC] Benchmark lecture seule de l'inventaire Git (5 runs)...
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% "%ALINA_ROOT%tools\benchmark_git_sync.py" --root "%ALINA_ROOT%." --git "%HYPERSMART_GIT%" --runs 5
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" echo [NO_GO] Benchmark non termine; aucune mutation Git.
goto :finish

:bad_option
echo [NO_GO] Option inconnue. Utiliser ce fichier en double clic sans argument.
set "RC=2"
goto :finish

:help
echo Usage : POUSSER-GITHUB-FORCE.cmd [--dry-run^|--plan^|--wip-only^|--promote-current-to-main^|--portable-self-check^|--benchmark]
echo Par defaut, une branche non-main est promue vers main uniquement par fast-forward securise.
echo Aucun force-push, reset, clean, stash, suppression ou telechargement de shard.
set "RC=0"
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
rem Bootstrap only from the pinned canonical GitHub commit. The caller verifies
rem both the engine build and the downloaded file hash.
rem Only tools/*.ps1 and *.py source can be requested by this CMD.
set "ALINA_EXPECTED_SHA256="
if /I "%~1"=="tools/alina_git_code_sync.py" set "ALINA_EXPECTED_SHA256=%ALINA_ENGINE_SHA256%"
if /I "%~1"=="tools/install_portable_git.ps1" set "ALINA_EXPECTED_SHA256=%ALINA_INSTALLER_SHA256%"
echo [INFO] Chargement du composant de code %~1
powershell.exe -NoLogo -NoProfile -Command "$ErrorActionPreference='Stop'; Invoke-WebRequest -UseBasicParsing -TimeoutSec 20 -MaximumRedirection 2 -Uri 'https://raw.githubusercontent.com/Rapt0r06300/hyperliquid-smart-wallet-observer/%ALINA_BOOTSTRAP_REF%/%~1' -OutFile '%~2'; if ((Get-Item -LiteralPath '%~2').Length -lt 500) { throw 'Fichier incomplet' }"
if errorlevel 1 exit /b 44
if not exist "%~2" exit /b 44
if defined ALINA_EXPECTED_SHA256 powershell.exe -NoLogo -NoProfile -Command "$ErrorActionPreference='Stop'; $sha256=[System.Security.Cryptography.SHA256]::Create(); $stream=[System.IO.File]::OpenRead('%~2'); try { $actual=([BitConverter]::ToString($sha256.ComputeHash($stream))).Replace('-','').ToLowerInvariant() } finally { $stream.Dispose(); $sha256.Dispose() }; if ($actual -ne '%ALINA_EXPECTED_SHA256%') { throw ('SHA-256 inattendu: ' + $actual) }"
if errorlevel 1 exit /b 45
set "ALINA_EXPECTED_SHA256="
exit /b 0

:finish
echo [LANCEUR 6/6] Fin du lanceur - code retour %RC%
if exist "%ALINA_ROOT%runtime\reports\git-sync\LAST_SYNC.json" echo Rapport detaille : %ALINA_ROOT%runtime\reports\git-sync\LAST_SYNC.json
if /I "%HYPERSMART_PUSH_NO_PAUSE%"=="1" goto :finish_cleanup
pause
:finish_cleanup
popd
endlocal & exit /b %RC%
