@echo off
REM HyperSmart official portable environment.
REM The sole interpreter is tools\python\python.exe. No venv/system fallback.

for %%I in ("%~dp0..") do set "HYPERSMART_PROJECT_ROOT=%%~fI"
set "HYPERSMART_PYTHON="
set "HYPERSMART_EMBED_PYTHON=%HYPERSMART_PROJECT_ROOT%\tools\python\python.exe"

REM Non-destructive one-time migration of the historical embedded runtime.
if not exist "%HYPERSMART_EMBED_PYTHON%" if exist "%HYPERSMART_PROJECT_ROOT%\portable_runtime\python\python.exe" (
  echo   [PORTABILITE] Migration de l'ancien runtime vers tools\python...
  "%HYPERSMART_PROJECT_ROOT%\portable_runtime\python\python.exe" "%HYPERSMART_PROJECT_ROOT%\tools\portable_runtime.py" --root "%HYPERSMART_PROJECT_ROOT%" migrate >nul
  if errorlevel 1 goto :migration_failed
  if not exist "%HYPERSMART_EMBED_PYTHON%" goto :migration_failed
)

if not exist "%HYPERSMART_EMBED_PYTHON%" goto :missing
set "HYPERSMART_PYTHON=%HYPERSMART_EMBED_PYTHON%"
set "HYPERSMART_PYTHON_SOURCE=embedded-tools-python"
set "PATH=%HYPERSMART_PROJECT_ROOT%\tools\python;%HYPERSMART_PROJECT_ROOT%\tools\python\Scripts;%PATH%"
set "PYTHONPATH=%HYPERSMART_PROJECT_ROOT%\src;%HYPERSMART_PROJECT_ROOT%;%HYPERSMART_PROJECT_ROOT%\tools"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"
set "PIP_USER=0"
set "PIP_NO_INDEX=1"
set "HYPERSMART_WHEELHOUSE=%HYPERSMART_PROJECT_ROOT%\tools\wheelhouse"
set "PIP_FIND_LINKS=%HYPERSMART_WHEELHOUSE%"
set "HYPERSMART_RUNTIME_ROOT=%HYPERSMART_PROJECT_ROOT%"
exit /b 0

:migration_failed
echo   [PORTABILITE] ECHEC de migration. L'ancien runtime reste intact.
exit /b 31

:missing
echo.
echo   [PORTABILITE] ECHEC : tools\python\python.exe est absent.
echo   Execute tools\preparer_python_portable.cmd sur un PC Windows x64 connecte.
echo   Aucun repli portable_runtime, venv ou Python systeme n'est autorise.
echo.
exit /b 30
