@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
pushd "%~dp0"
if errorlevel 1 goto :bad_location

rem Reconciliateur Local <-> GitHub : code (push) + shards SAFE (AlinaSync).
rem PAS d'auto-align catalog/ : partial clone + nombreux fichiers = echec.
rem Le moteur Python refuse seulement quand catalog/ est modifie LOCALEMENT.
rem Si c'est le cas, l'operateur doit nettoyer manuellement avant de pousser.
rem Aucun push force, reset, clean ou effacement.
set "GIT_LFS_SKIP_SMUDGE=1"
set "ALINA_ROOT=%~dp0"
set "ALINA_BOOTSTRAP=%TEMP%\alina-code-sync-bootstrap-main"
set "ALINA_BOOTSTRAP_REF=c1f2d33909a11ca8f37edd2460a40f9a280f4202"
set "ALINA_ENGINE_REQUIRED_BUILD=2026-11-01-safe-main-promotion-v13"
set "ALINA_LOCAL_ENGINE_SHA256=4e0d0e6f74efffd18ea136dbb3ffe1a44ddf509e7841dd845a340d62bbfefaf3"
set "ALINA_ENGINE_SHA256=0f1f6c15bf620767eeff0181bf5305682e20d70a8a76f1517999bfa7d9434b5b"
set "ALINA_INSTALLER_SHA256=f7715589a563572b1374c35704e5914e6873f88b110e241b9c0b2bfe90a3f297"
set "HYPERSMART_GIT="
set "HYPERSMART_PYTHON="
set "HYPERSMART_PY_ARGS="
set "SYNC_OPTION="
set "ALINA_SKIP_CODE=0"
set "ALINA_SKIP_SHARDS=0"
set "ALINA_SHARDS_ARGS=--preflight-only"
set "RC=1"
set "RC_CODE=0"
set "RC_SHARDS=0"

if /I "%~1"=="--help" goto :help
if /I "%~1"=="-h" goto :help

if /I "%~1"=="--dry-run" set "SYNC_OPTION=--dry-run" & set "ALINA_SKIP_SHARDS=1"
if /I "%~1"=="dry-run" set "SYNC_OPTION=--dry-run" & set "ALINA_SKIP_SHARDS=1"
if /I "%~1"=="--plan" set "SYNC_OPTION=--dry-run" & set "ALINA_SKIP_SHARDS=1"
if /I "%~1"=="--wip-only" set "SYNC_OPTION=--wip-only" & set "ALINA_SKIP_SHARDS=1"
if /I "%~1"=="wip" set "SYNC_OPTION=--wip-only" & set "ALINA_SKIP_SHARDS=1"
if /I "%~1"=="--promote-current-to-main" set "SYNC_OPTION=--promote-current-to-main"
if /I "%~1"=="--portable-self-check" set "SYNC_OPTION=--portable-self-check" & set "ALINA_SKIP_SHARDS=1"
if /I "%~1"=="--benchmark" set "SYNC_OPTION=--benchmark" & set "ALINA_SKIP_SHARDS=1"
if /I "%~1"=="--code-only" set "ALINA_SKIP_SHARDS=1"

if /I "%~1"=="--shards-only" set "ALINA_SKIP_CODE=1"
if /I "%~1"=="--download-safe" set "ALINA_SHARDS_ARGS=--download-safe --max-download-gib 256"
if /I "%~1"=="--all-safe" set "ALINA_SHARDS_ARGS=--download-safe --all-safe"
if /I "%~1"=="--prune-cache" set "ALINA_SHARDS_ARGS=--prune-cache-only"
if /I "%~1"=="--catalog-budget" set "ALINA_SHARDS_ARGS=--catalog-budget" & set "ALINA_SKIP_CODE=1"
if /I "%~1"=="--unpack-safe" set "ALINA_SHARDS_ARGS=--download-safe --unpack-safe --max-download-gib 256"

if not "%~1"=="" if not defined SYNC_OPTION if "%ALINA_SKIP_CODE%"=="0" if "%ALINA_SHARDS_ARGS%"=="--preflight-only" if /I not "%~1"=="--code-only" goto :bad_option

echo ============================================================
echo  ALINA SMART FLOW - RECONCILIATION LOCAL ^<-^> GITHUB
echo  Double clic : code (push) + preflight SAFE shards
echo  Shards telecharges uniquement sur demande explicite
echo  Aucun push force, reset, clean ou effacement de donnees
echo ============================================================
echo [05%%] [LANCEUR 1/7] Racine du depot et mode d'execution
echo Depot : %ALINA_ROOT%
if /I "%SYNC_OPTION%"=="--dry-run" echo Code mode : simulation en lecture seule
if /I "%SYNC_OPTION%"=="--wip-only" echo Code mode : checkpoint local uniquement
if "%ALINA_SKIP_CODE%"=="1" echo Code mode : ignore (--shards-only ou --catalog-budget)
if "%ALINA_SKIP_CODE%"=="0" if not defined SYNC_OPTION echo Code mode : synchronisation prudente vers GitHub main
echo Shards mode : %ALINA_SHARDS_ARGS%
if "%ALINA_SKIP_SHARDS%"=="1" echo Shards mode : ignore (mode lecture seule code)

