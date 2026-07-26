@echo off
REM ============================================================================
REM  LANCER-RECHERCHE-18H — labo quantitatif AUTONOME 18 h, ISOLE, PAPER-ONLY (Flo 26/07)
REM  NOUVELLE chaine : n'altere JAMAIS le 14 h (LANCER-RECHERCHE-14H.cmd et ses hashes restent intacts).
REM  Sortie UNIQUEMENT sous runtime\research_lab\overnight_18h\<run_id>.
REM  Sous-commandes : dry-run | start | status | watch | resume | stop <run_id> | finalize
REM  SECURITE : 0 /exchange, 0 signature, 0 cle, 0 wallet, 0 ordre reel/testnet, 0 executor,
REM             0 depot/retrait, 0 appel reseau d'ecriture. /info + WebSocket READ-ONLY seulement.
REM  Limites ressources surchargeables : HYPERSMART_18H_MAX_CPU_PERCENT / MAX_RAM_GB / MAX_WORKERS / MIN_FREE_DISK_GB
REM ============================================================================
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src;%CD%\tools"
set "PYTHONIOENCODING=utf-8"
set "ACTION=%~1"
if "%ACTION%"=="" set "ACTION=status"

if /i "%ACTION%"=="dry-run"  goto :dryrun
if /i "%ACTION%"=="start"    goto :start
if /i "%ACTION%"=="status"   goto :status
if /i "%ACTION%"=="watch"    goto :watch
if /i "%ACTION%"=="resume"   goto :resume
if /i "%ACTION%"=="stop"     goto :stop
if /i "%ACTION%"=="finalize" goto :finalize
echo Usage: LANCER-RECHERCHE-18H.cmd [dry-run^|start^|status^|watch^|resume^|stop ^<run_id^>^|finalize]
goto :fin

:dryrun
echo === DRY-RUN 18H (precheck : securite + disque + catalogue + ressources, sans chrono) ===
python tools\recherche_18h.py dry-run
goto :fin

:start
echo === PRECHECK + START (18 h, paper-only) ===
REM 0) DEDUP LABO 18h : ne tuer QUE la boucle 18h existante (script precis) — jamais un motif large.
powershell -NoProfile -Command "$p = Get-CimInstance Win32_Process | Where-Object { ($_.Name -eq 'python.exe' -or $_.Name -eq 'pythonw.exe') -and ($_.CommandLine -match 'recherche_18h\.py boucle') }; foreach ($x in $p) { try { Stop-Process -Id $x.ProcessId -Force -ErrorAction SilentlyContinue } catch {} }; Write-Host '  dedup 18h fait.'"
REM 1) (re)demarrer les collecteurs lecture-seule deja existants (isoles, throttle) pour nourrir le live.
start "" /b tools\boucle_collecteur.cmd lab-microstructure tools\collecter_lab_microstructure.py 30
start "" /b tools\boucle_collecteur.cmd lab-ctx tools\collecter_lab_ctx.py 30
REM 2) laisser 45 s aux flux WS read-only pour se connecter/s'abonner/recevoir.
ping -n 46 127.0.0.1 >nul 2>&1
REM 3) precheck bloquant + creation du run (chrono demarre seulement si PASS). Sortie tracee.
if not exist "runtime\research_lab\overnight_18h" mkdir "runtime\research_lab\overnight_18h" >nul 2>&1
python tools\recherche_18h.py start > "runtime\research_lab\overnight_18h\_last_start.json" 2>&1
type "runtime\research_lab\overnight_18h\_last_start.json"
REM 4) lancer la boucle 18 h SEULEMENT si un run est actif (PRECHECK PASS).
python tools\recherche_18h.py status | findstr /C:"\"actif\": true" >nul 2>&1
if not errorlevel 1 (
  start "RECHERCHE-18H-boucle" cmd /c "set PYTHONPATH=%CD%\src;%CD%\tools && python tools\recherche_18h.py boucle"
  echo === boucle 18 h lancee. Suivi : LANCER-RECHERCHE-18H.cmd watch ===
) else (
  echo === PRECHECK non PASS : boucle NON lancee. Voir _last_start.json. ===
)
python tools\recherche_18h.py status
pause
goto :fin

:status
python tools\recherche_18h.py status
goto :fin

:watch
echo (Ctrl-C pour quitter le suivi)
:watchloop
cls
python tools\recherche_18h.py watch
ping -n 6 127.0.0.1 >nul 2>&1
goto :watchloop

:resume
echo === RESUME 18H (idempotent, meme run_id, sans doublon) ===
python tools\recherche_18h.py resume
start "RECHERCHE-18H-boucle" cmd /c "set PYTHONPATH=%CD%\src;%CD%\tools && python tools\recherche_18h.py boucle"
goto :fin

:stop
echo === STOP 18H (run_id signe requis) ===
python tools\recherche_18h.py stop --run-id "%~2"
goto :fin

:finalize
echo === FINALIZE 18H (scelle + rapport exhaustif) ===
python tools\recherche_18h.py finalize
goto :fin

:fin
if /i not "%ACTION%"=="start" if /i not "%ACTION%"=="watch" pause
endlocal
