@echo off
setlocal EnableExtensions
for %%I in ("%~dp0..\..") do set "ALINA_PROJECT_ROOT=%%~fI"
cd /d "%ALINA_PROJECT_ROOT%" || exit /b 1
cd /d "%ALINA_PROJECT_ROOT%\"
REM ============================================================================
REM  DIAGNOSTIC_LANCEUR.cmd
REM  Trouve POURQUOI LANCER_HYPERSMART.cmd et ANALYSER_BACKTESTS_REPLAYS.cmd
REM  se ferment aussitot. Rejoue le tronc commun etape par etape, ecrit un
REM  rapport lisible, et NE FERME JAMAIS la fenetre.
REM
REM  STRICTEMENT LECTURE SEULE : 0 ordre reel, 0 argent reel, 0 cle privee,
REM  0 seed, 0 signature, 0 depot/retrait, aucun endpoint d'execution.
REM  Seul le rapport diagnostic est ecrit sous runtime\reports\ (artefact local).
REM ============================================================================
set "RAPPORT_DIR=%ALINA_PROJECT_ROOT%\runtime\reports"
if not exist "%RAPPORT_DIR%\" mkdir "%RAPPORT_DIR%" >nul 2>&1
if not exist "%RAPPORT_DIR%\" (
  echo [ERREUR] Impossible de creer le dossier de rapport runtime :
  echo         %RAPPORT_DIR%
  endlocal & exit /b 32
)
set "RAPPORT=%RAPPORT_DIR%\DIAGNOSTIC_LANCEUR.txt"

echo.
echo   Diagnostic en cours (lecture seule)... quelques secondes.
echo.

call :corps > "%RAPPORT%" 2>&1
set "RC=%ERRORLEVEL%"

type "%RAPPORT%"
echo.
echo ============================================================
echo   Rapport enregistre ici :
echo   %RAPPORT%
echo   Envoie-moi ce fichier (ou copie/colle son contenu).
echo ============================================================
echo.
echo   Appuie sur une touche pour fermer.
pause >nul
endlocal & exit /b %RC%


REM ############################################################################
REM  CORPS DU DIAGNOSTIC (toute la sortie est redirigee vers le rapport)
REM ############################################################################
:corps
echo ============================================================
echo   DIAGNOSTIC DES LANCEURS HYPERSMART - LECTURE SEULE
echo ============================================================
echo   Date    : %DATE% %TIME%
echo   Racine  : %ALINA_PROJECT_ROOT%\
echo   ComSpec : %ComSpec%
echo   Windows : %OS%  /  processeur : %PROCESSOR_ARCHITECTURE%
echo.

echo ------------------------------------------------------------
echo   ETAPE 1 : fichiers indispensables du tronc commun
echo ------------------------------------------------------------
call :fichier "%ALINA_PROJECT_ROOT%\LANCER_HYPERSMART.cmd"
call :fichier "%ALINA_PROJECT_ROOT%\tools\launchers\ANALYSER_BACKTESTS_REPLAYS.cmd"
call :fichier "%ALINA_PROJECT_ROOT%\tools\portable_env.cmd"
call :fichier "%ALINA_PROJECT_ROOT%\tools\python\python.exe"
call :fichier "%ALINA_PROJECT_ROOT%\tools\python\python314._pth"
call :dossier "%ALINA_PROJECT_ROOT%\tools\python\Lib\site-packages"
call :dossier "%ALINA_PROJECT_ROOT%\src\hl_observer\ops"
call :dossier "%ALINA_PROJECT_ROOT%\hyper_smart_observer"
echo.

echo ------------------------------------------------------------
echo   ETAPE 2 : fins de ligne des .cmd (cmd.exe attend du CRLF)
echo ------------------------------------------------------------
echo   Un .cmd en LF seul peut mal se comporter sous cmd.exe.
echo   C'est la regle ecrite dans le .gitattributes de ce projet.
echo.
call :finsdeligne "%ALINA_PROJECT_ROOT%\LANCER_HYPERSMART.cmd"
call :finsdeligne "%ALINA_PROJECT_ROOT%\tools\launchers\ANALYSER_BACKTESTS_REPLAYS.cmd"
call :finsdeligne "%ALINA_PROJECT_ROOT%\tools\portable_env.cmd"
call :finsdeligne "%ALINA_PROJECT_ROOT%\tools\boucle_collecteur.cmd"
echo.

