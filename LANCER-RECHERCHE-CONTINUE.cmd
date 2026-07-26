@echo off
REM ============================================================================
REM  LANCER-RECHERCHE-CONTINUE — laboratoire de recherche CONTINU, PAPER-ONLY (Flo 26/07)
REM  ADDITIF : ne casse NI le 14 h NI le 18 h. Sortie UNIQUEMENT sous runtime\research_lab\continuous\<run_id>.
REM  PLUS de limite de duree : travaille en cycles jusqu'au Ctrl+C, qui declenche la FINALISATION propre.
REM  IMPORTANT : le moteur tourne au PREMIER PLAN dans CE terminal (jamais detache), pour que Ctrl+C
REM              controle correctement l'arret propre et le rapport final.
REM  Sous-commandes : dry-run | start | resume | status | snapshot | stop <run_id>
REM  SECURITE : 0 /exchange, 0 signature, 0 cle, 0 ordre reel/testnet, 0 executor, 0 depot/retrait.
REM ============================================================================
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src;%CD%\tools"
set "PYTHONIOENCODING=utf-8"
set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=status"

if /i "%ACTION%"=="dry-run"  goto :dryrun
if /i "%ACTION%"=="start"    goto :start
if /i "%ACTION%"=="resume"   goto :start
if /i "%ACTION%"=="status"   goto :status
if /i "%ACTION%"=="snapshot" goto :snapshot
if /i "%ACTION%"=="stop"     goto :stop
echo Usage: LANCER-RECHERCHE-CONTINUE.cmd [dry-run^|start^|resume^|status^|snapshot^|stop ^<run_id^>]
goto :fin

:dryrun
echo === DRY-RUN CONTINU (securite + disque + ressources) ===
python tools\recherche_continue.py dry-run
goto :fin

:start
echo === DEMARRAGE DU LABO CONTINU (Ctrl+C = arret propre + rapport final) ===
echo === Les collecteurs lecture-seule sont desormais SUPERVISES par Python ===
echo ===  (PID enregistre, anti-doublon au resume, restart individuel, arret explicite a la fin). ===
echo === Le moteur tourne AU PREMIER PLAN. Appuie sur Ctrl+C quand tu veux le rapport final. ===
REM PAS de "start" : le moteur reste dans CE terminal pour que Ctrl+C controle la finalisation.
REM PAS de "start /b" aveugle des collecteurs : le superviseur Python (FINAL-14) les gere proprement.
python tools\recherche_continue.py start
echo === Finalisation terminee. Voir le chemin du rapport ci-dessus. ===
goto :fin

:status
python tools\recherche_continue.py status
goto :fin

:snapshot
echo === SNAPSHOT (rapport intermediaire, sans arreter le travail) ===
python tools\recherche_continue.py snapshot
goto :fin

:stop
echo === STOP (meme finalisation propre que Ctrl+C) ===
python tools\recherche_continue.py stop --run-id "%~2"
goto :fin

:fin
if /i not "%ACTION%"=="start" if /i not "%ACTION%"=="resume" pause
endlocal
