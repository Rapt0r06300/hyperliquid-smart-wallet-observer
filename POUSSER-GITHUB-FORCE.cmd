@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
pushd "%~dp0"
if errorlevel 1 goto :bad_location

rem Reconciliateur unique Local <-> GitHub.
rem  PHASE A  : commit local des changements de code (moteur, sans push).
rem  PHASE A2 : push fast-forward par plomberie (contourne le rebase casse
rem             par le shallow+partial clone ; aucun force, aucun reset).
rem  PHASE B  : AlinaSync (shards SAFE), preflight par defaut.
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
set "ALINA_SKIP_CODE=0"
set "ALINA_SKIP_SHARDS=0"
set "ALINA_DRYRUN=0"
set "ALINA_SHARDS_ARGS=--preflight-only"
set "RC=1"

if /I "%~1"=="--help" goto :help
if /I "%~1"=="-h" goto :help
if "%~1"=="" goto :args_done
if /I "%~1"=="--dry-run" ( set "ALINA_DRYRUN=1" & set "ALINA_SKIP_SHARDS=1" & goto :args_done )
if /I "%~1"=="--code-only" ( set "ALINA_SKIP_SHARDS=1" & goto :args_done )
if /I "%~1"=="--shards-only" ( set "ALINA_SKIP_CODE=1" & goto :args_done )
if /I "%~1"=="--download-safe" ( set "ALINA_SHARDS_ARGS=--download-safe --max-download-gib 256" & goto :args_done )
if /I "%~1"=="--all-safe" ( set "ALINA_SHARDS_ARGS=--download-safe --all-safe" & goto :args_done )
if /I "%~1"=="--unpack-safe" ( set "ALINA_SHARDS_ARGS=--download-safe --unpack-safe --max-download-gib 256" & goto :args_done )
if /I "%~1"=="--prune-cache" ( set "ALINA_SHARDS_ARGS=--prune-cache-only" & goto :args_done )
if /I "%~1"=="--catalog-budget" ( set "ALINA_SHARDS_ARGS=--catalog-budget" & set "ALINA_SKIP_CODE=1" & goto :args_done )
goto :bad_option
:args_done

echo ============================================================
echo  ALINA SMART FLOW - RECONCILIATION LOCAL ^<-^> GITHUB
echo  Commit local + push fast-forward + shards SAFE (preflight)
echo  Aucun push force, reset, clean ou effacement de donnees
echo ============================================================
echo [05%%] [LANCEUR 1/8] Racine : %ALINA_ROOT%
if "%ALINA_DRYRUN%"=="1" echo        Mode : DRY-RUN (construit le commit, ne pousse rien)
if "%ALINA_SKIP_CODE%"=="1" echo        Mode : shards uniquement (pas de code)
echo        Shards : %ALINA_SHARDS_ARGS%

rem --- Git ---
if exist "%ALINA_ROOT%tools\git\cmd\git.exe" set "HYPERSMART_GIT=%ALINA_ROOT%tools\git\cmd\git.exe"
if not defined HYPERSMART_GIT if exist "%ProgramFiles%\Git\cmd\git.exe" set "HYPERSMART_GIT=%ProgramFiles%\Git\cmd\git.exe"
if not defined HYPERSMART_GIT if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe" set "HYPERSMART_GIT=%LOCALAPPDATA%\Programs\Git\cmd\git.exe"
if not defined HYPERSMART_GIT for %%G in (git.exe) do if not "%%~$PATH:G"=="" set "HYPERSMART_GIT=%%~$PATH:G"
if not defined HYPERSMART_GIT goto :missing_git
echo [15%%] [LANCEUR 2/8] Git : %HYPERSMART_GIT%
"%HYPERSMART_GIT%" --version
if errorlevel 1 goto :missing_git

rem --- Python 3.11+ ---
echo [25%%] [LANCEUR 3/8] Recherche de Python 3.11 ou plus
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
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% --version

rem --- Moteur code (commit) ---
set "ALINA_ENGINE=%ALINA_ROOT%tools\alina_git_code_sync.py"
if not exist "%ALINA_ENGINE%" goto :missing_engine
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% -c "import ast,sys; ast.parse(open(sys.argv[1],'rb').read())" "%ALINA_ENGINE%" >nul 2>nul
if errorlevel 1 goto :invalid_engine
rem --- Moteur push fast-forward ---
set "ALINA_FF=%ALINA_ROOT%tools\alina_push_fastforward.py"
if not exist "%ALINA_FF%" goto :missing_ff
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% -c "import ast,sys; ast.parse(open(sys.argv[1],'rb').read())" "%ALINA_FF%" >nul 2>nul
if errorlevel 1 goto :missing_ff
rem --- Moteur shards ---
set "ALINA_SHARDS_ENGINE=%ALINA_ROOT%tools\sync_complete_clone.py"
if not exist "%ALINA_SHARDS_ENGINE%" goto :missing_shards_engine
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% -c "import ast,sys; ast.parse(open(sys.argv[1],'rb').read())" "%ALINA_SHARDS_ENGINE%" >nul 2>nul
if errorlevel 1 goto :missing_shards_engine
echo [35%%] [LANCEUR 4/8] Moteurs code, push-ff et shards valides

