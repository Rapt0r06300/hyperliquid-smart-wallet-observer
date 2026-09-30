@echo off
REM Relance du SEUL collecteur microstructure dense (avec reconnexion). Isole sous research_lab. 0 ordre.
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src"
set "PYTHONIOENCODING=utf-8"
title LABO-microstructure-reconnect
python tools\collecter_lab_microstructure.py
