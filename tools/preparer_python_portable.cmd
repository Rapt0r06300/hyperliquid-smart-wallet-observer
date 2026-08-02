@echo off
setlocal EnableExtensions
REM ============================================================================
REM  tools\preparer_python_portable.cmd   (items 2 & 3)
REM  A executer UNE fois, sur un PC Windows x64 avec Internet. Rend le dossier
REM  autonome : Python Windows x64 EMBARQUE + wheelhouse HORS LIGNE verrouille.
REM  Apres ca, le dossier se copie sur n'importe quel PC/disque/chemin et tourne
REM  SANS Python/pip/Git systeme et SANS Internet.
REM  PAPER STRICT : 0 ordre reel, 0 cle privee, 0 signature, aucun /exchange.
REM ============================================================================
cd /d "%~dp0.."
set "ROOT=%CD%"
echo.
echo ============================================================
echo   Preparation du runtime PORTABLE HyperSmart (Windows x64)
echo   Racine : %ROOT%
echo ============================================================
echo.

REM --- 1) Python embarque + dependances + manifeste (script existant, SHA-256 verifie) ---------
echo   [1/3] Python embarque officiel (telechargement + verification SHA-256 + dependances)...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_portable_runtime.ps1" -ProjectRoot "%ROOT%"
if errorlevel 1 (
  echo.
  echo   [ECHEC] L'installation du Python embarque a echoue. Voir la sortie ci-dessus.
  endlocal & exit /b 40
)

REM --- 2) Localiser le Python embarque fraichement installe ------------------------------------
set "EMBED=%ROOT%\tools\python\python.exe"
if not exist "%EMBED%" set "EMBED=%ROOT%\portable_runtime\python\python.exe"
if not exist "%EMBED%" (
  echo   [ECHEC] Python embarque introuvable apres installation.
  endlocal & exit /b 41
)

REM --- 3) Wheelhouse HORS LIGNE + verrou SHA-256 (item 3) --------------------------------------
echo   [2/3] Construction du wheelhouse hors ligne (pip download win_amd64)...
if not exist "%ROOT%\tools\wheelhouse" mkdir "%ROOT%\tools\wheelhouse" >nul 2>&1
"%EMBED%" -m pip download --disable-pip-version-check --no-input ^
   --requirement "%ROOT%\requirements-portable.txt" ^
   --dest "%ROOT%\tools\wheelhouse"
if errorlevel 1 (
  echo   [AVERTISSEMENT] Certaines roues n'ont pu etre telechargees. Le wheelhouse peut etre incomplet.
)

echo   [3/3] Verrouillage des versions + SHA-256 du wheelhouse...
"%EMBED%" -m tools.wheelhouse_lock --wheelhouse "%ROOT%\tools\wheelhouse" --ecrire "%ROOT%\tools\wheelhouse\WHEELHOUSE_LOCK.json"
if errorlevel 1 (
  echo   [AVERTISSEMENT] Verrou du wheelhouse non ecrit.
)

echo.
echo   [OK] Runtime portable pret.
echo        - Python embarque : %EMBED%
echo        - Wheelhouse hors ligne : %ROOT%\tools\wheelhouse ^(+ WHEELHOUSE_LOCK.json^)
echo        Le dossier peut maintenant etre copie/archive et lance sur un autre PC hors ligne.
echo.
endlocal & exit /b 0
