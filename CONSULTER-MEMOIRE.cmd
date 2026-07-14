@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONPATH=src
if "%~1"=="" (
  python tools\consulter_memoire.py
) else (
  python tools\consulter_memoire.py %*
)
echo.
pause
