@echo off
setlocal enabledelayedexpansion
rem ============================================================
rem  CERTIFICATION EN CONTINU — a laisser ouverte A COTE d une campagne.
rem
rem  POURQUOI. La certification n avait lieu qu a l arret propre (touche q) ou au
rem  demarrage suivant. Une campagne de 6 jours fermee brutalement au jour 5 laissait
rem  5 jours de donnees NON certifiees, donc invisibles pour le labo qui ne lit QUE le
rem  coffre certifie. Ici : toutes les 30 min. Au pire on perd l intervalle en cours.
rem
rem  POURQUOI UNE BOUCLE DE RELANCE. Un seul processus cense tenir 6 jours finit par
rem  mourir (plantage, memoire, fermeture accidentelle). Observe le 13/11 : le
rem  certificateur avait disparu et PLUS RIEN ne le relancait. Ici il repart tout seul,
rem  avec une attente qui double a chaque echec — meme motif que le superviseur des
rem  collecteurs, qui a fait ses preuves.
rem
rem  SANS DANGER pendant que les collecteurs ecrivent : le scellage s arrete au dernier
rem  saut de ligne COMPLET et reprend ou il s etait arrete.
rem
rem  ARRET : Ctrl+C (code 130), ou creer le fichier runtime\data\stop_certification.flag
rem ============================================================
title ALINA - CERTIFICATION CONTINUE
cd /d "%~dp0"
set "CC_ROOT=%~dp0"
set "CC_INTERVALLE=1800"
if not "%~1"=="" set "CC_INTERVALLE=%~1"
set "CC_ATTENTE=30"
set "CC_ATTENTE_MAX=300"
set "CC_RELANCES=0"
set "CC_MAX_RELANCES=200"
set "CC_STOP=%CC_ROOT%runtime\data\stop_certification.flag"
set "CC_JOURNAL=%CC_ROOT%runtime\logs\certification_continue.log"

set "CC_PYTHON="
if exist "%CC_ROOT%tools\python\python.exe" set "CC_PYTHON=%CC_ROOT%tools\python\python.exe"
if not defined CC_PYTHON if exist "%CC_ROOT%.venv\Scripts\python.exe" set "CC_PYTHON=%CC_ROOT%.venv\Scripts\python.exe"
if not defined CC_PYTHON (
  echo [ERREUR] Aucun Python trouve ^(tools\python ou .venv^).
  pause
  exit /b 2
)
if not exist "%CC_ROOT%runtime\logs" mkdir "%CC_ROOT%runtime\logs" >nul 2>nul
if exist "%CC_STOP%" del /f /q "%CC_STOP%" >nul 2>nul

set "PYTHONUTF8=1"
set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%CC_ROOT%src;%CC_ROOT%tools;%PYTHONPATH%"

echo.
echo   ============================================================
echo     CERTIFICATION EN CONTINU — une passe toutes les %CC_INTERVALLE% secondes
echo     Relance automatique si le processus meurt ^(jusqu a %CC_MAX_RELANCES% fois^).
echo     Laissez cette fenetre OUVERTE pendant toute la campagne.
echo     Ctrl+C pour arreter ^(la derniere passe complete reste certifiee^).
echo   ============================================================
echo.

:boucle
if exist "%CC_STOP%" goto :arret_demande
"%CC_PYTHON%" "%CC_ROOT%tools\tee_console.py" "%CC_JOURNAL%" -- "%CC_PYTHON%" -u "%CC_ROOT%tools\sceller_coffre_local.py" --root "%CC_ROOT%." --boucle-s %CC_INTERVALLE%
set "RC=!ERRORLEVEL!"
if exist "%CC_STOP%" goto :arret_demande
if "!RC!"=="130" goto :arret_ctrl_c
set /a CC_RELANCES+=1
if !CC_RELANCES! GTR %CC_MAX_RELANCES% goto :trop_de_relances
echo.
echo [RELANCE !CC_RELANCES!/%CC_MAX_RELANCES%] La certification s est arretee ^(code !RC!^).
echo                Nouvelle tentative dans !CC_ATTENTE! s.
>>"%CC_ROOT%runtime\logs\certification_relances.log" echo RELANCE=!CC_RELANCES! RC=!RC! ATTENTE=!CC_ATTENTE!s DATE=%DATE% %TIME%
timeout /t !CC_ATTENTE! /nobreak >nul 2>nul
set /a CC_ATTENTE=!CC_ATTENTE! * 2
if !CC_ATTENTE! GTR %CC_ATTENTE_MAX% set "CC_ATTENTE=%CC_ATTENTE_MAX%"
goto :boucle

:arret_ctrl_c
echo.
echo [ARRET] Ctrl+C — la derniere passe complete reste certifiee.
goto :fin

:arret_demande
del /f /q "%CC_STOP%" >nul 2>nul
echo.
echo [ARRET] Demande par stop_certification.flag.
goto :fin

:trop_de_relances
echo.
echo [ABANDON] %CC_MAX_RELANCES% relances atteintes : quelque chose ne va pas.
echo           Lire %CC_JOURNAL% et runtime\logs\certification_relances.log
set "RC=1"

:fin
echo.
echo [FIN] Certification continue terminee - !CC_RELANCES! relance^(s^) - code !RC!
pause
exit /b !RC!
