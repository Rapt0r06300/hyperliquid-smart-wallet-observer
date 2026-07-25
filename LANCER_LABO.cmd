@echo off
REM ============================================================================
REM  ACTIVATION DU LABO ISOLE (RESEARCH_PARALLEL_V1) — SANS TOUCHER AU MAIN
REM  Lance en parallele du moteur principal (qui continue de tourner) :
REM    - le superviseur du labo (DATA_CTX + 6 plugins shadow, boucle persistante)
REM    - le collecteur WS microstructure dense (l2Book top20 + trades + BBO tailles)
REM    - le verificateur 30 min (preuve PID/heartbeat/croissance/main vivant)
REM  Tout est ISOLE sous runtime\research_lab. 0 cle, 0 ordre, 0 signature.
REM ============================================================================
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src"
set "PYTHONIOENCODING=utf-8"
if not exist "runtime\research_lab\logs" mkdir "runtime\research_lab\logs" >nul 2>&1

echo Activation du laboratoire isole...
start "LABO-superviseur" cmd /k "set PYTHONPATH=%CD%\src && python tools\lancer_research_parallel.py --poll-s 60"
start "LABO-microstructure" cmd /k "set PYTHONPATH=%CD%\src && python tools\collecter_lab_microstructure.py"
start "LABO-verificateur-30min" cmd /k "set PYTHONPATH=%CD%\src && python tools\verifier_lab_30min.py --minutes 30"
echo Trois fenetres LABO lancees. Le main continue de tourner (non touche).
