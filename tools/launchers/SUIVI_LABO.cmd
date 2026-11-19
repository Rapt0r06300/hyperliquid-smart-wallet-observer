@echo off
setlocal
rem  Fenetre de suivi du labo en deux phases. LECTURE SEULE : elle ouvre le journal, compte, et
rem  affiche. Elle ne touche ni au labo, ni aux collecteurs, ni au coffre -- un ecran de suivi qui
rem  pourrait perturber ce qu'il observe ne vaut pas la peine d'exister.
rem
rem  Usage :  SUIVI_LABO.cmd                      (trouve le journal le plus frais)
rem           SUIVI_LABO.cmd "chemin\du\journal.log"
title Suivi du labo - Alina
set "CV_ROOT=%~dp0"
set "CV_PYTHON=%CV_ROOT%tools\python\python.exe"
if not exist "%CV_PYTHON%" set "CV_PYTHON=python"
set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
"%CV_PYTHON%" -X utf8 "%CV_ROOT%tools\suivi_labo.py" %*
endlocal
