@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%CD%;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
python tools\_apercu_dashboard.py > "%~dp0rapports\apercu_dashboard.txt" 2>&1
exit /b 0
