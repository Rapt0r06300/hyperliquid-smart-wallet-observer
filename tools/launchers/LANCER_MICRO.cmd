@echo off
setlocal
for %%I in ("%~dp0..\..") do set "ALINA_PROJECT_ROOT=%%~fI"
cd /d "%ALINA_PROJECT_ROOT%" || exit /b 1
REM Relance du SEUL collecteur microstructure dense (avec reconnexion). Isole sous research_lab. 0 ordre.
cd /d "%ALINA_PROJECT_ROOT%\"
set "PYTHONPATH=%CD%\src"
set "PYTHONIOENCODING=utf-8"
title LABO-microstructure-reconnect
python tools\collecter_lab_microstructure.py
