@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
pushd "%~dp0"
if errorlevel 1 goto :bad_location

rem ============================================================
rem  RECONCILIATEUR UNIQUE  Local <-> GitHub  (fichier autonome)
rem  - Moteur commit + push fast-forward EMBARQUE dans ce .cmd
rem    (base64, decode certutil, extrait dans %TEMP% puis efface).
rem  - Phase shards SAFE via le moteur data du depot
rem    (tools\sync_complete_clone.py : moteur du depot, pas un
rem     lanceur, il reste la pour ne jamais diverger).
rem  Aucun push force, reset, clean, stash ou effacement de donnees.
rem ============================================================
set "GIT_LFS_SKIP_SMUDGE=1"
set "ALINA_ROOT=%~dp0"
set "ALINA_SKIP_CODE=0"
set "ALINA_SKIP_SHARDS=0"
set "ALINA_DRYRUN=0"
set "ALINA_SHARDS_ARGS=--preflight-only"
set "RC=1"
set "ALINA_TMP_PY=%TEMP%\alina_reconcile_%RANDOM%%RANDOM%.py"
set "ALINA_TMP_B64=%TEMP%\alina_reconcile_%RANDOM%%RANDOM%.b64"

if /I "%~1"=="--help" goto :help
if /I "%~1"=="-h" goto :help
if "%~1"=="" goto :args_done
if /I "%~1"=="--dry-run" ( set "ALINA_DRYRUN=1" & set "ALINA_SKIP_SHARDS=1" & goto :args_done )
if /I "%~1"=="--code-only" ( set "ALINA_SKIP_SHARDS=1" & goto :args_done )
if /I "%~1"=="--shards-only" ( set "ALINA_SKIP_CODE=1" & goto :args_done )
if /I "%~1"=="--download-safe" ( set "ALINA_SHARDS_ARGS=--download-safe --max-download-gib 256" & goto :args_done )
if /I "%~1"=="--all-safe" ( set "ALINA_SHARDS_ARGS=--download-safe --all-safe" & goto :args_done )
if /I "%~1"=="--unpack-safe" ( set "ALINA_SHARDS_ARGS=--download-safe --unpack-safe --max-download-gib 256" & goto :args_done )
if /I "%~1"=="--prune-cache" ( set "ALINA_SHARDS_ARGS=--prune-cache-only" & goto :args_done )
if /I "%~1"=="--catalog-budget" ( set "ALINA_SHARDS_ARGS=--catalog-budget" & set "ALINA_SKIP_CODE=1" & goto :args_done )
goto :bad_option
:args_done

echo ============================================================
echo  ALINA SMART FLOW - RECONCILIATION LOCAL ^<-^> GITHUB (1 fichier)
echo  Commit local + push fast-forward + shards SAFE (preflight)
echo  Aucun push force, reset, clean ou effacement de donnees
echo ============================================================
echo [05%%] [LANCEUR 1/9] Racine : %ALINA_ROOT%
if "%ALINA_DRYRUN%"=="1" echo        Mode : DRY-RUN (construit le commit, ne pousse rien)
if "%ALINA_SKIP_CODE%"=="1" echo        Mode : shards uniquement (pas de code)
echo        Shards : %ALINA_SHARDS_ARGS%

rem --- Git ---
if exist "%ALINA_ROOT%tools\git\cmd\git.exe" set "HYPERSMART_GIT=%ALINA_ROOT%tools\git\cmd\git.exe"
if not defined HYPERSMART_GIT if exist "%ProgramFiles%\Git\cmd\git.exe" set "HYPERSMART_GIT=%ProgramFiles%\Git\cmd\git.exe"
if not defined HYPERSMART_GIT if exist "%LOCALAPPDATA%\Programs\Git\cmd\git.exe" set "HYPERSMART_GIT=%LOCALAPPDATA%\Programs\Git\cmd\git.exe"
if not defined HYPERSMART_GIT for %%G in (git.exe) do if not "%%~$PATH:G"=="" set "HYPERSMART_GIT=%%~$PATH:G"
if not defined HYPERSMART_GIT goto :missing_git
echo [15%%] [LANCEUR 2/9] Git : %HYPERSMART_GIT%
"%HYPERSMART_GIT%" --version
if errorlevel 1 goto :missing_git

rem --- Python 3.11+ ---
echo [22%%] [LANCEUR 3/9] Recherche de Python 3.11 ou plus
set "HYPERSMART_PYTHON="
set "PYARGS="
if exist "%ALINA_ROOT%tools\python\python.exe" set "HYPERSMART_PYTHON=%ALINA_ROOT%tools\python\python.exe"
if defined HYPERSMART_PYTHON goto :python_ready
where py.exe >nul 2>nul
if errorlevel 1 goto :try_python
set "HYPERSMART_PYTHON=py"
set "PYARGS=-3"
goto :python_ready
:try_python
where python.exe >nul 2>nul
if errorlevel 1 goto :missing_python
set "HYPERSMART_PYTHON=python"
:python_ready
"%HYPERSMART_PYTHON%" %PYARGS% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>nul
if errorlevel 1 goto :missing_python
"%HYPERSMART_PYTHON%" %PYARGS% --version

