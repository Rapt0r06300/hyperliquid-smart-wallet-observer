@echo off
REM ============================================================================
REM  VOIR-PREMIER-RAW — génère/affiche à la demande le rapport du 1er OPEN/CLOSE
REM  RAW_PROBE réel (le collecteur l'écrit AUSSI tout seul dès qu'il y en a un).
REM  Lecture seule d'un ledger paper. 0 ordre, 0 clé, 0 signature.
REM ============================================================================
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src"
python -c "from hl_observer.experimental import rapport_raw as R; p=R.ecrire_rapport('.'); print('Rapport ecrit :', p) if p else print('Aucun OPEN RAW pour l instant — le collecteur est arme, il capturera le premier.')"
echo.
if exist "runtime\rapports\PREMIER_RAW.md" type "runtime\rapports\PREMIER_RAW.md"
echo.
pause
