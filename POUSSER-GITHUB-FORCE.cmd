@echo off
setlocal EnableExtensions DisableDelayedExpansion
set "ALINA_LAUNCH_RUN_ID=%DATE%_%TIME%_%RANDOM%_%RANDOM%"
set "ALINA_LAUNCH_MODE=argument-dispatch"
set "ALINA_LAUNCH_PYTHON=unresolved"
chcp 65001 >nul
call "%~dp0tools\launcher_log.cmd" "POUSSER-GITHUB-FORCE" START preflight "repo-and-options" ""
set "ALINA_PUSHD_OK=0"
pushd "%~dp0" >nul 2>nul
if errorlevel 1 goto :bad_location
set "ALINA_PUSHD_OK=1"

rem ============================================================
rem  ALINA SMART FLOW - lanceur local unique
rem  - appelle les moteurs canoniques du depot (pas de copie embarquee)
rem  - code : tools\alina_git_code_sync.py
rem  - SAFE : tools\sync_complete_clone.py
rem  - AUCUN PUSH FORCE, reset, clean, stash ou suppression
rem  - AUCUN TELECHARGEMENT DE SHARDS sans option explicite
rem ============================================================
set "ALINA_ROOT=%~dp0"
set "ALINA_MODE=code"
set "ALINA_CODE_ARGS="
set "ALINA_SHARDS_ARGS=--download-safe --all-safe"
set "ALINA_SKIP_UPDATE=0"
set "ALINA_COPY_VAULT_ONLY="
set "ALINA_ENGINE_RAN=0"
set "RC=1"

if /I "%~1"=="--help" goto :help
if /I "%~1"=="-h" goto :help

:parse_args
if "%~1"=="" goto :args_done
if /I "%~1"=="--portable-self-check" set "ALINA_MODE=self-check"&shift&goto :parse_args
if /I "%~1"=="--self-check" set "ALINA_MODE=self-check"&shift&goto :parse_args
if /I "%~1"=="--dry-run" set "ALINA_CODE_ARGS=--dry-run"&set "ALINA_MODE=dry"&shift&goto :parse_args
if /I "%~1"=="--wip-only" set "ALINA_CODE_ARGS=--wip-only"&set "ALINA_MODE=code"&shift&goto :parse_args
if /I "%~1"=="--promote-current-to-main" set "ALINA_CODE_ARGS=--promote-current-to-main"&set "ALINA_MODE=code"&shift&goto :parse_args
if /I "%~1"=="--code-only" set "ALINA_MODE=code"&shift&goto :parse_args
if /I "%~1"=="--full" set "ALINA_MODE=all"&shift&goto :parse_args
if /I "%~1"=="--code-plus-safe" set "ALINA_MODE=all"&shift&goto :parse_args
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
if /I "%~1"=="--copy-vault-only" set "ALINA_MODE=shards"&set "ALINA_COPY_VAULT_ONLY=--copy-vault-only"&shift&goto :parse_args
goto :bad_option

:args_done
if "%ALINA_SKIP_UPDATE%"=="1" set "ALINA_SHARDS_ARGS=%ALINA_SHARDS_ARGS% --skip-update"
if defined ALINA_COPY_VAULT_ONLY set "ALINA_SHARDS_ARGS=%ALINA_SHARDS_ARGS% %ALINA_COPY_VAULT_ONLY%"
if /I "%ALINA_MODE%"=="code" (set "ALINA_LAUNCH_MODE=code-sync") else if /I "%ALINA_MODE%"=="shards" (set "ALINA_LAUNCH_MODE=safe-data-sync") else if /I "%ALINA_MODE%"=="all" (set "ALINA_LAUNCH_MODE=code-plus-safe") else set "ALINA_LAUNCH_MODE=%ALINA_MODE%"
call "%ALINA_ROOT%tools\launcher_log.cmd" "POUSSER-GITHUB-FORCE" STEP preflight "selected-mode-and-engine-validation" "0"

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
set "ALINA_LAUNCH_PYTHON=%HYPERSMART_PYTHON% %PYARGS%"
set "ALINA_LAUNCH_OUTPUT_LOG=runtime/reports/git-sync/LAST_SYNC.json"
"%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ROOT%tools\cmd_progress.py" percent 3 "Verification de Git et Python"
"%HYPERSMART_PYTHON%" %PYARGS% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto :missing_python

