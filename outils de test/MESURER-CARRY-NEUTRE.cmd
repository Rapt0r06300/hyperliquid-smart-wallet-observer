@echo off
chcp 65001 >nul
cd /d "%~dp0.."
set PYTHONPATH=src
python tools\mesurer_carry_neutre.py
echo.
pause
