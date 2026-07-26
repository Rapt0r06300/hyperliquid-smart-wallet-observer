@echo off
REM ============================================================================
REM  LANCER-RECHERCHE-14H — run de recherche AUTONOME 14 h, ISOLE (Flo 25/07)
REM  REUTILISE : RESEARCH_PARALLEL_V1 + collecter_lab_microstructure + collecter_lab_ctx
REM              + execution_honnete + validation. Ne reconstruit rien.
REM  Sous-commandes : start | status | resume | stop <run_id> | finalize | dry-run
REM  ISOLATION : sortie sous runtime\research_lab\overnight_14h\<run_id> ; 0 impact
REM              RAW/OOS/MAIN ; 0 reset ; 0 ordre ; arret par run_id signe seulement.
REM  Windows reste eveille (SetThreadExecutionState dans la boucle Python).
REM  0 cle, 0 signature, 0 ordre reel.
REM ============================================================================
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src"
set "PYTHONIOENCODING=utf-8"
set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=status"

if /i "%ACTION%"=="dry-run"  goto :dryrun
if /i "%ACTION%"=="start"    goto :start
if /i "%ACTION%"=="status"   goto :status
if /i "%ACTION%"=="resume"   goto :resume
if /i "%ACTION%"=="stop"     goto :stop
if /i "%ACTION%"=="finalize" goto :finalize
echo Usage: LANCER-RECHERCHE-14H.cmd [start^|status^|resume^|stop ^<run_id^>^|finalize^|dry-run]
goto :fin

:dryrun
echo === DRY-RUN (precheck sans chrono) ===
python tools\recherche_14h.py dry-run
goto :fin

:start
echo === PRECHECK + START (14 h) ===
REM 0) DEDUP LABO : tuer les instances LABO existantes (scripts PRECIS uniquement, jamais un motif large ->
REM    aucun risque pour un process etranger). Garantit UNE SEULE instance de chaque collecteur.
powershell -NoProfile -Command "$procs = Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and ($_.CommandLine -match 'collecter_lab_microstructure\.py|collecter_lab_ctx\.py|lancer_research_parallel\.py|recherche_14h\.py boucle') }; foreach ($p in $procs) { try { Stop-Process -Id $p.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }; Write-Host '  dedup LABO fait.'"
ping -n 3 127.0.0.1 >nul 2>&1
REM 1) relancer PROPREMENT les collecteurs isoles (throttle actif). boucle_collecteur = relance sur crash.
start "" /b tools\boucle_collecteur.cmd research-lab tools\lancer_research_parallel.py 60 --max-ticks 1
start "" /b tools\boucle_collecteur.cmd lab-microstructure tools\collecter_lab_microstructure.py 30
start "" /b tools\boucle_collecteur.cmd lab-ctx tools\collecter_lab_ctx.py 30
REM 2) laisser 20 s aux flux pour grossir (le precheck EXIGE une croissance WS reelle)
ping -n 21 127.0.0.1 >nul 2>&1
REM 3) precheck bloquant + creation du run (chrono demarre seulement si PASS). Sortie tracee (preuve).
if not exist "runtime\research_lab\overnight_14h" mkdir "runtime\research_lab\overnight_14h" >nul 2>&1
python tools\recherche_14h.py start > "runtime\research_lab\overnight_14h\_last_start.json" 2>&1
type "runtime\research_lab\overnight_14h\_last_start.json"
REM 4) lancer la boucle de mesure autonome 14 h SEULEMENT si un run est actif (PRECHECK PASS)
python tools\recherche_14h.py status | findstr /C:"\"actif\": true" >nul 2>&1
if not errorlevel 1 (
  start "RECHERCHE-14H-boucle" cmd /c "set PYTHONPATH=%CD%\src && python tools\recherche_14h.py boucle"
  echo === boucle 14 h lancee. ===
) else (
  echo === PRECHECK non PASS : boucle NON lancee. Voir _last_start.json. ===
)
python tools\recherche_14h.py status
pause
goto :fin

:status
python tools\recherche_14h.py status
goto :fin

:resume
echo === RESUME (idempotent, sans doublon) ===
python tools\recherche_14h.py resume
start "RECHERCHE-14H-boucle" cmd /c "set PYTHONPATH=%CD%\src && python tools\recherche_14h.py boucle"
goto :fin

:stop
echo === STOP (run_id signe requis) ===
python tools\recherche_14h.py stop --run-id "%~2"
goto :fin

:finalize
echo === FINALIZE (scelle + rapport) ===
python tools\recherche_14h.py finalize
goto :fin

:fin
endlocal
