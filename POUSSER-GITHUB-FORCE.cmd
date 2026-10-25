@echo off
chcp 65001 >nul
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0"
set "GIT_LFS_SKIP_SMUDGE=1"
set "HYPERSMART_GIT=%~dp0tools\git\cmd\git.exe"
if exist "%HYPERSMART_GIT%" goto :git_ready
for %%G in (git.exe) do if not "%%~$PATH:G"=="" set "HYPERSMART_GIT=%%~$PATH:G"
if exist "%HYPERSMART_GIT%" goto :git_ready

echo [INFO] Git absent : preparation du Git portable officiel (PAS de shards).
set "HYPERSMART_NO_PAUSE=1"
call "%~dp0PREPARER_GIT_PORTABLE.cmd"
if errorlevel 1 (
  echo [NO_GO] Installation de Git impossible. Rien n'a ete pousse.
  set "RC=30"
  goto :finish
)
set "HYPERSMART_GIT=%~dp0tools\git\cmd\git.exe"
if not exist "%HYPERSMART_GIT%" (
  set "RC=30"
  goto :finish
)

:git_ready
set "HYPERSMART_PYTHON="
set "HYPERSMART_PY_ARGS="
if exist "%~dp0tools\python\python.exe" set "HYPERSMART_PYTHON=%~dp0tools\python\python.exe"
if defined HYPERSMART_PYTHON goto :python_ready
where py.exe >nul 2>nul
if not errorlevel 1 (
  set "HYPERSMART_PYTHON=py"
  set "HYPERSMART_PY_ARGS=-3"
  goto :python_ready
)
where python.exe >nul 2>nul
if not errorlevel 1 set "HYPERSMART_PYTHON=python"
if not defined HYPERSMART_PYTHON (
  echo [NO_GO] Python 3 est requis pour une reconciliation sure.
  echo Aucun fichier local ni GitHub n'a ete modifie.
  set "RC=31"
  goto :finish
)

:python_ready
if not exist "%~dp0tools\alina_git_code_sync.py" (
  echo [NO_GO] tools\alina_git_code_sync.py absent. Actualisez ce depot manuellement.
  set "RC=32"
  goto :finish
)
if /I "%~1"=="--portable-self-check" goto :portable_self_check

set "SYNC_MODE="
if /I "%~1"=="--dry-run" set "SYNC_MODE=--dry-run"
if /I "%~1"=="dry-run" set "SYNC_MODE=--dry-run"
if /I "%~1"=="--wip-only" set "SYNC_MODE=--wip-only"
if /I "%~1"=="wip" set "SYNC_MODE=--wip-only"
if not "%~1"=="" if not defined SYNC_MODE (
  echo [NO_GO] Option inconnue : %~1
  echo Utilisation : POUSSER-GITHUB-FORCE.cmd [--dry-run ^| --wip-only]
  set "RC=2"
  goto :finish
)
echo =============================================================
echo  ALINA SMART FLOW — SYNC GITHUB BIDIRECTIONNEL
echo  GitHub main + modifications locales Codex/Claude
echo  Code Git seulement : ZERO telechargement des shards SAFE
echo  Aucun push force, aucun reset ni suppression de code
echo =============================================================
echo.
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% "%~dp0tools\alina_git_code_sync.py" --root "%~dp0." --git "%HYPERSMART_GIT%" %SYNC_MODE%
set "RC=%ERRORLEVEL%"
if "%RC%"=="0" (
  echo [OK] Verification terminee. Consulter le journal Git Sync.
) else (
  echo [NO_GO] Synchronisation incomplete, aucune perte volontaire. Code %RC%.
  echo Consultez runtime\reports\git-sync\LAST_SYNC.json
)

:portable_self_check
"%HYPERSMART_GIT%" --version >nul 2>nul
if errorlevel 1 (
  set "RC=33"
  goto :finish
)
"%HYPERSMART_PYTHON%" %HYPERSMART_PY_ARGS% -c "import ast, pathlib; ast.parse(pathlib.Path('tools/alina_git_code_sync.py').read_bytes())"
set "RC=%ERRORLEVEL%"
if not "%RC%"=="0" goto :finish
echo PORTABLE_GITHUB_PUSH_CHECK_OK

:finish
if /I not "%HYPERSMART_PUSH_NO_PAUSE%"=="1" pause
endlocal & exit /b %RC%
