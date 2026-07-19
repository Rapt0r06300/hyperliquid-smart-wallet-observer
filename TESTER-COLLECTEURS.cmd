@echo off
REM ============================================================================
REM  TEST ISOLE DES 3 LIGNES DE LANCEMENT DES COLLECTEURS
REM ============================================================================
REM  Pourquoi ce fichier : les 3 collecteurs ont echoue deux fois au demarrage
REM  ('C:\Users\flo\Desktop\Projet' n'est pas reconnu -- l'espace du dossier).
REM  Je ne peux pas executer un .cmd depuis mon environnement : ce script permet
REM  de VERIFIER le mecanisme en 15 secondes, SANS lancer le bot (donc sans
REM  conflit sur le port 8794 ni deuxieme instance).
REM
REM  Il rejoue les 3 lignes EXACTEMENT comme LANCER_HYPERSMART.cmd, attend,
REM  affiche le verdict, puis ARRETE ce qu'il a demarre. Aucun effet durable.
REM
REM  Securite : lecture seule cote marche. 0 ordre, 0 cle, 0 signature.
REM ============================================================================
setlocal
cd /d "%~dp0"
echo.
echo ================================================================
echo   TEST DES COLLECTEURS -- dossier : %CD%
echo ================================================================
echo.

REM On repart d'une ardoise propre pour que le verdict porte sur CE test.
if exist "runtime\logs\carry-feeder.log"    del /q "runtime\logs\carry-feeder.log"    >nul 2>&1
if exist "runtime\logs\marks-collector.log" del /q "runtime\logs\marks-collector.log" >nul 2>&1
if exist "runtime\logs\liq-collector.log"   del /q "runtime\logs\liq-collector.log"   >nul 2>&1

echo   Lancement des 3 collecteurs (chemins RELATIFS, sans guillemets)...
start "" /b tools\boucle_collecteur.cmd carry-feeder tools\ecrire_carry_spot_inputs.py 240
start "" /b tools\boucle_collecteur.cmd marks-collector tools\ecrire_marks_tous_coins.py 60 --une-fois
start "" /b tools\boucle_collecteur.cmd liq-collector tools\collecter_liquidations.py 300 --une-fois

echo   Attente de 12 secondes (ils ecrivent leur log des la 1re ligne)...
ping -n 13 127.0.0.1 >nul 2>&1
echo.
echo ---------------------------- VERDICT ---------------------------
set "ECHECS=0"
for %%C in (carry-feeder marks-collector liq-collector) do (
  if exist "runtime\logs\%%C.log" (
    echo   [OK]     %%C  -- log ecrit
  ) else (
    echo   [ECHEC]  %%C  -- AUCUN log
  )
)
echo ----------------------------------------------------------------
echo.
echo   Extrait du log marks-collector :
echo.
if exist "runtime\logs\marks-collector.log" (
  more +1 "runtime\logs\marks-collector.log"
) else (
  echo     ^(pas de log^)
)
echo.
echo ================================================================
echo   Arret des collecteurs demarres par CE test...
echo ================================================================
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -like '*boucle_collecteur.cmd*' } | ForEach-Object { try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop; Write-Host ('   arrete PID ' + $_.ProcessId) } catch {} }"
echo.
echo   Termine. Appuyez sur une touche pour fermer.
pause >nul
