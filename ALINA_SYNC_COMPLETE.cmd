@echo off
setlocal EnableExtensions DisableDelayedExpansion
cd /d "%~dp0" || (
  echo ALINA_SYNC_FAIL: cannot open the repository directory.
  exit /b 2
)
set "GIT_LFS_SKIP_SMUDGE=1"
if exist "%~dp0tools\python\python.exe" (
  "%~dp0tools\python\python.exe" -c "import sys; sys.exit(sys.version_info[:2] < (3, 10))" >nul 2>nul && goto :embedded
)
where py >nul 2>nul && py -3 -c "import sys; sys.exit(sys.version_info[:2] < (3, 10))" >nul 2>nul && goto :pylauncher
where python >nul 2>nul && python -c "import sys; sys.exit(sys.version_info[:2] < (3, 10))" >nul 2>nul && goto :system
echo ALINA_SYNC_FAIL: Python 3.10 or newer is required.
exit /b 2
:embedded
"%~dp0tools\python\python.exe" tools\sync_complete_clone.py %*
exit /b %ERRORLEVEL%
:pylauncher
py -3 tools\sync_complete_clone.py %*
exit /b %ERRORLEVEL%
:system
python tools\sync_complete_clone.py %*
exit /b %ERRORLEVEL%