set "ALINA_ENGINE_REQUIRED_BUILD=2026-11-12-compact-fresh-index-v15"
set "ALINA_ENGINE=%ALINA_ROOT%tools\alina_git_code_sync.py"
set "ALINA_SHARDS_ENGINE=%ALINA_ROOT%tools\sync_complete_clone.py"
if not exist "%ALINA_ENGINE%" goto :missing_engine
if not exist "%ALINA_SHARDS_ENGINE%" goto :missing_shards_engine
"%HYPERSMART_PYTHON%" %PYARGS% -c "import ast,sys; ast.parse(open(sys.argv[1],'rb').read())" "%ALINA_ENGINE%" >nul 2>nul
if errorlevel 1 goto :invalid_engine
"%HYPERSMART_PYTHON%" %PYARGS% -c "import ast,sys; n=ast.parse(open(sys.argv[1],'rb').read()).body; v=[x.value.value for x in n if isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='GIT_SYNC_ENGINE_BUILD' for t in x.targets) and isinstance(x.value,ast.Constant)]; sys.exit(0 if v==[sys.argv[2]] else 3)" "%ALINA_ENGINE%" "%ALINA_ENGINE_REQUIRED_BUILD%"
if errorlevel 1 goto :engine_build_mismatch
"%HYPERSMART_PYTHON%" %PYARGS% -c "import ast,sys; ast.parse(open(sys.argv[1],'rb').read())" "%ALINA_SHARDS_ENGINE%" >nul 2>nul
if errorlevel 1 goto :missing_shards_engine
call "%ALINA_ROOT%tools\launcher_log.cmd" "POUSSER-GITHUB-FORCE" RESULT preflight "git-python-and-canonical-engines-valid" "0"
"%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ROOT%tools\cmd_progress.py" percent 8 "Moteurs canoniques valides"
if /I "%ALINA_MODE%"=="self-check" goto :self_check

echo ============================================================
echo  ALINA SMART FLOW - modules canoniques du depot
echo  Code : tools\alina_git_code_sync.py
echo  SAFE : tools\sync_complete_clone.py
echo  Aucun force-push, reset, clean, stash ou suppression
echo ============================================================
echo Execution : %ALINA_LAUNCH_RUN_ID%
echo Rapport   : runtime\reports\git-sync\LAST_SYNC.json
if /I "%ALINA_MODE%"=="dry" echo Mode : DRY-RUN (aucune publication)
if /I "%ALINA_MODE%"=="code" echo Mode : CODE uniquement
if /I "%ALINA_MODE%"=="shards" echo Mode : SAFE uniquement
echo.

rem Le moteur effectue deja ses reprises internes bornees. Le CMD ne relance
rem une seconde fois que pour une panne explicitement transitoire. Un conflit,
rem un refus de securite ou une configuration invalide s'arrete immediatement.
set "ALINA_MAX_ATTEMPTS=2"
"%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ROOT%tools\cmd_progress.py" start > "%TEMP%\alina_cmd_start.tmp" 2>nul
set /p ALINA_CMD_START=<"%TEMP%\alina_cmd_start.tmp"
if /I "%ALINA_MODE%"=="shards" goto :run_shards
set "ALINA_PROGRESS_OFFSET=10"
set "ALINA_PROGRESS_SPAN=85"
if /I "%ALINA_MODE%"=="all" set "ALINA_PROGRESS_SPAN=55"
"%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ROOT%tools\cmd_progress.py" percent 10 "Demarrage de la synchronisation du code"

