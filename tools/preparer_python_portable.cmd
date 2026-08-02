@echo off
setlocal EnableExtensions
cd /d "%~dp0.."
set "ROOT=%CD%"
echo.
echo ============================================================
echo   Preparation du runtime PORTABLE HyperSmart (Windows x64)
echo ============================================================
echo   Runtime unique : tools\python\python.exe
echo   Installation   : wheelhouse hors ligne, hashes obligatoires
echo.

echo   [1/3] Verification des entrees de construction...
if not exist "%ROOT%\requirements-portable.txt" endlocal & exit /b 40
if not exist "%ROOT%\tools\wheelhouse\WHEELHOUSE_LOCK.json" endlocal & exit /b 41

echo   [2/3] Construction atomique de tools\python...
powershell -NoProfile -ExecutionPolicy Bypass -File "%ROOT%\tools\install_portable_runtime.ps1" -ProjectRoot "%ROOT%" -Force
if errorlevel 1 (
  echo   [ECHEC] Runtime portable non construit. Aucun OK ne sera affiche.
  endlocal & exit /b 42
)

echo   [3/3] Verification finale sans repli...
call "%ROOT%\tools\portable_env.cmd"
if errorlevel 1 endlocal & exit /b 43
"%HYPERSMART_PYTHON%" "%ROOT%\tools\portable_runtime.py" --root "%ROOT%" check --require-embedded
if errorlevel 1 endlocal & exit /b 44

echo.
echo   [OK] Runtime portable exact et hors ligne pret :
echo        %ROOT%\tools\python\python.exe
echo.
endlocal & exit /b 0
