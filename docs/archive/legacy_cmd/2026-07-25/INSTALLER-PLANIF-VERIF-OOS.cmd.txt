@echo off
REM ============================================================================
REM  Installe une tache du PLANIFICATEUR WINDOWS qui lance LANCER-VERIF-OOS.cmd
REM  toutes les 30 minutes (per-user, sans droits admin).
REM  Le verificateur est 100%% local, lecture seule : aucun modele Claude, aucun
REM  appel API, aucun reseau, aucune modif du runtime, aucun redemarrage.
REM  Pour retirer la tache : DESINSTALLER-PLANIF-VERIF-OOS.cmd
REM ============================================================================
setlocal
set "TN=HyperSmart_VerifOOS"
echo Creation de la tache planifiee "%TN%" (toutes les 30 min)...
schtasks /Create /SC MINUTE /MO 30 /TN "%TN%" /TR "\"%~dp0LANCER-VERIF-OOS.cmd\"" /F
if %ERRORLEVEL%==0 (
  echo.
  echo OK : "%TN%" creee. Verificateur OOS shadow local toutes les 30 min, lecture seule.
) else (
  echo.
  echo ECHEC de la creation. Lis le message ci-dessus.
)
echo.
echo --- Detail de la tache ---
schtasks /Query /TN "%TN%" /V /FO LIST 2>nul | findstr /I "TaskName Next Schedule Task_To_Run Scheduled"
echo.
pause
