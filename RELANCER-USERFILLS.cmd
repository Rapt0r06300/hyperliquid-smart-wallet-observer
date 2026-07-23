@echo off
REM ============================================================================
REM  RELANCER UNIQUEMENT le collecteur userfills-live (nouveau code RAW_PROBE)
REM ----------------------------------------------------------------------------
REM  Redemarre le SEUL collecteur userfills-live SANS toucher au bot principal
REM  (port 8794) ni aux autres collecteurs. Charge le code courant -> active les
REM  3 cohortes ALPHA / DISCOVERY_PROBE / RAW_PROBE (ouverture INLINE dans le flux
REM  WS userFills). Detache + sans fenetre : survit a la fermeture de ce lanceur.
REM
REM  Prerequis : lancer TUER-ORPHELIN-USERFILLS.cmd avant, pour liberer le verrou.
REM  Securite : 2 flux PUBLICS en lecture (userFills + L2). 0 ordre, 0 cle, 0 signature.
REM ============================================================================
cd /d "%~dp0"
echo Relance isolee du collecteur userfills-live (nouveau code)...
echo.
powershell -NoProfile -Command ^
  "$p = '%~dp0';" ^
  "$lk = Join-Path $p 'runtime\data\userfills_live.lock';" ^
  "if (Test-Path $lk) { Write-Host '  ATTENTION : un verrou existe encore -> lance TUER-ORPHELIN-USERFILLS.cmd d abord.'; exit 1 };" ^
  "Start-Process -WindowStyle Hidden -FilePath 'cmd.exe' -ArgumentList '/c','tools\boucle_collecteur.cmd userfills-live tools\collecter_userfills_vaults.py 5' -WorkingDirectory $p;" ^
  "Write-Host '  collecteur userfills-live relance (detache, sans fenetre).'"
echo.
echo Verification dans ~15 s : runtime\data\userfills_live.lock doit reapparaitre
echo avec un NOUVEAU run_id et un NOUVEAU pid ; runtime\logs\userfills-live.log frais.
echo.
timeout /t 8 >nul
if exist "runtime\data\userfills_live.lock" (
  echo   OK : verrou recree ^-^> collecteur en cours.
  type "runtime\data\userfills_live.lock"
) else (
  echo   Pas encore de verrou ^(le collecteur demarre peut-etre encore^).
)
echo.
pause
