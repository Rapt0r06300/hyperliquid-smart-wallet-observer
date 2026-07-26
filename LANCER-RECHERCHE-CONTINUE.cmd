@echo off
REM ============================================================================
REM  LANCER-RECHERCHE-CONTINUE — laboratoire de recherche CONTINU, PAPER-ONLY (Flo 26/07)
REM  Double-clic (sans argument) => MENU simple. Argument => sous-commande directe (avance/planifie).
REM  ADDITIF : ne casse NI le 14 h NI le 18 h. Sortie sous runtime\research_lab\continuous\<run_id>.
REM  PLUS de limite de duree : travaille en cycles jusqu'au Ctrl+C = FINALISATION propre + rapport.
REM  Le moteur tourne AU PREMIER PLAN (jamais detache) pour que Ctrl+C controle la finalisation.
REM  SECURITE : 0 /exchange, 0 signature, 0 cle, 0 ordre reel/testnet, 0 executor, 0 depot/retrait.
REM ============================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src;%CD%\tools"
set "PYTHONIOENCODING=utf-8"
set "ACTION=%~1"
if not "%ACTION%"=="" goto :dispatch

:menu
cls
echo ============================================================
echo   HYPERSMART - LABORATOIRE DE RECHERCHE CONTINU (paper-only)
echo ============================================================
echo   1 - Demarrer un nouveau laboratoire
echo   2 - Reprendre le laboratoire existant
echo   3 - Voir son etat
echo   4 - Creer un snapshot (rapport intermediaire)
echo   5 - Arreter et creer le rapport final
echo   6 - Verifier l'installation (dry-run)
echo   7 - Quitter
echo ============================================================
set "CHOIX="
set /p "CHOIX=Ton choix (1-7) puis Entree : "
if "%CHOIX%"=="1" ( set "ACTION=start"    & goto :dispatch )
if "%CHOIX%"=="2" ( set "ACTION=resume"   & goto :dispatch )
if "%CHOIX%"=="3" ( set "ACTION=status"   & goto :dispatch )
if "%CHOIX%"=="4" ( set "ACTION=snapshot" & goto :dispatch )
if "%CHOIX%"=="5" ( set "ACTION=stopmenu" & goto :dispatch )
if "%CHOIX%"=="6" ( set "ACTION=dry-run"  & goto :dispatch )
if "%CHOIX%"=="7" ( goto :quit )
echo Choix invalide.
timeout /t 2 >nul
goto :menu

:dispatch
if /i "%ACTION%"=="dry-run"  goto :dryrun
if /i "%ACTION%"=="start"    goto :start
if /i "%ACTION%"=="resume"   goto :start
if /i "%ACTION%"=="status"   goto :status
if /i "%ACTION%"=="snapshot" goto :snapshot
if /i "%ACTION%"=="stop"     goto :stop
if /i "%ACTION%"=="stopmenu" goto :stopmenu
echo Usage: LANCER-RECHERCHE-CONTINUE.cmd [dry-run^|start^|resume^|status^|snapshot^|stop ^<run_id^>]
goto :fin

:dryrun
echo === VERIFICATION DE L'INSTALLATION (securite + disque + ressources) ===
python tools\recherche_continue.py dry-run
if errorlevel 1 ( echo [ECHEC] Verification KO - voir ci-dessus. ) else ( echo [OK] Installation prete. )
goto :fin

:start
echo === DEMARRAGE DU LABO CONTINU (Ctrl+C = arret propre + rapport final) ===
echo === Collecteurs lecture-seule SUPERVISES par Python (PID, anti-doublon, restart, arret explicite). ===
echo === Le moteur tourne AU PREMIER PLAN. Appuie sur Ctrl+C quand tu veux le rapport final. ===
python tools\recherche_continue.py start
REM le CMD ne declare "finalisation terminee" que si un rapport ET un manifeste existent reellement.
python tools\recherche_continue.py verifier-finalisation
if errorlevel 1 (
  echo [ATTENTION] Aucun rapport/manifeste confirme - finalisation NON garantie.
) else (
  echo [OK] Finalisation confirmee : rapport ET manifeste presents. Voir le chemin ci-dessus.
)
goto :fin

:status
python tools\recherche_continue.py status
goto :fin

:snapshot
echo === SNAPSHOT (rapport intermediaire, sans arreter le travail) ===
python tools\recherche_continue.py snapshot
goto :fin

:stopmenu
echo === ARRET + RAPPORT FINAL ===
for /f "usebackq tokens=* delims=" %%R in (`python tools\recherche_continue.py run-id-actif`) do set "RID=%%R"
if "%RID%"=="" ( echo Aucun run actif a arreter. & goto :fin )
echo Run actif : %RID%
python tools\recherche_continue.py stop --run-id "%RID%"
goto :fin

:stop
echo === STOP (meme finalisation propre que Ctrl+C) ===
python tools\recherche_continue.py stop --run-id "%~2"
goto :fin

:fin
if /i not "%ACTION%"=="start" if /i not "%ACTION%"=="resume" pause
:quit
endlocal