echo ------------------------------------------------------------
echo   ETAPE 3 : appel REEL de tools\portable_env.cmd
echo   (c'est la toute premiere instruction des DEUX lanceurs)
echo ------------------------------------------------------------
set "HYPERSMART_PYTHON="
set "HYPERSMART_PROJECT_ROOT="
call "%ALINA_PROJECT_ROOT%\tools\portable_env.cmd"
set "RC_ENV=%ERRORLEVEL%"
echo   code retour portable_env  : %RC_ENV%
echo   HYPERSMART_PROJECT_ROOT   : [%HYPERSMART_PROJECT_ROOT%]
echo   HYPERSMART_PYTHON         : [%HYPERSMART_PYTHON%]
echo   HYPERSMART_PYTHON_SOURCE  : [%HYPERSMART_PYTHON_SOURCE%]
echo   PYTHONPATH                : [%PYTHONPATH%]
echo.
if not "%RC_ENV%"=="0" (
  echo   ^>^>^> CAUSE TROUVEE : portable_env.cmd renvoie %RC_ENV%.
  echo        Les deux lanceurs s'arretent ici, SANS pause : d'ou la
  echo        fenetre qui se ferme aussitot. Code 30 = python.exe absent,
  echo        code 31 = migration de l'ancien runtime echouee.
  goto :corps_fin
)
if not defined HYPERSMART_PYTHON (
  echo   ^>^>^> CAUSE TROUVEE : portable_env.cmd renvoie 0 mais ne definit
  echo        PAS HYPERSMART_PYTHON. Les lanceurs sortent en 31, sans pause.
  echo        Symptome typique d'un .cmd en LF mal decoupe par cmd.exe.
  goto :corps_fin
)
echo   [OK] portable_env.cmd a fait son travail.
echo.

echo ------------------------------------------------------------
echo   ETAPE 4 : l'interpreteur portable demarre-t-il ?
echo ------------------------------------------------------------
"%HYPERSMART_PYTHON%" -V
set "RC_PY=%ERRORLEVEL%"
echo   code retour : %RC_PY%
if not "%RC_PY%"=="0" (
  echo   ^>^>^> CAUSE TROUVEE : tools\python\python.exe ne demarre pas.
  echo        Reconstruire le runtime : tools\preparer_python_portable.cmd
  goto :corps_fin
)
echo.

echo ------------------------------------------------------------
echo   ETAPE 5 : sondes Python (sys.path, imports, dependances)
echo ------------------------------------------------------------
if not exist "%ALINA_PROJECT_ROOT%\tools\diagnostic_lanceur.py" (
  echo   [ABSENT] tools\diagnostic_lanceur.py - sondes Python ignorees.
  goto :corps_fin
)
"%HYPERSMART_PYTHON%" "%ALINA_PROJECT_ROOT%\tools\diagnostic_lanceur.py" --root "%ALINA_PROJECT_ROOT%\."
set "RC_DIAG=%ERRORLEVEL%"
echo.
echo   code retour des sondes Python : %RC_DIAG%
if not "%RC_DIAG%"=="0" (
  echo   ^>^>^> CAUSE TROUVEE cote Python : voir la section
  echo        "PREMIERE CAUSE RACINE" juste au-dessus.
  goto :corps_fin
)
echo.

echo ------------------------------------------------------------
echo   ETAPE 6 : premieres instructions propres a chaque lanceur
echo ------------------------------------------------------------
echo   [LANCER_HYPERSMART] verrou d'instance (lecture de l'etat, sans prise)
"%HYPERSMART_PYTHON%" -c "import hl_observer.ops.verrou_lanceur as m; print('   module charge :', m.__file__)"
echo   code retour : %ERRORLEVEL%
echo.
echo   [ANALYSER] smoke portable non interactif
call "%ALINA_PROJECT_ROOT%\tools\launchers\ANALYSER_BACKTESTS_REPLAYS.cmd" portable-smoke
echo   code retour du smoke : %ERRORLEVEL%
echo.

:corps_fin
echo.
echo ============================================================
echo   FIN DU DIAGNOSTIC - aucune mutation economique, aucun fichier source modifie
echo   0 ordre reel, 0 argent reel, 0 cle privee, 0 signature
echo ============================================================
exit /b 0


REM ############################################################################
REM  SOUS-ROUTINES
REM ############################################################################
:fichier
if exist "%~1" (echo   [OK]      %~1) else (echo   [ABSENT]  %~1)
exit /b 0

:dossier
if exist "%~1\" (echo   [OK]      dossier %~1) else (echo   [ABSENT]  dossier %~1)
exit /b 0

:finsdeligne
if not exist "%~1" (
  echo   [ABSENT]  %~1
  exit /b 0
)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$b=[IO.File]::ReadAllBytes('%~1'); $crlf=0; $lf=0; for($i=0;$i -lt $b.Length;$i++){ if($b[$i] -eq 10){ if($i -gt 0 -and $b[$i-1] -eq 13){$crlf++} else {$lf++} } }; if($lf -gt 0){ Write-Output ('  [LF SEUL] ' + $crlf + ' CRLF / ' + $lf + ' LF nus  -> A CONVERTIR EN CRLF') } else { Write-Output ('  [CRLF OK] ' + $crlf + ' lignes') }"
exit /b 0
