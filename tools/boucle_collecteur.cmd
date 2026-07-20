@echo off
REM ============================================================================
REM  BOUCLE DE COLLECTEUR — un seul script pour les 3 collecteurs, SANS FENETRE
REM ============================================================================
REM  Usage :  boucle_collecteur.cmd <nom> <script.py> <intervalle_s> [args...]
REM
REM  POURQUOI CE FICHIER (19/07) : les 3 collecteurs (carry-feeder, marks,
REM  liquidations) ouvraient chacun une fenetre cmd au demarrage du bot. Flo :
REM  « y'a plein de fenetres qui s'ouvrent et je veux pas ca ». C'est moi qui les
REM  avais ajoutees ; elles sont supprimees.
REM
REM  MAIS un processus cache qui echoue en SILENCE serait exactement la maladie
REM  qu'on vient de corriger (105 `except: pass` -> 0). Chaque passe est donc
REM  horodatee dans runtime\logs\<nom>.log, avec le code de sortie.
REM
REM  Le log est TRONQUE au demarrage de chaque session : on veut la session en
REM  cours, pas un fichier de 2 Go apres trois jours (le bot a deja crashe une
REM  fois sur un disque plein).
REM
REM  Securite : lecture seule cote marche. 0 ordre, 0 cle, 0 signature.
REM ============================================================================
setlocal
cd /d "%~dp0.."
set "NOM=%~1"
set "SCRIPT=%~2"
set "INTERVALLE=%~3"
if "%NOM%"=="" exit /b 2
if "%SCRIPT%"=="" exit /b 2
if "%INTERVALLE%"=="" set "INTERVALLE=300"

set "PYTHONIOENCODING=utf-8"
set "PYTHONPATH=%CD%\src"
if not exist "runtime\logs" mkdir "runtime\logs" >nul 2>&1
set "LOG=runtime\logs\%NOM%.log"

REM 🔴 20/07 : le superviseur relance un collecteur mort... et cette troncature DETRUISAIT la
REM preuve de sa mort (venues-collector : mort dans la nuit, log ecrase a 4:12, autopsie
REM impossible). On garde UNE generation : l'ancien log devient <nom>.prev.log avant d'etre
REM tronque. La tache R5 (pourquoi meurent-ils ?) a besoin de ce cadavre pour parler.
if exist "%LOG%" copy /y "%LOG%" "%LOG%.prev" >nul 2>&1

echo ============================================================ > "%LOG%"
echo  %NOM% — demarre le %date% a %time% (toutes les %INTERVALLE% s) >> "%LOG%"
echo  script : %SCRIPT% >> "%LOG%"
echo ============================================================ >> "%LOG%"

REM 21/07 ANTI-ORPHELIN (Flo : « Q — et meme la croix — doivent terminer la session ») :
REM on capture le marqueur de session du lanceur AU DEMARRAGE. A chaque passe, le garde
REM verifie (1) que le marqueur n'a pas change (sinon = vieille session -> stop, plus
REM jamais de boucles DOUBLEES) et (2) que le moteur donne signe de vie (sinon -> stop).
set "MARQUEUR="
if exist "runtime\data\lanceur_session_marqueur.txt" set /p MARQUEUR=<"runtime\data\lanceur_session_marqueur.txt"

:boucle
python tools\collecteur_doit_vivre.py "%MARQUEUR%" >> "%LOG%" 2>&1
if errorlevel 1 (
  echo   [arret propre anti-orphelin — la session est terminee] >> "%LOG%"
  exit /b 0
)
echo. >> "%LOG%"
echo --- passe du %date% %time% --- >> "%LOG%"
python "%SCRIPT%" %4 %5 %6 %7 %8 %9 >> "%LOG%" 2>&1
echo   [fin de passe, code de sortie = %errorlevel%] >> "%LOG%"
REM PAUSE PAR `ping` ET PAS `timeout` : `timeout` exige une console interactive et echoue avec
REM « Input redirection is not supported » des qu'on tourne en arriere-plan (start /b) ou avec
REM stdin redirige. La boucle partirait alors en roue libre, a fond, sans pause -- un collecteur
REM poli qui devient un marteau-pilon sur l'API publique. `ping -n N` attend N-1 secondes et
REM ne depend d'aucune console.
set /a "ATTENTE=%INTERVALLE%+1"
ping -n %ATTENTE% 127.0.0.1 >nul 2>&1
goto boucle
