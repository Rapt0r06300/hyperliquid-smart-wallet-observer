@echo off
setlocal
cd /d "%~dp0"
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
