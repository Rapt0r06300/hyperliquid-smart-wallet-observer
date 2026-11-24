@echo off
setlocal EnableExtensions DisableDelayedExpansion
rem Shared detached watcher for every root launcher. It never searches by a
rem global process name; the Python module verifies the owning PID and command.
set "LL_ROOT=%~dp0.."
for %%I in ("%LL_ROOT%") do set "LL_ROOT=%%~fI"
set "LL_PYTHON="
set "LL_PY_ARGS="
if exist "%LL_ROOT%\tools\python\python.exe" set "LL_PYTHON=%LL_ROOT%\tools\python\python.exe"
if not defined LL_PYTHON if exist "%LL_ROOT%\.venv\Scripts\python.exe" set "LL_PYTHON=%LL_ROOT%\.venv\Scripts\python.exe"
if not defined LL_PYTHON (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "LL_PYTHON=py"
    set "LL_PY_ARGS=-3"
  )
)
if not defined LL_PYTHON (
  where python >nul 2>nul
  if not errorlevel 1 set "LL_PYTHON=python"
)
if not defined LL_PYTHON exit /b 0
start "" /B "%LL_PYTHON%" %LL_PY_ARGS% "%~dp0launcher_lifecycle.py" %* >nul 2>&1
endlocal & exit /b 0