rem --- Extraction du moteur embarque (base64 -> %TEMP%) ---
rem  Primaire : PowerShell (FromBase64String, le plus fiable).
rem  Secours  : for/f + certutil (base64 natif Windows).
echo [30%%] [LANCEUR 4/9] Extraction du moteur reconcile embarque
if exist "%ALINA_TMP_B64%" del /q "%ALINA_TMP_B64%" >nul 2>nul
if exist "%ALINA_TMP_PY%" del /q "%ALINA_TMP_PY%" >nul 2>nul
set "ALINA_EXTRACT_OK="
where powershell.exe >nul 2>nul
if errorlevel 1 goto :extract_certutil
powershell -NoProfile -Command "$ErrorActionPreference='Stop'; $f=Get-Content -LiteralPath '%~f0'; $s=[array]::IndexOf($f,'#ALINA_B64_START'); $e=[array]::IndexOf($f,'#ALINA_B64_END'); if($s -lt 0 -or $e -le $s){exit 9}; [IO.File]::WriteAllBytes('%ALINA_TMP_PY%',[Convert]::FromBase64String(($f[($s+1)..($e-1)] -join '')))" >nul 2>nul
if not errorlevel 1 if exist "%ALINA_TMP_PY%" set "ALINA_EXTRACT_OK=1"
if defined ALINA_EXTRACT_OK goto :extract_validate
:extract_certutil
where certutil.exe >nul 2>nul
if errorlevel 1 goto :extract_failed
set "ALINA_GRAB="
for /f "usebackq delims=" %%L in ("%~f0") do (
  if "%%L"=="#ALINA_B64_END" set "ALINA_GRAB="
  if defined ALINA_GRAB echo(%%L>>"%ALINA_TMP_B64%"
  if "%%L"=="#ALINA_B64_START" set "ALINA_GRAB=1"
)
if not exist "%ALINA_TMP_B64%" goto :extract_failed
certutil -decode "%ALINA_TMP_B64%" "%ALINA_TMP_PY%" >nul 2>nul
if errorlevel 1 goto :extract_failed
del /q "%ALINA_TMP_B64%" >nul 2>nul
if exist "%ALINA_TMP_PY%" set "ALINA_EXTRACT_OK=1"
:extract_validate
if not defined ALINA_EXTRACT_OK goto :extract_failed
if not exist "%ALINA_TMP_PY%" goto :extract_failed
"%HYPERSMART_PYTHON%" %PYARGS% -c "import ast,sys; ast.parse(open(sys.argv[1],'rb').read())" "%ALINA_TMP_PY%" >nul 2>nul
if errorlevel 1 goto :extract_failed
echo [35%%] [LANCEUR 5/9] Moteur reconcile extrait et valide

rem --- Moteur shards (module du depot) ---
set "ALINA_SHARDS_ENGINE=%ALINA_ROOT%tools\sync_complete_clone.py"
if not exist "%ALINA_SHARDS_ENGINE%" goto :missing_shards_engine
"%HYPERSMART_PYTHON%" %PYARGS% -c "import ast,sys; ast.parse(open(sys.argv[1],'rb').read())" "%ALINA_SHARDS_ENGINE%" >nul 2>nul
if errorlevel 1 goto :missing_shards_engine
echo [40%%] [LANCEUR 6/9] Moteur shards du depot valide

if "%ALINA_SKIP_CODE%"=="1" goto :phase_b

rem --- PHASE CODE : commit WIP + push fast-forward (un seul moteur) ---
echo.
echo [55%%] [LANCEUR 7/9] PHASE CODE - commit local + push fast-forward
set "ALINA_FF_ARGS="
if "%ALINA_DRYRUN%"=="1" set "ALINA_FF_ARGS=--dry-run"
"%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_TMP_PY%" --git "%HYPERSMART_GIT%" --root "%ALINA_ROOT%." %ALINA_FF_ARGS%
set "RC_FF=%ERRORLEVEL%"
if not "%RC_FF%"=="0" goto :ff_failed
if "%ALINA_DRYRUN%"=="1" echo [80%%] [DRY-RUN] commit construit et verifie ; aucun push effectue.
if not "%ALINA_DRYRUN%"=="1" echo [80%%] [OK] Code pousse sur origin/main.
if "%ALINA_DRYRUN%"=="1" goto :finish_ok

:phase_b
if "%ALINA_SKIP_SHARDS%"=="1" goto :skip_shards
echo.
echo [90%%] [LANCEUR 8/9] PHASE SHARDS - AlinaSync SAFE
echo        Arguments : %ALINA_SHARDS_ARGS%
"%HYPERSMART_PYTHON%" %PYARGS% "%ALINA_SHARDS_ENGINE%" %ALINA_SHARDS_ARGS%
set "RC_SHARDS=%ERRORLEVEL%"
if not "%RC_SHARDS%"=="0" goto :shards_failed
echo [98%%] [OK] Phase shards terminee.
goto :finish_ok

:skip_shards
echo [90%%] [LANCEUR 8/9] PHASE SHARDS - ignoree
goto :finish_ok

:finish_ok
set "RC=0"
goto :finish

:bad_option
echo [NO_GO] Option inconnue : %~1  (voir --help)
set "RC=2"
goto :finish

:help
echo Usage : POUSSER-GITHUB-FORCE.cmd [option]
echo.
echo  (defaut)         commit local + push fast-forward + shards preflight
echo  --dry-run        construit le commit, verifie, NE POUSSE PAS
echo  --code-only      commit + push, pas de phase shards
echo  --shards-only    AlinaSync seul, pas de code
echo  --download-safe  + telecharge SAFE replayable (plafond 256 GiB)
echo  --all-safe       + telecharge tout SAFE sans plafond
echo  --unpack-safe    + telecharge et decompresse JSONL
echo  --prune-cache    purge le cache verifie inutilise
echo  --catalog-budget compta offline SAFE/PARTIAL/REJECT, aucun reseau
echo.
echo  Tout est dans ce seul fichier (moteur commit+push embarque).
echo  Aucun force-push, reset, clean, stash ou suppression silencieuse.
set "RC=0"
goto :finish

:bad_location
echo [NO_GO] Impossible d'ouvrir le dossier du CMD.
set "RC=3"
goto :finish
:missing_git
echo [NO_GO] Git introuvable.
set "RC=30"
goto :finish
:missing_python
echo [NO_GO] Python 3.11 ou plus requis.
set "RC=31"
goto :finish
:missing_certutil
echo [NO_GO] certutil introuvable (decodeur base64 Windows requis).
set "RC=36"
goto :finish
:extract_failed
echo [NO_GO] Extraction du moteur embarque impossible (base64/certutil).
if exist "%ALINA_TMP_B64%" del /q "%ALINA_TMP_B64%" >nul 2>nul
set "RC=37"
goto :finish
:missing_shards_engine
echo [NO_GO] Moteur shards manquant/invalide : tools\sync_complete_clone.py
set "RC=35"
goto :finish
:ff_failed
echo.
echo [NO_GO] Reconciliation code echouee avec code %RC_FF%. Aucune operation de force.
echo         Les lignes [WIP]/[FF] ci-dessus donnent la cause exacte.
echo         Ton HEAD local est sauvegarde dans la ref refs/alina/local-work.
set "RC=%RC_FF%"
goto :finish
:shards_failed
echo.
echo [NO_GO] Phase shards echouee avec code %RC_SHARDS%.
if not "%ALINA_SKIP_CODE%"=="1" echo         Le code a deja ete pousse (phase code OK).
set "RC=%RC_SHARDS%"
goto :finish

:finish
if exist "%ALINA_TMP_PY%" del /q "%ALINA_TMP_PY%" >nul 2>nul
if exist "%ALINA_TMP_B64%" del /q "%ALINA_TMP_B64%" >nul 2>nul
echo.
echo [100%%] [LANCEUR 9/9] Fin du lanceur - code retour %RC%
if exist "%ALINA_ROOT%runtime\recovery\full\SYNC_REPORT.json" echo Rapport shards: %ALINA_ROOT%runtime\recovery\full\SYNC_REPORT.json
if /I "%HYPERSMART_PUSH_NO_PAUSE%"=="1" goto :finish_cleanup
pause
:finish_cleanup
popd
endlocal & exit /b %RC%

rem Le moteur reconcile (commit WIP + push fast-forward) est embarque
rem ci-dessous en base64 entre les marqueurs. Ne rien editer a la main :
rem regenerer via l'outil de build si le moteur change.
#ALINA_B64_START

IyEvdXNyL2Jpbi9lbnYgcHl0aG9uMwoiIiJSZWNvbmNpbGlhdGV1ciB1bmlxdWUgTG9jYWwgPC0+
IEdpdEh1YiAoY29tbWl0IFdJUCArIHB1c2ggZmFzdC1mb3J3YXJkKS4KCkVtYmFycXVlIGRhbnMg
UE9VU1NFUi1HSVRIVUItRk9SQ0UuY21kIChiYXNlNjQpLCBleHRyYWl0IGEgbCdleGVjdXRpb24u
CgpQb3VycXVvaSBsYSBwbG9tYmVyaWUgOiBjZSBkZXBvdCBlc3QgdW4gY2xvbmUgc2hhbGxvdyAr
IHBhcnRpZWwKKGZpbHRlcj1ibG9iOm5vbmUpIDsgYGdpdCByZWJhc2VgIG5lIGZhaXQgUklFTiBk
ZXNzdXMsIGV0IGBnaXQgYWRkYC8KYGdpdCBzdGF0dXNgL2BnaXQgd3JpdGUtdHJlZWAgc3VyIGwn
aW5kZXggZ2VhbnQgKGNhdGFsb2cvID0gbWlsbGllcnMgZGUKZmljaGllcnMgKyBncm9zIEpTT04p
IHRpbWUtb3V0LiBPbiBwYXNzZSBkb25jIHBhciA6CiAgMSkgc25hcHNob3QgZHUgY29kZSBsb2Nh
bCBtb2RpZmllIC0+IGNvbW1pdCBsb2NhbCAoaW5kZXggdGVtcG9yYWlyZSwgSEVBRAogICAgIGNv
bW1lIGJhc2UsIG9uIG5lIHRvdWNoZSBRVUUgbGVzIGNoZW1pbnMgZGUgY29kZSwgamFtYWlzIGNh
dGFsb2cvKSA7CiAgMikgcmVjb25zdHJ1Y3Rpb24gZCd1biBjb21taXQgPSBhcmJyZSBkJ29yaWdp
bi9tYWluICsgU0VVTFMgbGVzIGZpY2hpZXJzCiAgICAgY2hhbmdlcyBwYXIgbGUgbG9jYWwsIHB1
aXMgYXZhbmNlIGRlIHJlZnMvaGVhZHMvPGJyYW5jaD4gZXQgcHVzaC4KQXVjdW4gcmViYXNlLCBh
dWN1biBmb3JjZSwgYXVjdW4gcmVzZXQsIGF1Y3VuIGNsZWFuLiBjYXRhbG9nLyByZXN0ZQpleGFj
dGVtZW50IGEgb3JpZ2luL21haW4gc2F1ZiBzaSB1biBjb21taXQgbG9jYWwgYSBjaGFuZ2UgdW4g
Y2hlbWluIGNhdGFsb2cvLgoKU2VjdXJpdGUgOiBwYXBlci9yZWFkLW9ubHkgOyBuZSBwb3Vzc2Ug
cXVlIGR1IGNvZGUuIEVuIGNhcyBkJ2VjaGVjLCBsYWlzc2UKdW5lIHJlZiBkZSBzZWNvdXJzIHJl
ZnMvYWxpbmEvbG9jYWwtd29yayBzdXIgbGUgSEVBRCBsb2NhbCBkJ29yaWdpbmUuCiIiIgpmcm9t
IF9fZnV0dXJlX18gaW1wb3J0IGFubm90YXRpb25zCmltcG9ydCBhcmdwYXJzZQppbXBvcnQgb3MK
aW1wb3J0IHN1YnByb2Nlc3MKaW1wb3J0IHN5cwoKUk9PVCA9IG9zLmVudmlyb24uZ2V0KCJBTElO
QV9ST09UIikgb3Igb3MucGF0aC5kaXJuYW1lKAogICAgb3MucGF0aC5kaXJuYW1lKG9zLnBhdGgu
YWJzcGF0aChfX2ZpbGVfXykpKQpHSVQgPSAiZ2l0IgoKIyBDaGVtaW5zIEpBTUFJUyBpbmNsdXMg
ZGFucyB1biBzbmFwc2hvdCBkZSBjb2RlIChkYXRhLXBsYW5lIC8gcnVudGltZSAvIGdpdCkuCkVY
Q0xVREVfUFJFRklYRVMgPSAoCiAgICAiY2F0YWxvZy8iLCAicnVudGltZS8iLCAibG9ncy8iLCAi
bG9nLyIsICIuZ2l0LyIsICJkYXRhLyIsICJkYXRhc2V0cy8iLAogICAgImNhY2hlLyIsICIuY2Fj
aGUvIiwgInRtcC8iLCAidGVtcC8iLCAib3V0cHV0cy8iLCAicnVudGltZV9yZWNvdmVyeS8iLAop
CiMgU3VmZml4ZXMgZGF0YSB2b2x1bWluZXV4IHF1ZSBsJ29uIG5lIGNvbW1pdGUgamFtYWlzIGVu
IFdJUCBhdXRvbWF0aXF1ZS4KRVhDTFVERV9TVUZGSVhFUyA9ICgKICAgICIuZGIiLCAiLnNxbGl0
ZSIsICIuc3FsaXRlMyIsICIuZGItd2FsIiwgIi5kYi1zaG0iLCAiLnBhcnF1ZXQiLCAiLmpzb25s
IiwKICAgICIuemlwIiwgIi5neiIsICIudGFyIiwgIi43eiIsICIubG9nIiwgIi5weWMiLCAiLnB5
byIsCikKIyBQbGFmb25kIGRlIHRhaWxsZSAob2N0ZXRzKSBwb3VyIHVuIGZpY2hpZXIgZGUgY29k
ZSBjb21taXR0ZSBhdXRvbWF0aXF1ZW1lbnQuCk1BWF9XSVBfRklMRV9CWVRFUyA9IDIgKiAxMDI0
ICogMTAyNCAgIyAyIE1pQgoKCmRlZiBfaW5kZXhfZGlyKCk6CiAgICAjIERvc3NpZXIgZGVzIGlu
ZGV4IHRlbXBvcmFpcmVzLiBQYXIgZGVmYXV0IC5naXQgKGNvcnJlY3Qgc3VyIFdpbmRvd3MsCiAg
ICAjIFNTRCByYXBpZGUpLiBBTElOQV9JTkRFWF9ESVIgcGVybWV0IGRlIGxlIHBvc2VyIHN1ciB1
biBkaXNxdWUgcmFwaWRlCiAgICAjIHF1YW5kIC5naXQgZXN0IHN1ciB1biBtb250YWdlIGxlbnQg
KHBvbnQpIDsgYXVjdW4gZWZmZXQgc3VyIFdpbmRvd3MuCiAgICByZXR1cm4gb3MuZW52aXJvbi5n
ZXQoIkFMSU5BX0lOREVYX0RJUiIpIG9yIG9zLnBhdGguam9pbihST09ULCAiLmdpdCIpCgoKZGVm
IGdpdCgqYSwgZW52X2V4dHJhPU5vbmUsIGlucD1Ob25lKToKICAgIGVudiA9IGRpY3Qob3MuZW52
aXJvbiwgR0lUX0xGU19TS0lQX1NNVURHRT0iMSIpCiAgICBpZiBlbnZfZXh0cmE6CiAgICAgICAg
ZW52LnVwZGF0ZShlbnZfZXh0cmEpCiAgICByZXR1cm4gc3VicHJvY2Vzcy5ydW4oW0dJVCwgKmFd
LCBjd2Q9Uk9PVCwgY2FwdHVyZV9vdXRwdXQ9VHJ1ZSwKICAgICAgICAgICAgICAgICAgICAgICAg
ICB0ZXh0PVRydWUsIGVudj1lbnYsIGlucHV0PWlucCkKCgpkZWYgZ2l0X29rKCphLCAqKmspOgog
ICAgciA9IGdpdCgqYSwgKiprKQogICAgaWYgci5yZXR1cm5jb2RlICE9IDA6CiAgICAgICAgcmFp
c2UgUnVudGltZUVycm9yKGYiZ2l0IHsnICcuam9pbihhKX06IHtyLnN0ZGVyci5zdHJpcCgpWzoz
MDBdfSIpCiAgICByZXR1cm4gci5zdGRvdXQKCgpkZWYgaXNfY29kZV9wYXRoKHA6IHN0cikgLT4g
Ym9vbDoKICAgIHEgPSBwLnJlcGxhY2UoIlxcIiwgIi8iKQogICAgbG93ID0gcS5sb3dlcigpCiAg
ICBpZiBhbnkobG93LnN0YXJ0c3dpdGgoeCkgZm9yIHggaW4gRVhDTFVERV9QUkVGSVhFUyk6CiAg
ICAgICAgcmV0dXJuIEZhbHNlCiAgICBpZiBhbnkobG93LmVuZHN3aXRoKHgpIGZvciB4IGluIEVY
Q0xVREVfU1VGRklYRVMpOgogICAgICAgIHJldHVybiBGYWxzZQogICAgcmV0dXJuIFRydWUKCgpk
ZWYgY3VycmVudF9icmFuY2goZGVmYXVsdD0ibWFpbiIpIC0+IHN0cjoKICAgIHIgPSBnaXQoInN5
bWJvbGljLXJlZiIsICItLXNob3J0IiwgIi1xIiwgIkhFQUQiKQogICAgYiA9IHIuc3Rkb3V0LnN0
cmlwKCkKICAgIHJldHVybiBiIG9yIGRlZmF1bHQKCgpkZWYgZXhjbHVkZV9wYXRoc3BlY3MoKToK
ICAgICMgUGF0aHNwZWMgcG9zaXRpZiAiLiIgKyBleGNsdXNpb25zIGRlcyBkb3NzaWVycyBkYXRh
L3J1bnRpbWUsIHBvdXIgbmUKICAgICMgSkFNQUlTIHBhcmNvdXJpciBjYXRhbG9nLyAoZGVzIG1p
bGxpZXJzIGRlIGZpY2hpZXJzKSA6IHJhcGlkZSBldCBzdXIuCiAgICBzcGVjcyA9IFsiLiJdCiAg
ICBmb3IgcGZ4IGluIEVYQ0xVREVfUFJFRklYRVM6CiAgICAgICAgZCA9IHBmeC5yc3RyaXAoIi8i
KQogICAgICAgIGlmIGQgYW5kIGQgIT0gIi5naXQiOgogICAgICAgICAgICBzcGVjcy5hcHBlbmQo
ZiI6KGV4Y2x1ZGUpe2R9IikKICAgIHJldHVybiBzcGVjcwoKCiMgLS0tLS0tLS0tLS0tLS0tLS0t
LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0K
IyBQSEFTRSAxIDogc25hcHNob3QgZHUgY29kZSBsb2NhbCBub24gY29tbWl0dGUgLT4gY29tbWl0
IGxvY2FsCiMgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t
LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0KZGVmIHNuYXBzaG90X3dpcChicmFuY2g6IHN0ciwg
ZHJ5OiBib29sKToKICAgIGhlYWQgPSBnaXRfb2soInJldi1wYXJzZSIsICJIRUFEIikuc3RyaXAo
KQoKICAgICMgRmljaGllcnMgc3VpdmlzIG1vZGlmaWVzL3N1cHByaW1lcyAodnMgd29ya2luZyB0
cmVlKS4gT24gZXhjbHV0IGxlcwogICAgIyBkb3NzaWVycyBkYXRhL3J1bnRpbWUgYXUgbml2ZWF1
IHBhdGhzcGVjIDogY2F0YWxvZy8gbidlc3QgamFtYWlzIHBhcmNvdXJ1LgogICAgeHAgPSBleGNs
dWRlX3BhdGhzcGVjcygpCiAgICBtb2RpZmllZCwgZGVsZXRlZCA9IFtdLCBbXQogICAgb3V0ID0g
Z2l0KCJkaWZmIiwgIi0tbmFtZS1zdGF0dXMiLCAiLXoiLCAiSEVBRCIsICItLSIsICp4cCkKICAg
IGlmIG91dC5yZXR1cm5jb2RlID09IDAgYW5kIG91dC5zdGRvdXQ6CiAgICAgICAgdG9rcyA9IG91
dC5zdGRvdXQuc3BsaXQoIlwwIikKICAgICAgICBpID0gMAogICAgICAgIHdoaWxlIGkgPCBsZW4o
dG9rcyk6CiAgICAgICAgICAgIHN0ID0gdG9rc1tpXQogICAgICAgICAgICBpZiBub3Qgc3Q6CiAg
ICAgICAgICAgICAgICBpICs9IDEKICAgICAgICAgICAgICAgIGNvbnRpbnVlCiAgICAgICAgICAg
IGNvZGUgPSBzdFswXQogICAgICAgICAgICBpZiBjb2RlIGluICgiUiIsICJDIikgYW5kIGkgKyAy
IDwgbGVuKHRva3MpOgogICAgICAgICAgICAgICAgIyByZW5hbWUvY29weSA6IG9sZCwgbmV3CiAg
ICAgICAgICAgICAgICBuZXdwID0gdG9rc1tpICsgMl0KICAgICAgICAgICAgICAgIG1vZGlmaWVk
LmFwcGVuZChuZXdwKQogICAgICAgICAgICAgICAgZGVsZXRlZC5hcHBlbmQodG9rc1tpICsgMV0p
CiAgICAgICAgICAgICAgICBpICs9IDMKICAgICAgICAgICAgZWxpZiBpICsgMSA8IGxlbih0b2tz
KToKICAgICAgICAgICAgICAgIHBhdGggPSB0b2tzW2kgKyAxXQogICAgICAgICAgICAgICAgaWYg
Y29kZSA9PSAiRCI6CiAgICAgICAgICAgICAgICAgICAgZGVsZXRlZC5hcHBlbmQocGF0aCkKICAg
ICAgICAgICAgICAgIGVsc2U6CiAgICAgICAgICAgICAgICAgICAgbW9kaWZpZWQuYXBwZW5kKHBh
dGgpCiAgICAgICAgICAgICAgICBpICs9IDIKICAgICAgICAgICAgZWxzZToKICAgICAgICAgICAg
ICAgIGkgKz0gMQoKICAgICMgRmljaGllcnMgbm9uIHN1aXZpcyAoaG9ycyAuZ2l0aWdub3JlKSwg
bWVtZXMgZXhjbHVzaW9ucy4KICAgIHVudHJhY2tlZCA9IFtwIGZvciBwIGluIGdpdF9vaygKICAg
ICAgICAibHMtZmlsZXMiLCAiLS1vdGhlcnMiLCAiLS1leGNsdWRlLXN0YW5kYXJkIiwgIi16Iiwg
Ii0tIiwgKnhwCiAgICApLnNwbGl0KCJcMCIpIGlmIHBdCgogICAgIyBHYXJkZSB1bmlxdWVtZW50
IGxlIGNvZGUsIGRlIHRhaWxsZSByYWlzb25uYWJsZSwgcHJlc2VudCBzdXIgZGlzcXVlLgogICAg
YWRkID0gW10KICAgIGZvciBwIGluIHNvcnRlZChzZXQobW9kaWZpZWQpIHwgc2V0KHVudHJhY2tl
ZCkpOgogICAgICAgIGlmIG5vdCBpc19jb2RlX3BhdGgocCk6CiAgICAgICAgICAgIGNvbnRpbnVl
CiAgICAgICAgYXAgPSBvcy5wYXRoLmpvaW4oUk9PVCwgcCkKICAgICAgICBpZiBub3Qgb3MucGF0
aC5pc2ZpbGUoYXApOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIHRyeToKICAgICAgICAg
ICAgaWYgb3MucGF0aC5nZXRzaXplKGFwKSA+IE1BWF9XSVBfRklMRV9CWVRFUzoKICAgICAgICAg
ICAgICAgIGNvbnRpbnVlCiAgICAgICAgZXhjZXB0IE9TRXJyb3I6CiAgICAgICAgICAgIGNvbnRp
bnVlCiAgICAgICAgYWRkLmFwcGVuZChwKQogICAgcm0gPSBbcCBmb3IgcCBpbiBzb3J0ZWQoc2V0
KGRlbGV0ZWQpKSBpZiBpc19jb2RlX3BhdGgocCldCgogICAgaWYgbm90IGFkZCBhbmQgbm90IHJt
OgogICAgICAgIHByaW50KCJbV0lQXSBhdWN1biBjaGFuZ2VtZW50IGRlIGNvZGUgbG9jYWwgYSBm
aWdlci4iLCBmbHVzaD1UcnVlKQogICAgICAgIHJldHVybiBoZWFkLCAwCgogICAgcHJpbnQoZiJb
V0lQXSB7bGVuKGFkZCl9IGZpY2hpZXIocykgY29kZSBtb2RpZmllKHMpL25vdXZlYXUoeCksICIK
ICAgICAgICAgIGYie2xlbihybSl9IHN1cHByZXNzaW9uKHMpLiIsIGZsdXNoPVRydWUpCiAgICBp
ZiBkcnk6CiAgICAgICAgZm9yIHAgaW4gYWRkWzoyMF06CiAgICAgICAgICAgIHByaW50KGYiICAg
ICAgICsge3B9IiwgZmx1c2g9VHJ1ZSkKICAgICAgICBmb3IgcCBpbiBybVs6MjBdOgogICAgICAg
ICAgICBwcmludChmIiAgICAgICAtIHtwfSIsIGZsdXNoPVRydWUpCgogICAgIyBJbmRleCB0ZW1w
b3JhaXJlIHNlZWRlIHBhciBsJ2FyYnJlIGRlIEhFQUQgKG5lIHRvdWNoZSBwYXMgbCdpbmRleCBy
ZWVsKS4KICAgIGlkeCA9IG9zLnBhdGguam9pbihfaW5kZXhfZGlyKCksICJhbGluYS13aXAtaW5k
ZXgiKQogICAgaWYgb3MucGF0aC5leGlzdHMoaWR4KToKICAgICAgICBvcy5yZW1vdmUoaWR4KQog
ICAgZW52ID0geyJHSVRfSU5ERVhfRklMRSI6IGlkeH0KICAgIHIgPSBnaXQoInJlYWQtdHJlZSIs
IGhlYWQsIGVudl9leHRyYT1lbnYpCiAgICBpZiByLnJldHVybmNvZGU6CiAgICAgICAgcmFpc2Ug
UnVudGltZUVycm9yKGYicmVhZC10cmVlIEhFQUQ6IHtyLnN0ZGVyci5zdHJpcCgpWzoyMDBdfSIp
CgogICAgIyBNb2RlcyBleGlzdGFudHMgZGVzIGZpY2hpZXJzIHN1aXZpcyAocG91ciBuZSBwYXMg
cGVyZHJlIHVuIDEwMDc1NSkuCiAgICBleGlzdGluZ19tb2RlID0ge30KICAgIGZvciBsaW5lIGlu
IGdpdF9vaygibHMtZmlsZXMiLCAiLXMiLCAiLXoiKS5zcGxpdCgiXDAiKToKICAgICAgICBpZiBu
b3QgbGluZToKICAgICAgICAgICAgY29udGludWUKICAgICAgICBtZXRhLCBfLCBwYXRoID0gbGlu
ZS5wYXJ0aXRpb24oIlx0IikKICAgICAgICBwYXJ0cyA9IG1ldGEuc3BsaXQoKQogICAgICAgIGlm
IGxlbihwYXJ0cykgPj0gMToKICAgICAgICAgICAgZXhpc3RpbmdfbW9kZVtwYXRoXSA9IHBhcnRz
WzBdCgogICAgbGluZXMgPSBbXQogICAgZm9yIHAgaW4gYWRkOgogICAgICAgIGFwID0gb3MucGF0
aC5qb2luKFJPT1QsIHApCiAgICAgICAgc2hhID0gZ2l0X29rKCJoYXNoLW9iamVjdCIsICItdyIs
ICItLSIsIGFwKS5zdHJpcCgpCiAgICAgICAgbW9kZSA9IGV4aXN0aW5nX21vZGUuZ2V0KHAsICIx
MDA2NDQiKQogICAgICAgIGlmIG1vZGUgbm90IGluICgiMTAwNjQ0IiwgIjEwMDc1NSIsICIxMjAw
MDAiKToKICAgICAgICAgICAgbW9kZSA9ICIxMDA2NDQiCiAgICAgICAgbGluZXMuYXBwZW5kKGYi
e21vZGV9IHtzaGF9XHR7cH0iKQogICAgZm9yIHAgaW4gcm06CiAgICAgICAgbGluZXMuYXBwZW5k
KGYiMCAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwXHR7cH0iKQoKICAg
IHIgPSBnaXQoInVwZGF0ZS1pbmRleCIsICItLWluZGV4LWluZm8iLCBlbnZfZXh0cmE9ZW52LAog
ICAgICAgICAgICBpbnA9IlxuIi5qb2luKGxpbmVzKSArICJcbiIpCiAgICBpZiByLnJldHVybmNv
ZGU6CiAgICAgICAgcmFpc2UgUnVudGltZUVycm9yKGYidXBkYXRlLWluZGV4IFdJUDoge3Iuc3Rk
ZXJyLnN0cmlwKClbOjMwMF19IikKICAgIHIgPSBnaXQoIndyaXRlLXRyZWUiLCBlbnZfZXh0cmE9
ZW52KQogICAgaWYgci5yZXR1cm5jb2RlOgogICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihmIndy
aXRlLXRyZWUgV0lQOiB7ci5zdGRlcnIuc3RyaXAoKVs6MzAwXX0iKQogICAgdHJlZSA9IHIuc3Rk
b3V0LnN0cmlwKCkKCiAgICBoZWFkX3RyZWUgPSBnaXRfb2soInJldi1wYXJzZSIsIGYie2hlYWR9
Xnt7dHJlZX19Iikuc3RyaXAoKQogICAgaWYgdHJlZSA9PSBoZWFkX3RyZWU6CiAgICAgICAgcHJp
bnQoIltXSVBdIGFyYnJlIGlkZW50aXF1ZSBhIEhFQUQsIHJpZW4gYSBjb21taXR0ZXIuIiwgZmx1
c2g9VHJ1ZSkKICAgICAgICByZXR1cm4gaGVhZCwgMAoKICAgIGlmIGRyeToKICAgICAgICBwcmlu
dChmIltXSVBdIERSWS1SVU4gOiBhcmJyZSBXSVA9e3RyZWVbOjEyXX0gKGNvbW1pdCBub24gZWNy
aXQpLiIsCiAgICAgICAgICAgICAgZmx1c2g9VHJ1ZSkKICAgICAgICByZXR1cm4gaGVhZCwgbGVu
KGFkZCkgKyBsZW4ocm0pCgogICAgbXNnID0gKCJjaG9yZShzeW5jKTogc25hcHNob3QgbG9jYWwg
Y29kZSBXSVBcblxuIgogICAgICAgICAgICJDb2RlIGxvY2FsIG5vbiBjb21taXR0ZSBmaWdlIGF2
YW50IHJlY29uY2lsaWF0aW9uIChjYXRhbG9nLyBldCAiCiAgICAgICAgICAgImRhdGEgZXhjbHVz
KS5cblxuIgogICAgICAgICAgICJDby1BdXRob3JlZC1CeTogQ2xhdWRlIE9wdXMgNC44IDxub3Jl
cGx5QGFudGhyb3BpYy5jb20+IikKICAgIGNvbW1pdCA9IGdpdF9vaygiY29tbWl0LXRyZWUiLCB0
cmVlLCAiLXAiLCBoZWFkLCAiLW0iLCBtc2cpLnN0cmlwKCkKICAgIGdpdF9vaygidXBkYXRlLXJl
ZiIsIGYicmVmcy9oZWFkcy97YnJhbmNofSIsIGNvbW1pdCkKICAgIHByaW50KGYiW1dJUF0gY29t
bWl0IGxvY2FsIHtjb21taXRbOjEyXX0gKHtsZW4oYWRkKStsZW4ocm0pfSBjaGVtaW5zKS4iLAog
ICAgICAgICAgZmx1c2g9VHJ1ZSkKICAgIHJldHVybiBjb21taXQsIGxlbihhZGQpICsgbGVuKHJt
KQoKCiMgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t
LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0KIyBQSEFTRSAyIDogcHVzaCBmYXN0LWZvcndhcmQgcGFy
IHBsb21iZXJpZQojIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t
LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCmRlZiBidWlsZF9pbmRleF9saW5lcyhiYXNl
LCB3b3JrKToKICAgIGRpZmYgPSBnaXRfb2soIi1jIiwgImNvcmUucXVvdGVwYXRoPWZhbHNlIiwg
ImRpZmYtdHJlZSIsICItciIsCiAgICAgICAgICAgICAgICAgICItLW5vLXJlbmFtZXMiLCAiLS1u
by1jb21taXQtaWQiLCBiYXNlLCB3b3JrKQogICAgbGluZXMsIGRlbGV0aW9ucywgY2hhbmdlcyA9
IFtdLCAwLCAwCiAgICBmb3IgcmF3IGluIGRpZmYuc3BsaXRsaW5lcygpOgogICAgICAgIGlmIG5v
dCByYXcuc3RhcnRzd2l0aCgiOiIpOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIG1ldGEs
IHRhYiwgcGF0aCA9IHJhdy5wYXJ0aXRpb24oIlx0IikKICAgICAgICBpZiBub3QgdGFiOgogICAg
ICAgICAgICBjb250aW51ZQogICAgICAgIHBhcnRzID0gbWV0YVsxOl0uc3BsaXQoKQogICAgICAg
IGlmIGxlbihwYXJ0cykgPCA1OgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGRzdG1vZGUs
IGRzdHNoYSwgc3RhdHVzID0gcGFydHNbMV0sIHBhcnRzWzNdLCBwYXJ0c1s0XVswXQogICAgICAg
IGlmIHN0YXR1cyA9PSAiRCI6CiAgICAgICAgICAgIGxpbmVzLmFwcGVuZChmIjAgMDAwMDAwMDAw
MDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMFx0e3BhdGh9IikKICAgICAgICAgICAgZGVs
ZXRpb25zICs9IDEKICAgICAgICBlbHNlOgogICAgICAgICAgICBsaW5lcy5hcHBlbmQoZiJ7ZHN0
bW9kZX0ge2RzdHNoYX1cdHtwYXRofSIpCiAgICAgICAgICAgIGNoYW5nZXMgKz0gMQogICAgcmV0
dXJuIGxpbmVzLCBjaGFuZ2VzLCBkZWxldGlvbnMKCgpkZWYgZmFzdF9mb3J3YXJkX3B1c2goYnJh
bmNoLCByZW1vdGUsIGJhc2VfcmVmLCBkcnksIG5vX2ZldGNoKToKICAgIGhlYWQgPSBnaXRfb2so
InJldi1wYXJzZSIsICJIRUFEIikuc3RyaXAoKQogICAgZ2l0X29rKCJ1cGRhdGUtcmVmIiwgInJl
ZnMvYWxpbmEvbG9jYWwtd29yayIsIGhlYWQpCiAgICBwcmludChmIltGRl0gSEVBRCBsb2NhbCBz
YXV2ZWdhcmRlIDoge2hlYWRbOjEyXX0gIgogICAgICAgICAgZiIocmVmIHJlZnMvYWxpbmEvbG9j
YWwtd29yaykiLCBmbHVzaD1UcnVlKQoKICAgIGFic190bXAgPSBvcy5wYXRoLmpvaW4oX2luZGV4
X2RpcigpLCAiYWxpbmEtZmYtaW5kZXgiKQogICAgcmVtb3RlX3JlZiA9IGJhc2VfcmVmIG9yIGYi
e3JlbW90ZX0ve2JyYW5jaH0iCgogICAgZm9yIGF0dGVtcHQgaW4gcmFuZ2UoMSwgNik6CiAgICAg
ICAgcHJpbnQoZiJbRkZdIC0tLSB0ZW50YXRpdmUge2F0dGVtcHR9LzUgLS0tIiwgZmx1c2g9VHJ1
ZSkKICAgICAgICBpZiBub3Qgbm9fZmV0Y2ggYW5kIGJhc2VfcmVmIGlzIE5vbmU6CiAgICAgICAg
ICAgIHByaW50KGYiW0ZGXSBmZXRjaCB7cmVtb3RlfSB7YnJhbmNofSAtLW5vLWZpbHRlciAuLi4i
LCBmbHVzaD1UcnVlKQogICAgICAgICAgICBmID0gZ2l0KCJmZXRjaCIsIHJlbW90ZSwgYnJhbmNo
LCAiLS1uby1maWx0ZXIiLCAiLS1xdWlldCIpCiAgICAgICAgICAgIGlmIGYucmV0dXJuY29kZSAh
PSAwOgogICAgICAgICAgICAgICAgcHJpbnQoZiJbRkZdIFdBUk4gZmV0Y2g6IHtmLnN0ZGVyci5z
dHJpcCgpWzoyMDBdfSIsIGZsdXNoPVRydWUpCgogICAgICAgIHRyeToKICAgICAgICAgICAgYmFz
ZV9zaGEgPSBnaXRfb2soInJldi1wYXJzZSIsIHJlbW90ZV9yZWYpLnN0cmlwKCkKICAgICAgICBl
eGNlcHQgUnVudGltZUVycm9yIGFzIGU6CiAgICAgICAgICAgIHByaW50KGYiW0ZGXSBOT19HTzog
e3JlbW90ZV9yZWZ9IGludHJvdXZhYmxlICh7ZX0pIiwgZmx1c2g9VHJ1ZSkKICAgICAgICAgICAg
cmV0dXJuIDIKICAgICAgICBtYiA9IGdpdF9vaygibWVyZ2UtYmFzZSIsICJyZWZzL2FsaW5hL2xv
Y2FsLXdvcmsiLCBiYXNlX3NoYSkuc3RyaXAoKQogICAgICAgIGxpbmVzLCBjaGFuZ2VzLCBkZWxz
ID0gYnVpbGRfaW5kZXhfbGluZXMobWIsICJyZWZzL2FsaW5hL2xvY2FsLXdvcmsiKQogICAgICAg
IHByaW50KGYiW0ZGXSBiYXNlPXtiYXNlX3NoYVs6MTJdfSBtZXJnZS1iYXNlPXttYls6MTJdfSAi
CiAgICAgICAgICAgICAgZiJ8IHtjaGFuZ2VzfSBtb2RpZi9ham91dCwge2RlbHN9IHN1cHByZXNz
aW9uKHMpIiwgZmx1c2g9VHJ1ZSkKICAgICAgICBpZiBub3QgbGluZXM6CiAgICAgICAgICAgIHBy
aW50KCJbRkZdIGF1Y3VuIGNoYW5nZW1lbnQgbG9jYWwgYSBwb3Vzc2VyIDsgcmllbiBhIGZhaXJl
LiIsCiAgICAgICAgICAgICAgICAgIGZsdXNoPVRydWUpCiAgICAgICAgICAgIHJldHVybiAwCgog
ICAgICAgIGlmIG9zLnBhdGguZXhpc3RzKGFic190bXApOgogICAgICAgICAgICBvcy5yZW1vdmUo
YWJzX3RtcCkKICAgICAgICBlbnYgPSB7IkdJVF9JTkRFWF9GSUxFIjogYWJzX3RtcH0KICAgICAg
ICBwcmludChmIltGRl0gcmVhZC10cmVlIHtiYXNlX3NoYVs6MTJdfSAoaW5kZXggdGVtcG9yYWly
ZSkgLi4uIiwKICAgICAgICAgICAgICBmbHVzaD1UcnVlKQogICAgICAgIHIgPSBnaXQoInJlYWQt
dHJlZSIsIGJhc2Vfc2hhLCBlbnZfZXh0cmE9ZW52KQogICAgICAgIGlmIHIucmV0dXJuY29kZToK
ICAgICAgICAgICAgcHJpbnQoZiJbRkZdIE5PX0dPIHJlYWQtdHJlZToge3Iuc3RkZXJyLnN0cmlw
KClbOjMwMF19IiwgZmx1c2g9VHJ1ZSkKICAgICAgICAgICAgcmV0dXJuIDIKICAgICAgICBwcmlu
dChmIltGRl0gdXBkYXRlLWluZGV4IDoge2xlbihsaW5lcyl9IGVudHJlZShzKSBlbiBsb3QgLi4u
IiwKICAgICAgICAgICAgICBmbHVzaD1UcnVlKQogICAgICAgIHIgPSBnaXQoInVwZGF0ZS1pbmRl
eCIsICItLWluZGV4LWluZm8iLCBlbnZfZXh0cmE9ZW52LAogICAgICAgICAgICAgICAgaW5wPSJc
biIuam9pbihsaW5lcykgKyAiXG4iKQogICAgICAgIGlmIHIucmV0dXJuY29kZToKICAgICAgICAg
ICAgcHJpbnQoZiJbRkZdIE5PX0dPIHVwZGF0ZS1pbmRleDoge3Iuc3RkZXJyLnN0cmlwKClbOjMw
MF19IiwKICAgICAgICAgICAgICAgICAgZmx1c2g9VHJ1ZSkKICAgICAgICAgICAgcmV0dXJuIDIK
ICAgICAgICBwcmludCgiW0ZGXSB3cml0ZS10cmVlIC4uLiIsIGZsdXNoPVRydWUpCiAgICAgICAg
ciA9IGdpdCgid3JpdGUtdHJlZSIsIGVudl9leHRyYT1lbnYpCiAgICAgICAgaWYgci5yZXR1cm5j
b2RlOgogICAgICAgICAgICBwcmludChmIltGRl0gTk9fR08gd3JpdGUtdHJlZToge3Iuc3RkZXJy
LnN0cmlwKClbOjMwMF19IiwKICAgICAgICAgICAgICAgICAgZmx1c2g9VHJ1ZSkKICAgICAgICAg
ICAgcmV0dXJuIDIKICAgICAgICB0cmVlID0gci5zdGRvdXQuc3RyaXAoKQogICAgICAgIHByaW50
KGYiW0ZGXSB0cmVlPXt0cmVlWzoxMl19IiwgZmx1c2g9VHJ1ZSkKICAgICAgICBtc2cgPSAoImNo
b3JlKHN5bmMpOiByZWNvbmNpbGUgbG9jYWwgd29yayBvbnRvIG9yaWdpbi9tYWluXG5cbiIKICAg
ICAgICAgICAgICAgIkZhc3QtZm9yd2FyZCBwbHVtYmluZyAocmViYXNlIGltcG9zc2libGUgb24g
c2hhbGxvdytwYXJ0aWFsICIKICAgICAgICAgICAgICAgImNsb25lKS4gQ29kZSBmaWxlcyBmcm9t
IGxvY2FsIGNvbW1pdHMgb25seTsgY2F0YWxvZy8ga2VwdCBhdCAiCiAgICAgICAgICAgICAgICJv
cmlnaW4vbWFpbi5cblxuIgogICAgICAgICAgICAgICAiQ28tQXV0aG9yZWQtQnk6IENsYXVkZSBP
cHVzIDQuOCA8bm9yZXBseUBhbnRocm9waWMuY29tPiIpCiAgICAgICAgciA9IGdpdCgiY29tbWl0
LXRyZWUiLCB0cmVlLCAiLXAiLCBiYXNlX3NoYSwgIi1tIiwgbXNnKQogICAgICAgIGlmIHIucmV0
dXJuY29kZToKICAgICAgICAgICAgcHJpbnQoZiJbRkZdIE5PX0dPIGNvbW1pdC10cmVlOiB7ci5z
dGRlcnIuc3RyaXAoKVs6MzAwXX0iLAogICAgICAgICAgICAgICAgICBmbHVzaD1UcnVlKQogICAg
ICAgICAgICByZXR1cm4gMgogICAgICAgIGNvbW1pdCA9IHIuc3Rkb3V0LnN0cmlwKCkKICAgICAg
ICBwcmludChmIltGRl0gY29tbWl0PXtjb21taXRbOjEyXX0iLCBmbHVzaD1UcnVlKQoKICAgICAg
ICBpZiBkcnk6CiAgICAgICAgICAgIGQgPSBnaXRfb2soImRpZmYiLCAiLS1uYW1lLW9ubHkiLCBj
b21taXQsICJyZWZzL2FsaW5hL2xvY2FsLXdvcmsiKQogICAgICAgICAgICBub25jYXQgPSBbcCBm
b3IgcCBpbiBkLnNwbGl0bGluZXMoKQogICAgICAgICAgICAgICAgICAgICAgaWYgcCBhbmQgbm90
IHAuc3RhcnRzd2l0aCgiY2F0YWxvZy8iKV0KICAgICAgICAgICAgcHJpbnQoZiJbRkZdIERSWS1S
VU4gOiBjb21taXQgY29uc3RydWl0IDsgZGlmZiBjb2RlIHZzIGxvY2FsID0gIgogICAgICAgICAg
ICAgICAgICBmIntsZW4obm9uY2F0KX0gKDAgPSBjb250ZW51IGlkZW50aXF1ZSkuICIKICAgICAg
ICAgICAgICAgICAgIm1haW4gaW5jaGFuZ2UsIGF1Y3VuIHB1c2guIiwgZmx1c2g9VHJ1ZSkKICAg
ICAgICAgICAgaWYgbm9uY2F0Wzo1XToKICAgICAgICAgICAgICAgIHByaW50KGYiICAgICBkaXZl
cmdlbmNlczoge25vbmNhdFs6NV19IiwgZmx1c2g9VHJ1ZSkKICAgICAgICAgICAgcmV0dXJuIDAK
CiAgICAgICAgZ2l0X29rKCJ1cGRhdGUtcmVmIiwgZiJyZWZzL2hlYWRzL3ticmFuY2h9IiwgY29t
bWl0KQogICAgICAgIHByaW50KGYiW0ZGXSBwdXNoIHtyZW1vdGV9IHticmFuY2h9IC4uLiIsIGZs
dXNoPVRydWUpCiAgICAgICAgcCA9IGdpdCgicHVzaCIsIHJlbW90ZSwgYnJhbmNoKQogICAgICAg
IG91dCA9IChwLnN0ZG91dCBvciAiIikgKyAocC5zdGRlcnIgb3IgIiIpCiAgICAgICAgaWYgcC5y
ZXR1cm5jb2RlID09IDA6CiAgICAgICAgICAgIHByaW50KCJbRkZdID09PT4gUFVTSCBPSyA8PT09
IiwgZmx1c2g9VHJ1ZSkKICAgICAgICAgICAgcHJpbnQoZiJbRkZdIEhFQUQgcG91c3NlIDoge2Nv
bW1pdFs6MTJdfSIsIGZsdXNoPVRydWUpCiAgICAgICAgICAgIHJldHVybiAwCiAgICAgICAgaWYg
YW55KHMgaW4gb3V0IGZvciBzIGluICgibm9uLWZhc3QtZm9yd2FyZCIsICJmZXRjaCBmaXJzdCIs
CiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAicmVqZWN0ZWQiLCAic3RhbGUgaW5m
byIpKToKICAgICAgICAgICAgcHJpbnQoIltGRl0gb3JpZ2luIGEgYXZhbmNlIHBlbmRhbnQgbCdv
cGVyYXRpb24gOyBub3V2ZWxsZSAiCiAgICAgICAgICAgICAgICAgICJ0ZW50YXRpdmUuLi4iLCBm
bHVzaD1UcnVlKQogICAgICAgICAgICBjb250aW51ZQogICAgICAgIHByaW50KGYiW0ZGXSBOT19H
TyBwdXNoOiB7b3V0LnN0cmlwKClbOjQwMF19IiwgZmx1c2g9VHJ1ZSkKICAgICAgICByZXR1cm4g
MQoKICAgIHByaW50KCJbRkZdIE5PX0dPOiB0cm9wIGRlIHRlbnRhdGl2ZXMgKG9yaWdpbiBhdmFu
Y2UgdHJvcCB2aXRlKS4iLAogICAgICAgICAgZmx1c2g9VHJ1ZSkKICAgIHJldHVybiAxCgoKZGVm
IG1haW4oKToKICAgIGdsb2JhbCBHSVQsIFJPT1QKICAgIGFwID0gYXJncGFyc2UuQXJndW1lbnRQ
YXJzZXIoKQogICAgYXAuYWRkX2FyZ3VtZW50KCItLWdpdCIsIGRlZmF1bHQ9ImdpdCIpCiAgICBh
cC5hZGRfYXJndW1lbnQoIi0tcm9vdCIsIGRlZmF1bHQ9Tm9uZSwKICAgICAgICAgICAgICAgICAg
ICBoZWxwPSJyYWNpbmUgZHUgZGVwb3QgKHNpbm9uIEFMSU5BX1JPT1Qgb3UgZGV1eCBuaXZlYXV4
IGF1LWRlc3N1cykiKQogICAgYXAuYWRkX2FyZ3VtZW50KCItLXJlbW90ZSIsIGRlZmF1bHQ9Im9y
aWdpbiIpCiAgICBhcC5hZGRfYXJndW1lbnQoIi0tYnJhbmNoIiwgZGVmYXVsdD1Ob25lKQogICAg
YXAuYWRkX2FyZ3VtZW50KCItLWRyeS1ydW4iLCBhY3Rpb249InN0b3JlX3RydWUiKQogICAgYXAu
YWRkX2FyZ3VtZW50KCItLW5vLWZldGNoIiwgYWN0aW9uPSJzdG9yZV90cnVlIikKICAgIGFwLmFk
ZF9hcmd1bWVudCgiLS1uby1jb21taXQiLCBhY3Rpb249InN0b3JlX3RydWUiLAogICAgICAgICAg
ICAgICAgICAgIGhlbHA9Im5lIGZpZ2UgcGFzIGxlIFdJUCwgcG91c3NlIHNldWxlbWVudCBjZSBx
dWkgZXN0IGNvbW1pdGUiKQogICAgYXAuYWRkX2FyZ3VtZW50KCItLWJhc2UiLCBkZWZhdWx0PU5v
bmUsIGhlbHA9ImRlYnVnOiBidWlsZCBvbiB0aGlzIHJlZiIpCiAgICBhcmdzID0gYXAucGFyc2Vf
YXJncygpCiAgICBHSVQgPSBhcmdzLmdpdAogICAgaWYgYXJncy5yb290OgogICAgICAgIFJPT1Qg
PSBvcy5wYXRoLmFic3BhdGgoYXJncy5yb290KQogICAgYnJhbmNoID0gYXJncy5icmFuY2ggb3Ig
Y3VycmVudF9icmFuY2goIm1haW4iKQoKICAgIHRyeToKICAgICAgICBpZiBub3QgYXJncy5ub19j
b21taXQ6CiAgICAgICAgICAgIHNuYXBzaG90X3dpcChicmFuY2gsIGFyZ3MuZHJ5X3J1bikKICAg
IGV4Y2VwdCBFeGNlcHRpb24gYXMgZTogICMgbm9xYTogQkxFMDAxCiAgICAgICAgcHJpbnQoZiJb
V0lQXSBOT19HTyBzbmFwc2hvdCAoe2V9KSA7IG9uIHBvdXNzZSBjZSBxdWkgZXN0IGRlamEgIgog
ICAgICAgICAgICAgICJjb21taXRlLiIsIGZsdXNoPVRydWUpCgogICAgcmV0dXJuIGZhc3RfZm9y
d2FyZF9wdXNoKGJyYW5jaCwgYXJncy5yZW1vdGUsIGFyZ3MuYmFzZSwKICAgICAgICAgICAgICAg
ICAgICAgICAgICAgICBhcmdzLmRyeV9ydW4sIGFyZ3Mubm9fZmV0Y2gpCgoKaWYgX19uYW1lX18g
PT0gIl9fbWFpbl9fIjoKICAgIHN5cy5leGl0KG1haW4oKSkK
#ALINA_B64_END

