@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
pushd "%~dp0" >nul 2>nul
if errorlevel 1 goto :bad_location

rem ============================================================
rem  ALINA SMART FLOW - lanceur local unique
rem  - appelle les moteurs canoniques du depot (pas de copie embarquee)
rem  - code : tools\alina_git_code_sync.py
rem  - SAFE : tools\sync_complete_clone.py
rem  - AUCUN PUSH FORCE, reset, clean, stash ou suppression
rem  - AUCUN TELECHARGEMENT DE SHARDS sans option explicite
rem ============================================================
set "ALINA_ROOT=%~dp0"
set "ALINA_MODE=all"
set "ALINA_CODE_ARGS="
set "ALINA_SHARDS_ARGS=--download-safe --all-safe"
set "ALINA_SKIP_UPDATE=0"
set "RC=1"

if /I "%~1"=="--help" goto :help
if /I "%~1"=="-h" goto :help

:parse_args
if "%~1"=="" goto :args_done
if /I "%~1"=="--dry-run" set "ALINA_CODE_ARGS=--dry-run"&set "ALINA_MODE=dry"&shift&goto :parse_args
if /I "%~1"=="--wip-only" set "ALINA_CODE_ARGS=--wip-only"&set "ALINA_MODE=code"&shift&goto :parse_args
if /I "%~1"=="--promote-current-to-main" set "ALINA_CODE_ARGS=--promote-current-to-main"&set "ALINA_MODE=code"&shift&goto :parse_args
if /I "%~1"=="--code-only" set "ALINA_MODE=code"&shift&goto :parse_args
if /I "%~1"=="--shards-only" set "ALINA_MODE=shards"&shift&goto :parse_args
if /I "%~1"=="--preflight" set "ALINA_MODE=shards"&set "ALINA_SHARDS_ARGS=--preflight-only"&shift&goto :parse_args
if /I "%~1"=="--preflight-only" set "ALINA_MODE=shards"&set "ALINA_SHARDS_ARGS=--preflight-only"&shift&goto :parse_args
if /I "%~1"=="--download-safe" set "ALINA_MODE=shards"&set "ALINA_SHARDS_ARGS=--download-safe --max-download-gib 256"&shift&goto :parse_args
if /I "%~1"=="--all-safe" set "ALINA_MODE=shards"&set "ALINA_SHARDS_ARGS=--download-safe --all-safe"&shift&goto :parse_args
if /I "%~1"=="--unpack-safe" set "ALINA_MODE=shards"&set "ALINA_SHARDS_ARGS=--download-safe --unpack-safe --max-download-gib 256"&shift&goto :parse_args
if /I "%~1"=="--prune-cache" set "ALINA_MODE=shards"&set "ALINA_SHARDS_ARGS=--prune-cache-only"&shift&goto :parse_args
if /I "%~1"=="--prune-cache-only" set "ALINA_MODE=shards"&set "ALINA_SHARDS_ARGS=--prune-cache-only"&shift&goto :parse_args
if /I "%~1"=="--catalog-budget" set "ALINA_MODE=shards"&set "ALINA_SHARDS_ARGS=--catalog-budget"&shift&goto :parse_args
if /I "%~1"=="--skip-update" set "ALINA_SKIP_UPDATE=1"&shift&goto :parse_args
goto :bad_option

:args_done
if "%ALINA_SKIP_UPDATE%"=="1" set "ALINA_SHARDS_ARGS=%ALINA_SHARDS_ARGS% --skip-update"

rem --- Git ---
set "HYPERSMART_GIT="
if exist "%ALINA_ROOT%tools\git\cmd\git.exe" set "HYPERSMART_GIT=%ALINA_ROOT%tools\git\cmd\git.exe"
if not defined HYPERSMART_GIT if exist "%ProgramFiles%\Git\cmd\git.exe" set "HYPERSMART_GIT=%ProgramFiles%\Git\cmd\git.exe"
if not defined HYPERSMART_GIT if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe" set "HYPERSMART_GIT=%LOCALAPPDATA%\Programs\Git\cmd\git.exe"
if not defined HYPERSMART_GIT for %%G in (git.exe) do if not "%%~$PATH:G"=="" set "HYPERSMART_GIT=%%~$PATH:G"
if not defined HYPERSMART_GIT goto :missing_git

rem --- Python ---
set "HYPERSMART_PYTHON="
set "PYARGS="
if exist "%ALINA_ROOT%tools\python\python.exe" set "HYPERSMART_PYTHON=%ALINA_ROOT%tools\python\python.exe"
if not defined HYPERSMART_PYTHON (
  where py.exe >nul 2>nul
  if not errorlevel 1 (
    set "HYPERSMART_PYTHON=py"
    set "PYARGS=-3"
  )
)
if not defined HYPERSMART_PYTHON (
  where python.exe >nul 2>nul
  if not errorlevel 1 set "HYPERSMART_PYTHON=python"
)
if not defined HYPERSMART_PYTHON goto :missing_python
"%HYPERSMART_PYTHON%" %PYARGS% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto :missing_python

