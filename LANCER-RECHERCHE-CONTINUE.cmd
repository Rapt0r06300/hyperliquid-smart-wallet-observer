@echo off
REM ============================================================================
REM  HyperSmart - recherche continue locale, paper/read-only.
REM  Double-clic: precontrole, reprise ou nouveau run, tableau de bord temps reel.
REM  Ctrl+C: arret cooperatif, rapport Markdown, audit puis manifeste SHA-256.
REM ============================================================================
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
chcp 65001 >nul
title HyperSmart - Recherche continue
set "PYTHONPATH=%CD%\src;%CD%\tools"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PYTHONUNBUFFERED=1"
set "HYPERSMART_DASHBOARD_FULLSCREEN=1"
set "HYPERSMART_DASHBOARD_REFRESH_MS=1000"
set "HYPERSMART_18H_MAX_CPU_PERCENT=45"
set "HYPERSMART_18H_MAX_RAM_GB=8"
set "HYPERSMART_18H_MAX_WORKERS=2"
set "HYPERSMART_18H_MAX_SOURCES_PER_BOOTSTRAP=256"
set "HYPERSMART_18H_MAX_BOOTSTRAP_MEGABYTES=512"
set "HYPERSMART_RESOURCE_PRIORITY=BELOW_NORMAL"
set "HYPERSMART_RESOURCE_NEVER_IDLE=1"
set "ENGINE_EXIT=0"
set "FINAL_EXIT=1"

echo ============================================================
echo   HYPERSMART - RECHERCHE CONTINUE PAPER / READ-ONLY
echo ============================================================
echo   Console plein ecran : progression globale + boucle interne.
echo   Affichage 1 fois/seconde + preuve de vie ecrite chaque seconde.
echo   Les calculs longs restent visibles sans bloquer le moteur.
echo   Priorite BelowNormal permanente, jamais Idle, aucune pause de travail.
echo   Avec Salad: lots et concurrence reduits automatiquement, calcul continu.
echo   Ctrl+C une fois = arret propre et rapport garanti.
echo   Ctrl+C deux fois = rapport partiel d'urgence.
echo ============================================================
echo.

echo [1/4] Precontrole securite, disque et dependances...
python -u tools\recherche_continue.py dry-run
if errorlevel 1 (
  echo.
  echo [ECHEC] Le precontrole a refuse le demarrage. Aucun calcul n'a ete lance.
  echo Consulte les lignes ci-dessus pour connaitre la cause exacte.
  set "ENGINE_EXIT=2"
  goto :fin
)
echo [OK] Precontrole valide.
echo.

echo [2/4] Recherche d'un run incomplet a reprendre...
python -u tools\recherche_continue.py peut-reprendre
if errorlevel 1 (
  echo [INFO] Aucun run incomplet: creation d'un nouveau laboratoire.
  echo [INFO] Le tableau de bord va afficher chaque sous-tache et son pourcentage.
  python -u tools\recherche_continue.py start
) else (
  echo [INFO] Run incomplet detecte: reprise exacte des artefacts existants.
  echo [INFO] Aucun ancien rapport ni resultat n'est supprime.
  python -u tools\recherche_continue.py resume
)
set "ENGINE_EXIT=!ERRORLEVEL!"
echo.
echo [3/4] Le moteur principal est revenu avec le code !ENGINE_EXIT!.

set "RID="
for /f "usebackq tokens=* delims=" %%R in (`python -u tools\recherche_continue.py dernier-run-lance`) do set "RID=%%R"
if "!RID!"=="" (
  echo [ERREUR] Aucun run_id lance n'a ete retrouve.
  echo Le pointeur n'a pas ete efface: les artefacts restent sur disque.
  goto :fin
)

echo [INFO] Run verifie: !RID!
echo [4/4] Verification du rapport et de toutes les empreintes SHA-256...
python -u tools\recherche_continue.py verifier-finalisation --run-id "!RID!"
set "FINAL_EXIT=!ERRORLEVEL!"

if not "!FINAL_EXIT!"=="0" (
  echo.
  echo [ATTENTION] La finalisation complete n'est pas encore confirmee.
  echo [SECOURS] Le processus principal est revenu; demande de finalisation du meme run...
  python -u tools\recherche_continue.py stop --run-id "!RID!"
  timeout /t 2 /nobreak >nul
  python -u tools\recherche_continue.py verifier-finalisation --run-id "!RID!"
  set "FINAL_EXIT=!ERRORLEVEL!"
)

if "!FINAL_EXIT!"=="0" (
  echo.
  echo [OK] Rapport final confirme pour !RID!.
  echo [OK] Les SHA-256 ont ete recalcules et concordent.
) else (
  echo.
  echo [ATTENTION] Un rapport partiel ou de secours a ete conserve.
  echo [ATTENTION] La sortie ci-dessus donne son chemin et la cause exacte.
)

:fin
echo.
echo ============================================================
echo   Fin du lanceur. Aucun ordre reel, aucune cle, aucune signature.
echo ============================================================
pause
endlocal & exit /b %ENGINE_EXIT%
