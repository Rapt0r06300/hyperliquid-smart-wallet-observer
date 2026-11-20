@echo off
chcp 65001 >nul
setlocal EnableDelayedExpansion
rem ============================================================================
rem ALINA_SYNC_COMPLETE.cmd  -  Entree officielle OFFICIAL_DATA_SYNC (Windows).
rem PAPER / LECTURE SEULE : reprise apres sinistre et synchronisation du corpus
rem SAFE. Aucun ordre, aucune cle, aucune execution reelle. Jumeau de
rem ALINA_SYNC_COMPLETE.sh (meme moteur tools/sync_complete_clone.py).
rem
rem Sans argument : restauration SAFE complete et decompressee (opt-in par lancement).
rem   --download-safe           : telecharge le corpus SAFE (borne par defaut).
rem   --all-safe                : DOWNLOAD_AND_UNPACK_ALL_SAFE, corpus complet.
rem   --unpack-safe             : decompresse les conteneurs SAFE deja presents.
rem   --prune-only              : purge le cache sans telecharger.
rem ============================================================================
set "ALINA_ROOT=%~dp0"
set "UNIFIED=%ALINA_ROOT%POUSSER-GITHUB.cmd"
set "GIT_LFS_SKIP_SMUDGE=1"
set "ALINA_LAUNCH_RUN_ID=%DATE%_%TIME%_%RANDOM%_%RANDOM%"
set "ALINA_SYNC_PYTHON="
set "ALINA_SYNC_PY_ARGS="
if exist "%ALINA_ROOT%tools\python\python.exe" set "ALINA_SYNC_PYTHON=%ALINA_ROOT%tools\python\python.exe"
if not defined ALINA_SYNC_PYTHON if exist "%ALINA_ROOT%.venv\Scripts\python.exe" set "ALINA_SYNC_PYTHON=%ALINA_ROOT%.venv\Scripts\python.exe"
if not defined ALINA_SYNC_PYTHON (
    where py >nul 2>nul
    if not errorlevel 1 (
        set "ALINA_SYNC_PYTHON=py"
        set "ALINA_SYNC_PY_ARGS=-3"
    )
)
if not defined ALINA_SYNC_PYTHON (
    where python >nul 2>nul
    if not errorlevel 1 set "ALINA_SYNC_PYTHON=python"
)
set "ALINA_LAUNCH_PYTHON=!ALINA_SYNC_PYTHON! !ALINA_SYNC_PY_ARGS!"
set "ALINA_LAUNCH_OUTPUT_LOG=runtime/logs/launchers/ALINA_SYNC_COMPLETE.output.log"
set "ALINA_LAUNCH_MODE=argument-dispatch"
if not defined ALINA_SYNC_PYTHON goto :missing_python

if "%~1"=="" (
    rem The explicit operator launch requests every selected SAFE asset, SHA-verified.
    rem Never invoke POUSSER-GITHUB here; this entrypoint is data-only.
    set "DEFAULT_SAFE_ARGS=--download-safe --all-safe --unpack-safe"
    goto :run
)

set "MODE=%~1"
if /i "%MODE%"=="--help" goto :run
if /i "%MODE%"=="--preflight-only" goto :run
if /i "%MODE%"=="--catalog-budget" goto :run
if /i "%MODE%"=="--prune-cache-only" goto :run
if /i "%MODE%"=="--download-safe" goto :run
if /i "%MODE%"=="--all-safe" goto :run
if /i "%MODE%"=="--unpack-safe" goto :run
if /i "%MODE%"=="--prune-only" (
    set "ALINA_LAUNCH_MODE=prune-only"
    call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" START preflight "prune-cache-only" ""
    "!ALINA_SYNC_PYTHON!" !ALINA_SYNC_PY_ARGS! "%ALINA_ROOT%tools\sync_complete_clone.py" --prune-cache-only
    set "RC=!ERRORLEVEL!"
    call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" EXIT completion "prune-cache-only" "!RC!"
    endlocal & exit /b !RC!
)

echo Option AlinaSync inconnue : %MODE%
echo Options valides : --download-safe ^| --all-safe ^| --unpack-safe ^| --prune-only
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" EXIT argument-validation "unknown-option" "2"
endlocal & exit /b 2