set "ALINA_ENGINE=%ALINA_ROOT%tools\alina_git_code_sync.py"
set "ALINA_SHARDS_ENGINE=%ALINA_ROOT%tools\sync_complete_clone.py"
if not exist "%ALINA_ENGINE%" goto :missing_engine
if not exist "%ALINA_SHARDS_ENGINE%" goto :missing_shards_engine
"%HYPERSMART_PYTHON%" %PYARGS% -c "import ast,sys; ast.parse(open(sys.argv[1],'rb').read())" "%ALINA_ENGINE%" >nul 2>nul
if errorlevel 1 goto :invalid_engine
"%HYPERSMART_PYTHON%" %PYARGS% -c "import ast,sys; ast.parse(open(sys.argv[1],'rb').read())" "%ALINA_SHARDS_ENGINE%" >nul 2>nul
if errorlevel 1 goto :missing_shards_engine

echo ============================================================
echo  ALINA SMART FLOW - modules canoniques du depot
echo  Code : tools\alina_git_code_sync.py
echo  SAFE : tools\sync_complete_clone.py
echo  Aucun force-push, reset, clean, stash ou suppression
echo ============================================================
if /I "%ALINA_MODE%"=="dry" echo Mode : DRY-RUN (aucune publication)
if /I "%ALINA_MODE%"=="code" echo Mode : CODE uniquement
if /I "%ALINA_MODE%"=="shards" echo Mode : SAFE uniquement
echo.

"%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ROOT%tools\cmd_progress.py" start > "%TEMP%\alina_cmd_start.tmp" 2>nul
set /p ALINA_CMD_START=<"%TEMP%\alina_cmd_start.tmp"
if /I "%ALINA_MODE%"=="shards" goto :run_shards
"%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ROOT%tools\cmd_progress.py" phase "Synchronisation code vers GitHub" 1 2
"%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ENGINE%" --root "%ALINA_ROOT%." --git "%HYPERSMART_GIT%" %ALINA_CODE_ARGS%
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :finish
if /I "%ALINA_MODE%"=="dry" goto :finish
if /I "%ALINA_MODE%"=="code" goto :finish
echo [OK] Code termine et verifie.

:run_shards
if /I "%ALINA_MODE%"=="all" "%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ROOT%tools\cmd_progress.py" phase "Telechargement SAFE (tous les shards)" 2 2
if /I "%ALINA_MODE%"=="shards" "%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ROOT%tools\cmd_progress.py" phase "Operation SAFE" 1 1
"%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_SHARDS_ENGINE%" %ALINA_SHARDS_ARGS%
set "RC=%ERRORLEVEL%"
goto :finish

:help
echo Usage : POUSSER-GITHUB-FORCE.cmd [options]
echo.
echo  (defaut)              code push fast-forward + telechargement SAFE complet
echo  --dry-run             code en lecture seule, aucune publication
echo  --code-only           synchronisation du code uniquement
echo  --shards-only         operation SAFE uniquement
echo  --preflight-only      inventaire SAFE sans telechargement
echo  --download-safe       telechargement SAFE plafonne a 256 GiB
echo  --all-safe            telechargement SAFE sans plafond
echo  --unpack-safe         telechargement SAFE + decompression JSONL
echo  --prune-cache         purge du cache verifie inutilise
echo  --catalog-budget      comptabilite SAFE offline, sans reseau
echo  --skip-update         SAFE sans fetch ni fusion Git
echo.
echo Le lanceur appelle les modules canoniques du depot; aucune copie Python embarquee.
echo Aucun force-push, reset, clean, stash ou suppression silencieuse.
set "RC=0"
goto :finish

:bad_option
echo [NO_GO] Option inconnue : %~1 (voir --help)
set "RC=2"
goto :finish
:bad_location
echo [NO_GO] Impossible d'ouvrir le dossier du depot.
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
echo [NO_GO] Module manquant : tools\alina_git_code_sync.py
set "RC=34"
goto :finish
:missing_shards_engine
echo [NO_GO] Module manquant/invalide : tools\sync_complete_clone.py
set "RC=35"
goto :finish
:invalid_engine
echo [NO_GO] Syntaxe invalide dans tools\alina_git_code_sync.py.
set "RC=36"
goto :finish

:finish
echo.
"%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ROOT%tools\cmd_progress.py" elapsed
echo [FIN] Lanceur termine - code retour %RC%
if /I not "%HYPERSMART_PUSH_NO_PAUSE%"=="1" pause
popd
endlocal & exit /b %RC%