set "ALINA_ATTEMPT=0"
:code_attempt
set /a ALINA_ATTEMPT+=1
call :ensure_no_stale_lock
call "%ALINA_ROOT%tools\launcher_log.cmd" "POUSSER-GITHUB-FORCE" STEP git-code-sync "attempt-%ALINA_ATTEMPT%-of-%ALINA_MAX_ATTEMPTS%" ""
echo [TENTATIVE] Synchronisation code %ALINA_ATTEMPT%/%ALINA_MAX_ATTEMPTS%
set "ALINA_ENGINE_RAN=1"
"%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ENGINE%" --root "%ALINA_ROOT%." --git "%HYPERSMART_GIT%" %ALINA_CODE_ARGS%
set "RC=%ERRORLEVEL%"
call "%ALINA_ROOT%tools\launcher_log.cmd" "POUSSER-GITHUB-FORCE" RESULT git-code-sync "attempt-%ALINA_ATTEMPT%-of-%ALINA_MAX_ATTEMPTS%" "%RC%"
if "%RC%"=="0" goto :code_ok
if %ALINA_ATTEMPT% GEQ %ALINA_MAX_ATTEMPTS% goto :finish
"%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ROOT%tools\cmd_progress.py" retry-decision "%ALINA_ROOT%runtime\reports\git-sync\LAST_SYNC.json" "%RC%"
if errorlevel 1 goto :finish
echo [AUTO-REPAIR] Incident transitoire confirme; nouvel essai dans 2s...
timeout /t 2 /nobreak >nul 2>nul
goto :code_attempt
:code_ok
if /I "%ALINA_MODE%"=="dry" goto :finish
if /I "%ALINA_MODE%"=="code" goto :finish
echo [OK] Code termine et verifie.
"%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ROOT%tools\cmd_progress.py" percent 65 "Code GitHub termine; passage aux donnees SAFE"

:run_shards
if /I "%ALINA_MODE%"=="shards" "%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ROOT%tools\cmd_progress.py" percent 10 "Demarrage de l'operation SAFE"
set "ALINA_ATTEMPT=0"
:shards_attempt
set /a ALINA_ATTEMPT+=1
call :ensure_no_stale_lock
call "%ALINA_ROOT%tools\launcher_log.cmd" "POUSSER-GITHUB-FORCE" STEP safe-data-sync "attempt-%ALINA_ATTEMPT%-of-%ALINA_MAX_ATTEMPTS%" ""
if /I "%ALINA_MODE%"=="all" "%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ROOT%tools\cmd_progress.py" percent 70 "Telechargement SAFE explicite"
if /I "%ALINA_MODE%"=="shards" "%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ROOT%tools\cmd_progress.py" percent 35 "Operation SAFE en cours"
"%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_SHARDS_ENGINE%" %ALINA_SHARDS_ARGS%
set "RC=%ERRORLEVEL%"
call "%ALINA_ROOT%tools\launcher_log.cmd" "POUSSER-GITHUB-FORCE" RESULT safe-data-sync "attempt-%ALINA_ATTEMPT%-of-%ALINA_MAX_ATTEMPTS%" "%RC%"
if "%RC%"=="0" goto :finish
if %ALINA_ATTEMPT% GEQ %ALINA_MAX_ATTEMPTS% goto :finish
echo [AUTO-REPAIR] Operation SAFE echouee ^(code %RC%^); nouvel essai borne dans 2s...
timeout /t 2 /nobreak >nul 2>nul
goto :shards_attempt

:self_check
rem Entirely offline: real Git/Python lookup plus source AST and engine build gates
rem above have completed. Never fetch, commit, restore SAFE, or contact a broker.
echo PORTABLE_GITHUB_PUSH_CHECK_OK
"%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ROOT%tools\cmd_progress.py" percent 100 "Autocontrole termine"
set "RC=0"
goto :finish

