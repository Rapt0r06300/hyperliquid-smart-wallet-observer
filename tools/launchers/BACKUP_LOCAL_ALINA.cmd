@echo off
setlocal
for %%I in ("%~dp0..\..") do set "ALINA_PROJECT_ROOT=%%~fI"
cd /d "%ALINA_PROJECT_ROOT%" || exit /b 1
cd /d "%ALINA_PROJECT_ROOT%\"
where python >nul 2>nul || (
  echo ALINA_LOCAL_SNAPSHOT_FAIL: Python 3 is required.
  exit /b 2
)
where gh >nul 2>nul || (
  echo ALINA_LOCAL_SNAPSHOT_FAIL: GitHub CLI gh is required and must be authenticated.
  exit /b 2
)
python tools\publish_local_recovery_snapshot.py --root .
exit /b %ERRORLEVEL%
