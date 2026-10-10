@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || (
  echo ALINA_RESTORE_FAIL: cannot open the cloned repository directory.
  exit /b 2
)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
rem Restore is strictly read-only against GitHub. No collector is stopped.
rem The Python restore verifies the canonical SHA-bound catalog and every
rem Release/LFS asset before placing any shard under usable/.
rem Do not force git lfs pull here: space requirements must be preflighted.
if exist "%~dp0tools\python\python.exe" goto :embedded
where py >nul 2>nul && goto :pylauncher
where python >nul 2>nul && goto :system
echo ALINA_RESTORE_FAIL: Python 3 is required (embedded, py -3 or python).
exit /b 2

:embedded
"%~dp0tools\python\python.exe" tools\restore_alina.py --everything --clone-root "." --destination "runtime\recovery\full"
exit /b %ERRORLEVEL%

:pylauncher
py -3 tools\restore_alina.py --everything --clone-root "." --destination "runtime\recovery\full"
exit /b %ERRORLEVEL%

:system
python tools\restore_alina.py --everything --clone-root "." --destination "runtime\recovery\full"
exit /b %ERRORLEVEL%
