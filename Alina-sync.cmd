@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || (
  echo ALINA_SYNC_FAIL: cannot open repository directory.
  exit /b 2
)
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "GIT_LFS_SKIP_SMUDGE=1"
rem Updates canonical main fast-forward only, then verifies every published Release.
rem Never discards local tracked changes or invokes an LFS pull.
if exist "%~dp0tools\python\python.exe" (
  "%~dp0tools\python\python.exe" -c "import sys; sys.exit(sys.version_info[:2] < (3, 10))" >nul 2>nul && goto :embedded
)
where py >nul 2>nul && py -3 -c "import sys; sys.exit(sys.version_info[:2] < (3, 10))" >nul 2>nul && goto :pylauncher
where python >nul 2>nul && python -c "import sys; sys.exit(sys.version_info[:2] < (3, 10))" >nul 2>nul && goto :system
echo ALINA_SYNC_FAIL: Python 3.10 or newer is required.
exit /b 2

:embedded
"%~dp0tools\python\python.exe" tools\sync_alina.py %*
exit /b %ERRORLEVEL%

:pylauncher
py -3 tools\sync_alina.py %*
exit /b %ERRORLEVEL%

:system
python tools\sync_alina.py %*
exit /b %ERRORLEVEL%
