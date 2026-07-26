@echo off
REM ============================================================================
REM  RECETTE-WINDOWS — laboratoire de recherche CONTINU (Flo, FX-10)
REM  À LANCER PAR FLO sur son poste Windows (Claude ne peut pas exécuter Windows).
REM  Enchaîne des étapes AUTOMATIQUES (dry-run, smoke borné, SHA recalculés, no-child)
REM  et des étapes INTERACTIVES guidées (dashboard Rich, touche S, Ctrl+C par phase,
REM  crash/reprise). Chaque étape s'arrête sur une pause pour que tu constates le résultat.
REM  SECURITE : paper-only, read-only. 0 ordre reel, 0 cle, 0 signature, 0 depot/retrait.
REM ============================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src;%CD%\tools"
set "PYTHONIOENCODING=utf-8"

echo ============================================================
echo   RECETTE WINDOWS — LABORATOIRE CONTINU (paper-only)
echo ============================================================

echo.
echo [1/9] DRY-RUN (securite + disque + dependances optionnelles optuna/cmaes)
python tools\recherche_continue.py dry-run
if errorlevel 1 ( echo [ECHEC] dry-run KO. & goto :fin ) else ( echo [OK] dry-run PASS. )
pause

echo.
echo [2/9] SMOKE BORNE reel (2 cycles, read-only, finalise SANS Ctrl+C) + SHA recalcules
python tools\recette_windows_smoke.py 2
if errorlevel 1 ( echo [ATTENTION] smoke non confirme - voir le JSON ci-dessus (SHA/rapport). ) else ( echo [OK] smoke: finalisation confirmee, SHA recalcules concordants. )
pause

echo.
echo [3/9] SUITE DE TESTS non-Windows (doit etre 100%% verte)
python -m pytest -q tests\test_labo_continu_absolute.py tests\test_labo_continu_fix.py tests\test_labo_continu_prod_truth.py tests\test_labo_continu_ultimate.py tests\test_labo_continu_final.py tests\test_data_complete_18h.py
pause

echo.
echo [4/9] CMD CHOIX 1 (Demarrer) — INTERACTIF
echo   -> Une fenetre va lancer un NOUVEAU labo au premier plan (dashboard Rich 12 panneaux).
echo   -> Observe : la PROGRESSION qui bouge (fait/total/%%/vitesse/ETA), pas des None.
echo   -> Appuie sur les touches 1..7 pour naviguer, puis 'S' pour creer un SNAPSHOT (le chemin s'affiche).
echo   -> Quand tu veux le rapport : Ctrl+C UNE fois (arret propre). Le CMD verifiera le MEME run (SHA recalcules).
pause
call LANCER-RECHERCHE-CONTINUE.cmd start
echo [i] Le CMD ci-dessus a du afficher "[OK] Finalisation confirmee ... (meme run)".
pause

echo.
echo [5/9] CTRL+C PENDANT CHAQUE PHASE — INTERACTIF (a repeter 3 fois)
echo   -> Relance 'start', puis fais Ctrl+C pendant l'INGESTION, puis (nouvelle fois) pendant le REPLAY,
echo      puis pendant la VALIDATION. A chaque fois un RAPPORT doit etre produit (pas de crash).
echo   -> Un 2e Ctrl+C rapproche => FINALIZATION_PARTIAL (sauvegarde d'urgence).
pause

echo.
echo [6/9] CRASH PENDANT UNE POSITION OUVERTE + REPRISE AUTOMATIQUE — INTERACTIF
echo   -> Lance 'start', laisse un cycle ouvrir des positions (panneau 9 : Positions ^> 0),
echo      puis FERME BRUTALEMENT la fenetre (croix) pour simuler un crash.
echo   -> Relance ensuite le CHOIX 2 (Reprendre) : les positions et sorties en attente sont REPRISES,
echo      les fermetures se font a leur echeance (aucune fermeture manuelle demandee).
pause
call LANCER-RECHERCHE-CONTINUE.cmd resume
pause

echo.
echo [7/9] STOPMENU attend le rapport — INTERACTIF
echo   -> Depuis le MENU (double-clic sur LANCER-RECHERCHE-CONTINUE.cmd), lance 1 (Demarrer) dans une fenetre,
echo      puis dans une AUTRE, choisis 5 (Arreter + rapport final). Le 5 doit ATTENDRE le rapport (boucle d'attente),
echo      puis afficher "[OK] Finalisation confirmee pour <run_id> (etat COMPLETE, rapport + manifeste + SHA)".
pause

echo.
echo [8/9] VERIFICATION SHA DU MEME RUN (recalcul, pas simple presence)
for /f "usebackq tokens=* delims=" %%R in (`python tools\recherche_continue.py dernier-run-lance`) do set "RID=%%R"
if "%RID%"=="" ( echo [i] Aucun run memorise. ) else ( echo Run: %RID% & python tools\recherche_continue.py verifier-finalisation --run-id "%RID%" )
pause

echo.
echo [9/9] AUCUN PROCESSUS ENFANT RESTANT (collecteurs read-only)
echo   -> La liste ci-dessous doit etre VIDE apres une finalisation propre :
tasklist /v /fi "IMAGENAME eq python.exe" 2>nul | findstr /i "collecter_lab" || echo [OK] Aucun collecteur python restant.
echo.
echo === RECETTE TERMINEE. Rapports dans "Rapports en continu\<run_id>\". SECURITE : 0 ordre reel. ===
:fin
pause
endlocal