:run
if defined DEFAULT_SAFE_ARGS (set "ALINA_LAUNCH_MODE=default-all-safe") else (set "ALINA_LAUNCH_MODE=%MODE%")
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" START preflight "sync-request" ""
if defined DEFAULT_SAFE_ARGS (
    call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" STEP download "sync_complete_clone.py" ""
    "!ALINA_SYNC_PYTHON!" !ALINA_SYNC_PY_ARGS! "%ALINA_ROOT%tools\sync_complete_clone.py" !DEFAULT_SAFE_ARGS!
) else (
    call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" STEP download "sync_complete_clone.py" ""
    "!ALINA_SYNC_PYTHON!" !ALINA_SYNC_PY_ARGS! "%ALINA_ROOT%tools\sync_complete_clone.py" %*
)
set "RC=!ERRORLEVEL!"
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" RESULT primary-sync "sync_complete_clone.py" "!RC!"
if /I "!MODE!"=="--help" goto :primary_only
if /I "!MODE!"=="--preflight-only" goto :primary_only
if /I "!MODE!"=="--catalog-budget" goto :primary_only
if /I "!MODE!"=="--prune-cache-only" goto :primary_only
rem AlinaSync : rapatrie aussi les fills des lanes GitHub (fail-soft, non bloquant).
set "LANE_FAILURES=0"
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" STEP github-lanes "telecharger_fills_lanes_github.py" ""
"!ALINA_SYNC_PYTHON!" !ALINA_SYNC_PY_ARGS! "%ALINA_ROOT%tools\telecharger_fills_lanes_github.py" --root "%ALINA_ROOT%." >>"%ALINA_ROOT%runtime\logs\launchers\ALINA_SYNC_COMPLETE.output.log" 2>&1
set "LANE_RC=!ERRORLEVEL!"
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" RESULT github-lanes "telecharger_fills_lanes_github.py" "!LANE_RC!"
if not "!LANE_RC!"=="0" set /a LANE_FAILURES+=1
rem AlinaSync : rapatrie aussi les fills LIVE_WS des lanes WS (fail-soft).
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" STEP github-lanes "telecharger_fills_ws_lanes_github.py" ""
"!ALINA_SYNC_PYTHON!" !ALINA_SYNC_PY_ARGS! "%ALINA_ROOT%tools\telecharger_fills_ws_lanes_github.py" --root "%ALINA_ROOT%." >>"%ALINA_ROOT%runtime\logs\launchers\ALINA_SYNC_COMPLETE.output.log" 2>&1
set "LANE_RC=!ERRORLEVEL!"
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" RESULT github-lanes "telecharger_fills_ws_lanes_github.py" "!LANE_RC!"
if not "!LANE_RC!"=="0" set /a LANE_FAILURES+=1
rem AlinaSync : rapatrie aussi les carnets L2 des lanes L2 (fail-soft).
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" STEP github-lanes "telecharger_l2_lanes_github.py" ""
"!ALINA_SYNC_PYTHON!" !ALINA_SYNC_PY_ARGS! "%ALINA_ROOT%tools\telecharger_l2_lanes_github.py" --root "%ALINA_ROOT%." >>"%ALINA_ROOT%runtime\logs\launchers\ALINA_SYNC_COMPLETE.output.log" 2>&1
set "LANE_RC=!ERRORLEVEL!"
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" RESULT github-lanes "telecharger_l2_lanes_github.py" "!LANE_RC!"
if not "!LANE_RC!"=="0" set /a LANE_FAILURES+=1
rem AlinaSync : rapatrie aussi le feed explorer (activite + decouverte leaders, fail-soft).
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" STEP github-lanes "telecharger_explorer_github.py" ""
"!ALINA_SYNC_PYTHON!" !ALINA_SYNC_PY_ARGS! "%ALINA_ROOT%tools\telecharger_explorer_github.py" --root "%ALINA_ROOT%." >>"%ALINA_ROOT%runtime\logs\launchers\ALINA_SYNC_COMPLETE.output.log" 2>&1
set "LANE_RC=!ERRORLEVEL!"
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" RESULT github-lanes "telecharger_explorer_github.py" "!LANE_RC!"
if not "!LANE_RC!"=="0" set /a LANE_FAILURES+=1
rem AlinaSync : rapatrie aussi les lanes marche (transactions, bougies) et contexte (positions des
rem leaders relevees 24h/24, tranches TWAP), validees ligne a ligne par le certificateur (fail-soft).
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" STEP github-lanes "telecharger_lanes_certifiees_github.py" ""
"!ALINA_SYNC_PYTHON!" !ALINA_SYNC_PY_ARGS! "%ALINA_ROOT%tools\telecharger_lanes_certifiees_github.py" --root "%ALINA_ROOT%." >>"%ALINA_ROOT%runtime\logs\launchers\ALINA_SYNC_COMPLETE.output.log" 2>&1
set "LANE_RC=!ERRORLEVEL!"
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" RESULT github-lanes "telecharger_lanes_certifiees_github.py" "!LANE_RC!"
if not "!LANE_RC!"=="0" set /a LANE_FAILURES+=1
for /f "delims=" %%R in ("!RC!") do set "RC=%%R"
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" SUMMARY github-lanes "failed-lanes=!LANE_FAILURES!" "!LANE_FAILURES!"
rem 19/11/2026 -- LES DONNEES D ALINASYNC SONT TRAITEES COMME CELLES DES COLLECTEURS.
rem AlinaSync depose ses shards SAFE dans runtime/recovery/, que le certificateur n inspecte
rem JAMAIS (recovery est dans son _EXCLUS) et que le labo ne voit pas (il ne lit que
rem LOCAL_INDEX.json, et COFFRE_INDEX.json est vide : 0 shard). Le pont existait pourtant,
rem teste et couvert par la CI, mais AUCUN lanceur ne l appelait : les 149,5 Go telecharges
rem restaient donc invisibles au labo. Il convertit les enveloppes SAFE en entrees Copy-Vault
rem DANS runtime/data/, le dossier meme ou ecrivent les collecteurs, et le certificateur les
rem scelle alors comme le reste.
rem FAIL-SOFT : le pont REFUSE legitimement quand rien n est admissible (aucun fill causal,
rem aucun L2 rejouable). Ce refus est une information, pas un echec de synchronisation.
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" STEP safe-bridge "copy_vault_safe_bridge.py" ""
"!ALINA_SYNC_PYTHON!" !ALINA_SYNC_PY_ARGS! "%ALINA_ROOT%tools\copy_vault_safe_bridge.py" --root "%ALINA_ROOT%." >>"%ALINA_ROOT%runtime\logs\launchers\ALINA_SYNC_COMPLETE.output.log" 2>&1
set "BRIDGE_RC=!ERRORLEVEL!"
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" RESULT safe-bridge "copy_vault_safe_bridge.py" "!BRIDGE_RC!"
if not "!BRIDGE_RC!"=="0" echo [INFO] Pont SAFE : rien d admissible a convertir (code !BRIDGE_RC!). Detail dans le journal.
goto :sync_complete

