@echo off
chcp 65001 >nul
setlocal EnableExtensions
rem ===================================================================
rem   COFFRE - DONNEES EXTERNES GRATUITES
rem ===================================================================
rem   1. Recolte Ironflow : funding, open interest, liquidations,
rem      bougies 1 h ; et les 1ers du mois gratuits de Tardis : trades
rem      et carnet. Empreintes verifiees, rien de payant.
rem   2. Recoupe chaque dex avec NOS donnees, sur des seuils fixes
rem      d avance : ce qui ne se recoupe pas n entre pas.
rem   3. Verse au coffre seulement ce qu Alina n a pas : heures de
rem      funding manquantes, historique d avant nos collecteurs.
rem   4. Le certificateur habituel scelle. Tout est etiquete EXTERNE :
rem      jamais pris pour une observation d Alina.
rem
rem   Le carnet Tardis n entre pas au coffre : il n a pas d heure de
rem   reception par Alina, et on ne la fabrique pas.
rem   Aucun ordre, aucune cle. Les collecteurs ne sont pas touches.
rem
rem   --plan : affiche l etat et le reste a faire, sans reseau
rem            ni ecriture, puis s arrete.
rem ===================================================================
set "CE_ROOT=%~dp0"
set "CE_PYTHON="
if exist "%CE_ROOT%tools\python\python.exe" set "CE_PYTHON=%CE_ROOT%tools\python\python.exe"
if not defined CE_PYTHON if exist "%CE_ROOT%.venv\Scripts\python.exe" set "CE_PYTHON=%CE_ROOT%.venv\Scripts\python.exe"
if not defined CE_PYTHON (
  where python >nul 2>nul
  if not errorlevel 1 set "CE_PYTHON=python"
)
if not defined CE_PYTHON (
  echo [REFUS] Aucun Python trouve : rien n est recolte ni verse au coffre.
  endlocal
  exit /b 2
)
"%CE_PYTHON%" "%CE_ROOT%tools\coffre_donnees_externes.py" --racine "%CE_ROOT%." %*
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" echo [OK] Termine. Rapport : runtime\history\coffre_externe_rapport.json
if not "%RC%"=="0" echo [!] Code %RC% : lire runtime\history\coffre_externe_rapport.json
if /I not "%CV_NO_PAUSE%"=="1" pause
endlocal & exit /b %RC%