if exist "%ALINA_ROOT%tools\git\cmd\git.exe" set "HYPERSMART_GIT=%ALINA_ROOT%tools\git\cmd\git.exe"
if not defined HYPERSMART_GIT if exist "%ProgramFiles%\Git\cmd\git.exe" set "HYPERSMART_GIT=%ProgramFiles%\Git\cmd\git.exe"
if not defined HYPERSMART_GIT if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe" set "HYPERSMART_GIT=%LOCALAPPDATA%\Programs\Git\cmd\git.exe"
if not defined HYPERSMART_GIT for %%G in (git.exe) do if not "%%~$PATH:G"=="" set "HYPERSMART_GIT=%%~$PATH:G"
if defined HYPERSMART_GIT goto :git_ready

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
echo [15%%] [LANCEUR 2/7] Verification de Git
echo Git : %HYPERSMART_GIT%
"%HYPERSMART_GIT%" --version
if errorlevel 1 goto :missing_git

echo [25%%] [LANCEUR 3/7] Recherche de Python 3.11 ou plus
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
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto :missing_python
echo Python : %HYPERSMART_PYTHON% %HYPERSMART_PY_ARGS%
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% --version

set "ALINA_ENGINE=%ALINA_ROOT%tools\alina_git_code_sync.py"
if not exist "%ALINA_ENGINE%" goto :get_engine
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
echo [35%%] [LANCEUR 4/7] Verification du moteur de synchronisation code
echo Moteur code : %ALINA_ENGINE%
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% -c "import ast,sys; ast.parse(open(sys.argv[1],'rb').read())" "%ALINA_ENGINE%" >nul 2>nul
if errorlevel 1 goto :invalid_engine
echo [OK] Version du moteur et syntaxe Python valides

if /I "%SYNC_OPTION%"=="--portable-self-check" goto :self_check
if /I "%SYNC_OPTION%"=="--benchmark" goto :benchmark

set "ALINA_SHARDS_ENGINE=%ALINA_ROOT%tools\sync_complete_clone.py"
if not exist "%ALINA_SHARDS_ENGINE%" goto :missing_shards_engine
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% -c "import ast,sys; ast.parse(open(sys.argv[1],'rb').read())" "%ALINA_SHARDS_ENGINE%" >nul 2>nul
if errorlevel 1 goto :missing_shards_engine
echo Moteur shards : %ALINA_SHARDS_ENGINE%

if "%ALINA_SKIP_CODE%"=="1" goto :skip_code_sync
if not defined SYNC_OPTION (
  set "ALINA_ACTIVE_BRANCH="
  for /f "delims=" %%B in ('"%HYPERSMART_GIT%" -C "%ALINA_ROOT%." branch --show-current 2^>nul') do (
    set "ALINA_ACTIVE_BRANCH=%%B"
  )
  if defined ALINA_ACTIVE_BRANCH if /I not "%ALINA_ACTIVE_BRANCH%"=="main" set "SYNC_OPTION=--promote-current-to-main"
)
if /I "%SYNC_OPTION%"=="--promote-current-to-main" echo [INFO] Branche active %ALINA_ACTIVE_BRANCH%; promotion fast-forward securisee vers main.

echo.
echo [45%%] [PRE-FETCH] hydrate les blobs manquants (partial clone) ...
"%HYPERSMART_GIT%" fetch origin main --no-filter --quiet
if errorlevel 1 echo [WARN] pre-fetch non critique a echoue; poursuite normale.
if not errorlevel 1 echo [OK] pre-fetch termine.
echo.
echo [50%%] [LANCEUR 5/7] PHASE A - synchronisation du code (fetch+rebase+push, 1-3 min)
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% "%ALINA_ENGINE%" --root "%ALINA_ROOT%." --git "%HYPERSMART_GIT%" %SYNC_OPTION%
set "RC_CODE=%ERRORLEVEL%"
if not "%RC_CODE%"=="0" goto :code_failed
if /I "%SYNC_OPTION%"=="--dry-run" echo [85%%] [DRY-RUN] Phase A OK; aucun fichier Git modifie et aucun push effectue.
if /I "%SYNC_OPTION%"=="--wip-only" echo [85%%] [CHECKPOINT] Phase A OK; sauvegarde locale uniquement.
if not defined SYNC_OPTION echo [85%%] [OK] Phase A terminee et verifiee.
if /I "%SYNC_OPTION%"=="--promote-current-to-main" echo [85%%] [OK] Phase A terminee et verifiee.
goto :phase_b

