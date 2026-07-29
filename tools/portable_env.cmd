@echo off
REM Configure HyperSmart from paths relative to this project directory.
REM Called by LANCER_HYPERSMART.cmd; do not launch this file directly.

for %%I in ("%~dp0..") do set "HYPERSMART_PROJECT_ROOT=%%~fI"
set "HYPERSMART_PORTABLE_RUNTIME=%HYPERSMART_PROJECT_ROOT%\portable_runtime"
set "HYPERSMART_PORTABLE_PYTHON=%HYPERSMART_PORTABLE_RUNTIME%\python\python.exe"
set "HYPERSMART_PYTHON="

if exist "%HYPERSMART_PORTABLE_PYTHON%" (
  set "HYPERSMART_PYTHON=%HYPERSMART_PORTABLE_PYTHON%"
  set "PATH=%HYPERSMART_PORTABLE_RUNTIME%\python;%HYPERSMART_PORTABLE_RUNTIME%\python\Scripts;%PATH%"
  set "HYPERSMART_PYTHON_SOURCE=embedded-portable"
  goto :configured
)

if exist "%HYPERSMART_PROJECT_ROOT%\.venv-portable\Scripts\python.exe" (
  set "HYPERSMART_PYTHON=%HYPERSMART_PROJECT_ROOT%\.venv-portable\Scripts\python.exe"
  set "PATH=%HYPERSMART_PROJECT_ROOT%\.venv-portable\Scripts;%PATH%"
  set "HYPERSMART_PYTHON_SOURCE=local-venv"
  goto :configured
)

where python >nul 2>&1
if errorlevel 1 (
  echo.
  echo   ERREUR PORTABILITE : aucun Python local ou systeme disponible.
  echo   Depuis un PC connecte, execute :
  echo   powershell -ExecutionPolicy Bypass -File tools\install_portable_runtime.ps1
  echo.
  exit /b 30
)

for /f "delims=" %%P in ('where python 2^>nul') do (
  if not defined HYPERSMART_PYTHON set "HYPERSMART_PYTHON=%%P"
)
set "HYPERSMART_PYTHON_SOURCE=system-fallback"

:configured
set "PYTHONPATH=%HYPERSMART_PROJECT_ROOT%\src;%HYPERSMART_PROJECT_ROOT%;%HYPERSMART_PROJECT_ROOT%\tools;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"
set "PIP_USER=0"
set "HYPERSMART_RUNTIME_ROOT=%HYPERSMART_PROJECT_ROOT%"
exit /b 0
