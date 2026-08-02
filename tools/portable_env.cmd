@echo off
REM ============================================================================
REM  tools\portable_env.cmd  --  UNIQUE SOURCE DE VERITE de l'environnement (item 4)
REM ----------------------------------------------------------------------------
REM  Detecte AUTOMATIQUEMENT la racine du projet (relative a CE fichier, jamais un
REM  chemin absolu ni le repertoire courant), choisit le Python EMBARQUE portable,
REM  et REFUSE tout repli SILENCIEUX vers le Python systeme (item 4).
REM  Appele par LANCER_HYPERSMART.cmd / ANALYSER_BACKTESTS_REPLAYS.cmd /
REM  CREER_ARCHIVE_PORTABLE.cmd ; ne pas lancer directement.
REM ============================================================================

REM item 1 : racine = dossier parent de tools\ , resolue depuis %~dp0 (portable a tout chemin/disque).
for %%I in ("%~dp0..") do set "HYPERSMART_PROJECT_ROOT=%%~fI"
set "HYPERSMART_PYTHON="

REM --- 1) Python EMBARQUE (cible portable officielle : tools\python\python.exe) -----------------
set "HYPERSMART_EMBED_PYTHON=%HYPERSMART_PROJECT_ROOT%\tools\python\python.exe"
if exist "%HYPERSMART_EMBED_PYTHON%" (
  set "HYPERSMART_PYTHON=%HYPERSMART_EMBED_PYTHON%"
  set "PATH=%HYPERSMART_PROJECT_ROOT%\tools\python;%HYPERSMART_PROJECT_ROOT%\tools\python\Scripts;%PATH%"
  set "HYPERSMART_PYTHON_SOURCE=embedded-tools-python"
  goto :configured
)

REM --- 1bis) Ancien emplacement embarque (portable_runtime\python) : encore accepte ------------
set "HYPERSMART_PORTABLE_PYTHON=%HYPERSMART_PROJECT_ROOT%\portable_runtime\python\python.exe"
if exist "%HYPERSMART_PORTABLE_PYTHON%" (
  set "HYPERSMART_PYTHON=%HYPERSMART_PORTABLE_PYTHON%"
  set "PATH=%HYPERSMART_PROJECT_ROOT%\portable_runtime\python;%HYPERSMART_PROJECT_ROOT%\portable_runtime\python\Scripts;%PATH%"
  set "HYPERSMART_PYTHON_SOURCE=embedded-portable-runtime"
  goto :configured
)

REM --- 2) venv portable local (secondaire) -----------------------------------------------------
if exist "%HYPERSMART_PROJECT_ROOT%\.venv-portable\Scripts\python.exe" (
  set "HYPERSMART_PYTHON=%HYPERSMART_PROJECT_ROOT%\.venv-portable\Scripts\python.exe"
  set "PATH=%HYPERSMART_PROJECT_ROOT%\.venv-portable\Scripts;%PATH%"
  set "HYPERSMART_PYTHON_SOURCE=local-venv"
  goto :configured
)

REM --- 3) AUCUN runtime portable : on REFUSE le repli SILENCIEUX vers le Python systeme (item 4) -
REM  Le Python systeme n'est utilise QUE si l'utilisateur l'autorise EXPLICITEMENT, et on l'annonce.
if "%HYPERSMART_ALLOW_SYSTEM_PYTHON%"=="1" (
  where python >nul 2>&1
  if errorlevel 1 goto :aucun_python
  for /f "delims=" %%P in ('where python 2^>nul') do (
    if not defined HYPERSMART_PYTHON set "HYPERSMART_PYTHON=%%P"
  )
  set "HYPERSMART_PYTHON_SOURCE=system-EXPLICIT-OPTIN"
  echo.
  echo   [PORTABILITE] ATTENTION : runtime portable ABSENT. Utilisation du Python SYSTEME car
  echo   HYPERSMART_ALLOW_SYSTEM_PYTHON=1 ^(repli EXPLICITE, non silencieux^). Pour un dossier
  echo   reellement portable, execute une fois : tools\preparer_python_portable.cmd
  echo.
  goto :configured
)

REM  Par defaut : refus NET (jamais de repli silencieux). Diagnostic precis + marche a suivre offline.
echo.
echo   ERREUR PORTABILITE ^(item 4^) : aucun runtime Python PORTABLE dans ce dossier.
echo   Attendu : tools\python\python.exe ^(Python Windows x64 embarque^).
echo.
echo   Pour rendre ce dossier autonome ^(a faire UNE fois, sur un PC avec Internet^) :
echo       tools\preparer_python_portable.cmd
echo   Il telecharge le Python embarque + le wheelhouse hors ligne et verrouille les SHA-256.
echo.
echo   Repli EXPLICITE et temporaire ^(si un Python systeme est present^) :
echo       set HYPERSMART_ALLOW_SYSTEM_PYTHON=1  puis relance.
echo.
exit /b 30

:aucun_python
echo.
echo   ERREUR PORTABILITE : HYPERSMART_ALLOW_SYSTEM_PYTHON=1 mais AUCUN Python sur le PATH.
echo   Execute tools\preparer_python_portable.cmd depuis un PC connecte.
echo.
exit /b 30

:configured
REM item 5 : tout est relatif a la racine ; aucune ecriture hors du projet, aucun user-site.
set "PYTHONPATH=%HYPERSMART_PROJECT_ROOT%\src;%HYPERSMART_PROJECT_ROOT%;%HYPERSMART_PROJECT_ROOT%\tools;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
set "PYTHONNOUSERSITE=1"
set "PIP_USER=0"
REM wheelhouse hors ligne (item 3) : pip n'ira JAMAIS sur Internet si le wheelhouse est present.
set "HYPERSMART_WHEELHOUSE=%HYPERSMART_PROJECT_ROOT%\tools\wheelhouse"
if exist "%HYPERSMART_WHEELHOUSE%" (
  set "PIP_NO_INDEX=1"
  set "PIP_FIND_LINKS=%HYPERSMART_WHEELHOUSE%"
)
set "HYPERSMART_RUNTIME_ROOT=%HYPERSMART_PROJECT_ROOT%"
exit /b 0
