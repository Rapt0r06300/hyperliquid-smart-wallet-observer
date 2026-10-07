@echo off
setlocal
cd /d "%~dp0"
where python >nul 2>nul || (
  echo ALINA_RESTORE_FAIL: Python 3 is required.
  exit /b 2
)
python tools\restore_alina.py --everything --workspace .
exit /b %ERRORLEVEL%