:primary_only
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" SUMMARY github-lanes "skipped-for-non-download-mode" "0"

:sync_complete
rem 19/11/2026 -- 12 MINUTES DE SILENCE PUIS RIEN. Les lanes ecrivent dans le journal, mais
rem l etape principale ecrivait sur une console qui se referme : le SEUL message expliquant
rem l echec etait donc perdu. Il passe desormais par tee_console (console ET journal), et on
rem le rappelle ici en clair. (tee_console a ete essaye puis RETIRE : sans son « -- », il
rem bascule en mode tuyau et attend une saisie, ce qui figeait le lanceur sur une
rem fenetre vide.) Cause de loin la plus frequente : du code local non committe,
rem qu AlinaSync refuse d ecraser (fail-closed, sans reset ni stash).
rem DECODER LE CODE, PAS EN SUPPOSER UN SEUL (20/11/2026). Ce bloc annoncait « du code local
rem non committe » pour TOUS les codes. Releve des echecs reels de primary-sync : NEUF a
rem 20/11/2026 au soir : un TROISIEME code est apparu, 1073807364 = 0x40010004 =
rem DBG_TERMINATE_PROCESS, quand une mise a jour de Windows a coupe un prefligh en cours apres
rem 464 s. Lui aussi n est PAS une panne. Deux des trois codes observes sont donc des arrets :
rem presumer la panne par defaut etait trompeur dans deux cas sur trois.
rem exit_code=2 (le refus fail-closed, cette cause-la) et UN a -1073741510, soit 0xC000013A =
rem STATUS_CONTROL_C_EXIT -- une INTERRUPTION, fenetre fermee ou Ctrl+C. Ce passage-la n avait
rem pas echoue, et une journee a ete passee a chercher un message d erreur qui n existait pas.
if not "!RC!"=="0" (
    echo.
    if "!RC!"=="2" (
        echo [ECHEC] AlinaSync a REFUSE de synchroniser ^(code 2^).
        echo         Cause : du CODE local non committe. AlinaSync ne l ecrase jamais,
        echo                 et ne fait ni reset ni stash : c est voulu.
        echo         Remede : lancer POUSSER-GITHUB.cmd, PUIS relancer AlinaSync.
    ) else if "!RC!"=="-1073741510" (
        echo [INTERROMPU] AlinaSync a ete ARRETE, il n a pas echoue ^(0xC000013A^).
        echo         Cause : Ctrl+C, ou la fenetre a ete fermee pendant le travail.
        echo         A savoir : la restauration et la fusion REPRENNENT ou elles en etaient.
        echo         Remede : relancer, simplement. Rien n est perdu ni corrompu.
    ) else if "!RC!"=="1073807364" (
        echo [INTERROMPU] AlinaSync a ete TUE par l arret du systeme ^(0x40010004^).
        echo         Cause : extinction, redemarrage, ou mise a jour de Windows.
        echo         A savoir : la restauration et la fusion REPRENNENT ou elles en etaient.
        echo         Remede : relancer. ^(Verifier aussi .git\index.lock, qu un arret brutal
        echo                 peut laisser derriere lui ; POUSSER-GITHUB.cmd le signale.^)
    ) else (
        echo [ECHEC] AlinaSync s est arrete avec le code !RC!.
        echo         Code inconnu ^(connus : 2=refus, -1073741510=Ctrl+C, 1073807364=arret^).
        echo         Lire le detail : c est lui qui porte la cause.
    )
    echo         Detail complet : runtime\logs\launchers\ALINA_SYNC_COMPLETE.output.log
    echo.
)
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" EXIT completion "sync-complete" "!RC!"
endlocal & exit /b %RC%

:missing_python
set "ALINA_LAUNCH_PYTHON=unresolved"
call "%ALINA_ROOT%tools\launcher_log.cmd" "ALINA_SYNC_COMPLETE" EXIT preflight "python-3-not-found" "30"
echo [NO_GO] Python 3 introuvable. Aucune synchronisation n'a ete lancee.
endlocal & exit /b 30