:help
echo Usage : POUSSER-GITHUB-FORCE.cmd [options]
echo.
echo  (defaut)              code push rapide SEUL ^(pas de telechargement 153 Go^)
echo  --dry-run             code en lecture seule, aucune publication
echo  --code-only           synchronisation du code uniquement ^(identique au defaut^)
echo  --full                code push PUIS telechargement SAFE complet ^(ancien defaut^)
echo  --shards-only         operation SAFE uniquement
echo  --preflight-only      inventaire SAFE sans telechargement
echo  --download-safe       telechargement SAFE plafonne a 256 GiB
echo  --all-safe            telechargement SAFE sans plafond
echo  --unpack-safe         telechargement SAFE + decompression JSONL
echo  --prune-cache         purge du cache verifie inutilise
echo  --catalog-budget      comptabilite SAFE offline, sans reseau
echo  --skip-update         SAFE sans fetch ni fusion Git
echo  --self-check         verification locale Git/Python/moteurs, sans publication
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

rem --- 12/11/2026 : un ECART DE VERSION s'annoncait « Syntaxe invalide ». Message mensonger, et
rem     piege de diagnostic : on cherchait une faute de frappe dans un fichier parfaitement valide.
rem     (Mesure du jour : syntaxe OK avec le Python du lanceur ; c'etait la broche restee en v13
rem     alors que le module etait passe en v14.) Un motif d'echec doit NOMMER sa vraie cause. ---
:engine_build_mismatch
echo [NO_GO] Version du moteur de poussee incompatible ^(ce n'est PAS une erreur de syntaxe^).
echo         Attendu par ce lanceur   : %ALINA_ENGINE_REQUIRED_BUILD%
"%HYPERSMART_PYTHON%" %PYARGS% -c "import ast,sys;n=ast.parse(open(sys.argv[1],'rb').read()).body;v=[x.value.value for x in n if isinstance(x,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='GIT_SYNC_ENGINE_BUILD' for t in x.targets) and isinstance(x.value,ast.Constant)];print('         Trouve dans le module    : ' + (v[0] if v else '(aucune empreinte)'))" "%ALINA_ENGINE%"
echo         Mettre a jour ALINA_ENGINE_REQUIRED_BUILD dans ce .cmd, ou le module.
set "RC=37"
goto :finish

:finish
call "%~dp0tools\launcher_log.cmd" "POUSSER-GITHUB-FORCE" EXIT completion "launcher-finished" "%RC%"
echo.
if "%ALINA_ENGINE_RAN%"=="1" "%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ROOT%tools\cmd_progress.py" summary "%ALINA_ROOT%runtime\reports\git-sync\LAST_SYNC.json" "%RC%"
if "%RC%"=="0" if /I not "%ALINA_MODE%"=="self-check" "%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ROOT%tools\cmd_progress.py" percent 100 "Lanceur termine et resultat verifie"
if defined HYPERSMART_PYTHON "%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_ROOT%tools\cmd_progress.py" elapsed
echo [FIN] Lanceur termine - code retour %RC%
if /I not "%HYPERSMART_PUSH_NO_PAUSE%"=="1" pause
if "%ALINA_PUSHD_OK%"=="1" popd
endlocal & exit /b %RC%

rem ============================================================
rem  Self-healing SUR : supprime un verrou Git index.lock PERIME
rem  (uniquement si AUCUN processus git ne tourne). Jamais de reset,
rem  force, clean ou stash. Un verrou tenu par un git actif est
rem  respecte. Appele via `call`, retourne par `goto :eof`.
rem ============================================================
:ensure_no_stale_lock
if not exist "%ALINA_ROOT%.git\index.lock" goto :eof
tasklist /FI "IMAGENAME eq git.exe" /NH 2>nul | findstr /I "git.exe" >nul 2>nul
if not errorlevel 1 (
  echo [VERROU] Un processus git est actif; verrou respecte ^(pas de suppression^).
  goto :eof
)
echo [AUTO-REPAIR] Verrou Git perime detecte ^(aucun git actif^) -^> suppression securisee.
del /f /q "%ALINA_ROOT%.git\index.lock" >nul 2>nul
goto :eof