if "%ALINA_SKIP_CODE%"=="1" goto :phase_b
if "%ALINA_DRYRUN%"=="1" goto :phase_a2

rem --- PHASE A : commit local (best-effort, non bloquant) ---
echo.
echo [45%%] [LANCEUR 5/8] PHASE A - checkpoint local (commit sans push)
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% "%ALINA_ENGINE%" --root "%ALINA_ROOT%." --git "%HYPERSMART_GIT%" --wip-only
if errorlevel 1 echo [55%%] [A] moteur de commit a signale un probleme ; le push ne poussera que ce qui est deja commite.

:phase_a2
rem --- PHASE A2 : push fast-forward (bloquant) ---
echo.
echo [60%%] [LANCEUR 6/8] PHASE A2 - push fast-forward sur origin/main
set "ALINA_FF_ARGS="
if "%ALINA_DRYRUN%"=="1" set "ALINA_FF_ARGS=--dry-run"
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% "%ALINA_FF%" --git "%HYPERSMART_GIT%" %ALINA_FF_ARGS%
set "RC_FF=%ERRORLEVEL%"
if not "%RC_FF%"=="0" goto :ff_failed
if "%ALINA_DRYRUN%"=="1" echo [85%%] [DRY-RUN] commit construit et verifie ; aucun push effectue.
if not "%ALINA_DRYRUN%"=="1" echo [85%%] [OK] Code pousse sur origin/main.
if "%ALINA_DRYRUN%"=="1" goto :finish_ok

:phase_b
if "%ALINA_SKIP_SHARDS%"=="1" goto :skip_shards
echo.
echo [90%%] [LANCEUR 7/8] PHASE B - AlinaSync (shards SAFE)
echo        Arguments : %ALINA_SHARDS_ARGS%
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% "%ALINA_SHARDS_ENGINE%" %ALINA_SHARDS_ARGS%
set "RC_SHARDS=%ERRORLEVEL%"
if not "%RC_SHARDS%"=="0" goto :shards_failed
echo [98%%] [OK] Phase B terminee.
goto :finish_ok

:skip_shards
echo [90%%] [LANCEUR 7/8] PHASE B - ignoree
goto :finish_ok

:finish_ok
set "RC=0"
goto :finish

:bad_option
echo [NO_GO] Option inconnue : %~1  (voir --help)
set "RC=2"
goto :finish

:help
echo Usage : POUSSER-GITHUB-FORCE.cmd [option]
echo.
echo  (defaut)         commit local + push fast-forward + shards preflight
echo  --dry-run        construit le commit, verifie, NE POUSSE PAS
echo  --code-only      commit + push, pas de phase shards
echo  --shards-only    AlinaSync seul, pas de code
echo  --download-safe  + telecharge SAFE replayable (plafond 256 GiB)
echo  --all-safe       + telecharge tout SAFE sans plafond
echo  --unpack-safe    + telecharge et decompresse JSONL
echo  --prune-cache    purge le cache verifie inutilise
echo  --catalog-budget compta offline SAFE/PARTIAL/REJECT, aucun reseau
echo.
echo  Aucun force-push, reset, clean, stash ou suppression silencieuse.
set "RC=0"
goto :finish

:bad_location
echo [NO_GO] Impossible d'ouvrir le dossier du CMD.
set "RC=3"
goto :finish
:missing_git
echo [NO_GO] Git introuvable.
set "RC=30"
goto :finish
:missing_python
echo [NO_GO] Python 3.11 ou plus requis.
set "RC=31"
goto :finish
:missing_engine
echo [NO_GO] Moteur de commit manquant : tools\alina_git_code_sync.py
set "RC=32"
goto :finish
:invalid_engine
echo [NO_GO] Moteur de commit invalide (syntaxe).
set "RC=33"
goto :finish
:missing_ff
echo [NO_GO] Moteur push fast-forward manquant/invalide : tools\alina_push_fastforward.py
set "RC=34"
goto :finish
:missing_shards_engine
echo [NO_GO] Moteur shards manquant/invalide : tools\sync_complete_clone.py
set "RC=35"
goto :finish
:ff_failed
echo.
echo [NO_GO] Push fast-forward echoue avec code %RC_FF%. Aucune operation de force.
echo         Les lignes [FF] ci-dessus donnent la cause exacte.
echo         Ton HEAD local est sauvegarde dans la ref refs/alina/local-work.
set "RC=%RC_FF%"
goto :finish
:shards_failed
echo.
echo [NO_GO] Phase B (shards) echouee avec code %RC_SHARDS%.
echo         Le code a deja ete pousse (Phase A2 OK).
set "RC=%RC_SHARDS%"
goto :finish

:finish
echo.
echo [100%%] [LANCEUR 8/8] Fin du lanceur - code retour %RC%
if exist "%ALINA_ROOT%runtime\recovery\full\SYNC_REPORT.json" echo Rapport shards: %ALINA_ROOT%runtime\recovery\full\SYNC_REPORT.json
if /I "%HYPERSMART_PUSH_NO_PAUSE%"=="1" goto :finish_cleanup
pause
:finish_cleanup
popd
endlocal & exit /b %RC%