:skip_code_sync
echo [50%%] [LANCEUR 5/7] PHASE A - ignoree (--shards-only / --catalog-budget)

:phase_b
if "%ALINA_SKIP_SHARDS%"=="1" goto :skip_shards_sync
echo.
echo [90%%] [LANCEUR 6/7] PHASE B - AlinaSync (shards SAFE)
echo Arguments : %ALINA_SHARDS_ARGS%
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% "%ALINA_SHARDS_ENGINE%" %ALINA_SHARDS_ARGS%
set "RC_SHARDS=%ERRORLEVEL%"
if not "%RC_SHARDS%"=="0" goto :shards_failed
echo [98%%] [OK] Phase B terminee.
goto :finish_ok

:skip_shards_sync
echo [90%%] [LANCEUR 6/7] PHASE B - ignoree (mode lecture seule du code)
goto :finish_ok

:finish_ok
set "RC=0"
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
echo [NO_GO] Option inconnue : %~1
echo Utiliser --help pour la liste des options.
set "RC=2"
goto :finish

:help
echo Usage : POUSSER-GITHUB-FORCE.cmd [option]
echo.
echo Sans option  = code sync (push) + AlinaSync preflight (rapide, sans telechargement).
echo.
echo Modes code uniquement (shards ignores) :
echo   --dry-run                  simulation lecture seule, pas de push
echo   --wip-only                 checkpoint local uniquement, pas de push
echo   --promote-current-to-main  promotion fast-forward securisee vers main
echo   --portable-self-check      verifie git + moteur Python et quitte
echo   --benchmark                benchmark lecture seule de l'inventaire Git
echo   --code-only                code sync normal, pas de phase shards
echo.
echo Modes shards (code sync + AlinaSync) :
echo   --download-safe            telecharge SAFE replayable (plafond 256 GiB)
echo   --all-safe                 telecharge tout SAFE sans plafond
echo   --unpack-safe              telecharge + decompresse JSONL (long)
echo   --prune-cache              supprime les copies cache verifiees inutilisees
echo.
echo Modes isoles :
echo   --shards-only              AlinaSync seul (preflight ou autre), pas de code
echo   --catalog-budget           compta offline SAFE/PARTIAL/REJECT, aucun reseau
echo.
echo Aucun force-push, reset, clean, stash, suppression silencieuse ou ordre reel.
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
echo [NO_GO] Python 3.11 ou plus est requis pour synchroniser sans risque.
set "RC=31"
goto :finish

:missing_engine
echo [NO_GO] Moteur code manquant et telechargement du code impossible.
set "RC=32"
goto :finish

:missing_shards_engine
echo [NO_GO] Moteur shards manquant ou invalide : tools\sync_complete_clone.py
set "RC=34"
goto :finish

:invalid_engine
echo [NO_GO] Code du moteur Python incomplet ou invalide. Aucune synchro.
set "RC=33"
goto :finish

:code_failed
echo.
echo [NO_GO] Phase A (code) echouee avec code %RC_CODE%. Aucune operation de force.
echo         Phase B (shards) ignoree pour preserver l'etat.
echo         Consulter : runtime\reports\git-sync\LAST_SYNC.json
set "RC=%RC_CODE%"
goto :finish

:shards_failed
echo.
echo [NO_GO] Phase B (shards) echouee avec code %RC_SHARDS%.
echo         Phase A (code) est deja terminee avec succes.
echo         Consulter : runtime\recovery\full\SYNC_REPORT.json ou RESTORE_REPORT.json
set "RC=%RC_SHARDS%"
goto :finish

:prepare_bootstrap
if exist "%ALINA_BOOTSTRAP%\" exit /b 0
mkdir "%ALINA_BOOTSTRAP%" >nul 2>nul
if not exist "%ALINA_BOOTSTRAP%\" exit /b 43
exit /b 0

:download_source
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
echo [100%%] [LANCEUR 7/7] Fin du lanceur - code retour %RC%
if exist "%ALINA_ROOT%runtime\reports\git-sync\LAST_SYNC.json" echo Rapport code  : %ALINA_ROOT%runtime\reports\git-sync\LAST_SYNC.json
if exist "%ALINA_ROOT%runtime\recovery\full\SYNC_REPORT.json" echo Rapport shards: %ALINA_ROOT%runtime\recovery\full\SYNC_REPORT.json
if /I "%HYPERSMART_PUSH_NO_PAUSE%"=="1" goto :finish_cleanup
pause
:finish_cleanup
popd
endlocal & exit /b %RC%
