@echo off
REM ============================================================================
REM  LANCER-RECHERCHE-CONTINUE — LANCEMENT AUTOMATIQUE, PAPER-ONLY (Flo, PF-1)
REM  Double-clic = dry-run rapide -> REPRISE si un run existe, sinon DEMARRAGE. AUCUN menu.
REM  Collecteurs read-only + moteur + dashboard COMPACT (Rich Live) demarrent automatiquement.
REM  Ctrl+C = arret propre + rapport final. Le menu manuel est dans LANCER-RECHERCHE-CONTINUE-ADMIN.cmd.
REM  SECURITE : 0 /exchange, 0 signature, 0 cle, 0 ordre reel, 0 executor, 0 depot/retrait.
REM ============================================================================
setlocal EnableDelayedExpansion
cd /d "%~dp0"
set "PYTHONPATH=%CD%\src;%CD%\tools"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUNBUFFERED=1"

echo ============================================================
echo   HYPERSMART - LANCEMENT AUTOMATIQUE (paper-only)
echo ============================================================

REM 1) verification rapide (securite + disque). En cas d'echec : voir le menu ADMIN pour le detail.
python -u tools\recherche_continue.py dry-run >nul 2>&1
if errorlevel 1 (
  echo [ECHEC] Verification rapide KO. Ouvre LANCER-RECHERCHE-CONTINUE-ADMIN.cmd ^> 6 pour le detail.
  pause
  goto :quit
)
echo [OK] Verification rapide passee.

REM 2) pointeur de run efface avant tout demarrage (jamais d'ancien run verifie par erreur)
del /q "runtime\research_lab\continuous\DERNIER_RUN_LANCE.txt" 2>nul

REM 3) REPRISE si un run est reprenable, sinon DEMARRAGE d'un nouveau. Moteur AU PREMIER PLAN (Ctrl+C = rapport).
python -u tools\recherche_continue.py peut-reprendre >nul 2>&1
if errorlevel 1 (
  echo Aucun run a reprendre -^> DEMARRAGE d'un nouveau laboratoire. Ctrl+C = rapport final.
  python -u tools\recherche_continue.py start
) else (
  echo Run existant detecte -^> REPRISE. Ctrl+C = rapport final.
  python -u tools\recherche_continue.py resume
)

REM 4) verification de la finalisation du MEME run (SHA du manifeste recalcules)
set "RID="
for /f "usebackq tokens=* delims=" %%R in (`python -u tools\recherche_continue.py dernier-run-lance`) do set "RID=%%R"
if "%RID%"=="" (
  echo [ATTENTION] run_id introuvable - finalisation NON verifiee.
) else (
  python -u tools\recherche_continue.py verifier-finalisation --run-id "%RID%"
  if errorlevel 1 ( echo [ATTENTION] Finalisation NON confirmee pour %RID%. ) else ( echo [OK] Finalisation confirmee ^(SHA recalcules, meme run^). )
)
pause
:quit
endlocal
