@echo off
setlocal enableextensions enabledelayedexpansion
chcp 65001 >nul
title ALINA SMART FLOW - RATTRAPAGE DES DONNEES
set "CV_ROOT=%~dp0"
set "PYTHONUNBUFFERED=1"
set "PYTHONUTF8=1"

rem ===================================================================================
rem  RATTRAPAGE DES DONNEES — PAPER / LECTURE SEULE
rem
rem  A QUOI CA SERT. Le nombre d'observations INDEPENDANTES vaut
rem  `historique / duree_de_detention`. A 211 jours d'historique et 96 h de detention,
rem  cela fait 26 observations : c'est trop peu pour distinguer une strategie d'une
rem  serie chanceuse, et c'est la vraie raison pour laquelle le `t` honnete plafonne a
rem  0,54 quand il en faut 1,96. Le `t` croit en racine de `n`, donc x4 d'historique
rem  donne x2 sur le `t` — si l'effet tient sur les regimes plus anciens.
rem
rem  CE QU'IL FAIT. Il mesure ce qui manque, classe les taches par jours-coins gagnes
rem  par seconde de requete, et les execute UNE A LA FOIS avec une garde memoire.
rem  Il s'arrete tout seul si la RAM devient critique, au lieu de se faire tuer : l'etat
rem  est sauve apres chaque page, donc le passage suivant reprend exactement ou il
rem  s'etait arrete. Un verrou interdit deux rattrapages simultanes.
rem
rem  Les seules requetes sont `candleSnapshot` et `fundingHistory`, publics et en
rem  lecture seule. Aucun ordre, aucune cle, aucune signature.
rem ===================================================================================

rem --- Resolution de Python (meme ordre que les autres lanceurs) ---
set "CV_PYTHON="
set "CV_PY_ARGS="
if exist "%CV_ROOT%tools\python\python.exe" set "CV_PYTHON=%CV_ROOT%tools\python\python.exe"
if not defined CV_PYTHON if exist "%CV_ROOT%.venv\Scripts\python.exe" set "CV_PYTHON=%CV_ROOT%.venv\Scripts\python.exe"
if not defined CV_PYTHON (
  where py >nul 2>nul
  if not errorlevel 1 (
    set "CV_PYTHON=py"
    set "CV_PY_ARGS=-3"
  )
)
if not defined CV_PYTHON (
  where python >nul 2>nul
  if not errorlevel 1 set "CV_PYTHON=python"
)
if not defined CV_PYTHON (
  echo [NO_GO] Python 3 introuvable. Aucun rattrapage n'a ete lance.
  endlocal & exit /b 30
)

rem --- Arguments : (defaut) 6 h ; --plan n'execute rien ; --court tient en 40 min ---
set "BUDGET=21600"
set "SUITE="
for %%A in (%*) do (
  if /I "%%~A"=="--plan" set "SUITE=--plan"
  if /I "%%~A"=="--court" set "BUDGET=2400"
  if /I "%%~A"=="--long" set "BUDGET=43200"
  if /I "%%~A"=="--help" goto :help
  if /I "%%~A"=="-h" goto :help
)

echo.
echo === RATTRAPAGE DES DONNEES (PAPER / LECTURE SEULE) ===
if defined SUITE (
  echo   Mode : PLAN SEUL - rien ne sera demande au reseau.
) else (
  echo   Budget de ce passage : %BUDGET% s. Interrompre avec Ctrl+C ne perd RIEN :
  echo   l'etat est sauve apres chaque page et le passage suivant reprend ici.
)
echo.

"%CV_PYTHON%" %CV_PY_ARGS% -X utf8 "%CV_ROOT%tools\rattrapage_complet.py" --root "%CV_ROOT%." --budget-s %BUDGET% %SUITE%
set "RC=%ERRORLEVEL%"
echo.
if "%RC%"=="0" (
  echo [OK] Passage termine. Avancement : runtime\data\rattrapage_etat.json
) else if "%RC%"=="130" (
  echo [CTRL+C] Arret demande. AUCUNE DONNEE PERDUE : chaque page est ecrite en lignes entieres
  echo          et l'etat est sauve apres chacune. Relancer reprend exactement ici.
) else if "%RC%"=="3" (
  echo [DEJA EN COURS] Un autre rattrapage tourne : rien n'a ete lance.
) else (
  echo [ARRET] Code %RC%. L'etat est sauve : relancer reprend ou on s'est arrete.
)
echo.
echo Fermez cette fenetre, ou relancez pour continuer a creuser.
pause >nul
endlocal & exit /b %RC%

:help
echo Usage : RATTRAPAGE.cmd [--plan] [--court] [--long]
echo   (defaut)  6 h de requetes, une tache a la fois, garde memoire active
echo   --plan    AFFICHE ce qui manque et ce que ca couterait, puis s'arrete (0 requete)
echo   --court   40 min (le meme budget que celui du certificateur)
echo   --long    12 h
endlocal & exit /b 0
