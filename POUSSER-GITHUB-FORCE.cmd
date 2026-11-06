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
ICogMTAyNCAgIyAyIE1pQgoKCmRlZiBnaXQoKmEsIGVudl9leHRyYT1Ob25lLCBpbnA9Tm9uZSk6
CiAgICBlbnYgPSBkaWN0KG9zLmVudmlyb24sIEdJVF9MRlNfU0tJUF9TTVVER0U9IjEiKQogICAg
aWYgZW52X2V4dHJhOgogICAgICAgIGVudi51cGRhdGUoZW52X2V4dHJhKQogICAgcmV0dXJuIHN1
YnByb2Nlc3MucnVuKFtHSVQsICphXSwgY3dkPVJPT1QsIGNhcHR1cmVfb3V0cHV0PVRydWUsCiAg
ICAgICAgICAgICAgICAgICAgICAgICAgdGV4dD1UcnVlLCBlbnY9ZW52LCBpbnB1dD1pbnApCgoK
ZGVmIGdpdF9vaygqYSwgKiprKToKICAgIHIgPSBnaXQoKmEsICoqaykKICAgIGlmIHIucmV0dXJu
Y29kZSAhPSAwOgogICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihmImdpdCB7JyAnLmpvaW4oYSl9
OiB7ci5zdGRlcnIuc3RyaXAoKVs6MzAwXX0iKQogICAgcmV0dXJuIHIuc3Rkb3V0CgoKZGVmIGlz
X2NvZGVfcGF0aChwOiBzdHIpIC0+IGJvb2w6CiAgICBxID0gcC5yZXBsYWNlKCJcXCIsICIvIikK
ICAgIGxvdyA9IHEubG93ZXIoKQogICAgaWYgYW55KGxvdy5zdGFydHN3aXRoKHgpIGZvciB4IGlu
IEVYQ0xVREVfUFJFRklYRVMpOgogICAgICAgIHJldHVybiBGYWxzZQogICAgaWYgYW55KGxvdy5l
bmRzd2l0aCh4KSBmb3IgeCBpbiBFWENMVURFX1NVRkZJWEVTKToKICAgICAgICByZXR1cm4gRmFs
c2UKICAgIHJldHVybiBUcnVlCgoKZGVmIGN1cnJlbnRfYnJhbmNoKGRlZmF1bHQ9Im1haW4iKSAt
PiBzdHI6CiAgICByID0gZ2l0KCJzeW1ib2xpYy1yZWYiLCAiLS1zaG9ydCIsICItcSIsICJIRUFE
IikKICAgIGIgPSByLnN0ZG91dC5zdHJpcCgpCiAgICByZXR1cm4gYiBvciBkZWZhdWx0CgoKZGVm
IGV4Y2x1ZGVfcGF0aHNwZWNzKCk6CiAgICAjIFBhdGhzcGVjIHBvc2l0aWYgIi4iICsgZXhjbHVz
aW9ucyBkZXMgZG9zc2llcnMgZGF0YS9ydW50aW1lLCBwb3VyIG5lCiAgICAjIEpBTUFJUyBwYXJj
b3VyaXIgY2F0YWxvZy8gKGRlcyBtaWxsaWVycyBkZSBmaWNoaWVycykgOiByYXBpZGUgZXQgc3Vy
LgogICAgc3BlY3MgPSBbIi4iXQogICAgZm9yIHBmeCBpbiBFWENMVURFX1BSRUZJWEVTOgogICAg
ICAgIGQgPSBwZngucnN0cmlwKCIvIikKICAgICAgICBpZiBkIGFuZCBkICE9ICIuZ2l0IjoKICAg
ICAgICAgICAgc3BlY3MuYXBwZW5kKGYiOihleGNsdWRlKXtkfSIpCiAgICByZXR1cm4gc3BlY3MK
CgojIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t
LS0tLS0tLS0tLS0tLS0tLS0tLS0tCiMgUEhBU0UgMSA6IHNuYXBzaG90IGR1IGNvZGUgbG9jYWwg
bm9uIGNvbW1pdHRlIC0+IGNvbW1pdCBsb2NhbAojIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t
LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCmRlZiBzbmFw
c2hvdF93aXAoYnJhbmNoOiBzdHIsIGRyeTogYm9vbCk6CiAgICBoZWFkID0gZ2l0X29rKCJyZXYt
cGFyc2UiLCAiSEVBRCIpLnN0cmlwKCkKCiAgICAjIEZpY2hpZXJzIHN1aXZpcyBtb2RpZmllcy9z
dXBwcmltZXMgKHZzIHdvcmtpbmcgdHJlZSkuIE9uIGV4Y2x1dCBsZXMKICAgICMgZG9zc2llcnMg
ZGF0YS9ydW50aW1lIGF1IG5pdmVhdSBwYXRoc3BlYyA6IGNhdGFsb2cvIG4nZXN0IGphbWFpcyBw
YXJjb3VydS4KICAgIHhwID0gZXhjbHVkZV9wYXRoc3BlY3MoKQogICAgbW9kaWZpZWQsIGRlbGV0
ZWQgPSBbXSwgW10KICAgIG91dCA9IGdpdCgiZGlmZiIsICItLW5hbWUtc3RhdHVzIiwgIi16Iiwg
IkhFQUQiLCAiLS0iLCAqeHApCiAgICBpZiBvdXQucmV0dXJuY29kZSA9PSAwIGFuZCBvdXQuc3Rk
b3V0OgogICAgICAgIHRva3MgPSBvdXQuc3Rkb3V0LnNwbGl0KCJcMCIpCiAgICAgICAgaSA9IDAK
ICAgICAgICB3aGlsZSBpIDwgbGVuKHRva3MpOgogICAgICAgICAgICBzdCA9IHRva3NbaV0KICAg
ICAgICAgICAgaWYgbm90IHN0OgogICAgICAgICAgICAgICAgaSArPSAxCiAgICAgICAgICAgICAg
ICBjb250aW51ZQogICAgICAgICAgICBjb2RlID0gc3RbMF0KICAgICAgICAgICAgaWYgY29kZSBp
biAoIlIiLCAiQyIpIGFuZCBpICsgMiA8IGxlbih0b2tzKToKICAgICAgICAgICAgICAgICMgcmVu
YW1lL2NvcHkgOiBvbGQsIG5ldwogICAgICAgICAgICAgICAgbmV3cCA9IHRva3NbaSArIDJdCiAg
ICAgICAgICAgICAgICBtb2RpZmllZC5hcHBlbmQobmV3cCkKICAgICAgICAgICAgICAgIGRlbGV0
ZWQuYXBwZW5kKHRva3NbaSArIDFdKQogICAgICAgICAgICAgICAgaSArPSAzCiAgICAgICAgICAg
IGVsaWYgaSArIDEgPCBsZW4odG9rcyk6CiAgICAgICAgICAgICAgICBwYXRoID0gdG9rc1tpICsg
MV0KICAgICAgICAgICAgICAgIGlmIGNvZGUgPT0gIkQiOgogICAgICAgICAgICAgICAgICAgIGRl
bGV0ZWQuYXBwZW5kKHBhdGgpCiAgICAgICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAg
ICAgIG1vZGlmaWVkLmFwcGVuZChwYXRoKQogICAgICAgICAgICAgICAgaSArPSAyCiAgICAgICAg
ICAgIGVsc2U6CiAgICAgICAgICAgICAgICBpICs9IDEKCiAgICAjIEZpY2hpZXJzIG5vbiBzdWl2
aXMgKGhvcnMgLmdpdGlnbm9yZSksIG1lbWVzIGV4Y2x1c2lvbnMuCiAgICB1bnRyYWNrZWQgPSBb
cCBmb3IgcCBpbiBnaXRfb2soCiAgICAgICAgImxzLWZpbGVzIiwgIi0tb3RoZXJzIiwgIi0tZXhj
bHVkZS1zdGFuZGFyZCIsICIteiIsICItLSIsICp4cAogICAgKS5zcGxpdCgiXDAiKSBpZiBwXQoK
ICAgICMgR2FyZGUgdW5pcXVlbWVudCBsZSBjb2RlLCBkZSB0YWlsbGUgcmFpc29ubmFibGUsIHBy
ZXNlbnQgc3VyIGRpc3F1ZS4KICAgIGFkZCA9IFtdCiAgICBmb3IgcCBpbiBzb3J0ZWQoc2V0KG1v
ZGlmaWVkKSB8IHNldCh1bnRyYWNrZWQpKToKICAgICAgICBpZiBub3QgaXNfY29kZV9wYXRoKHAp
OgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGFwID0gb3MucGF0aC5qb2luKFJPT1QsIHAp
CiAgICAgICAgaWYgbm90IG9zLnBhdGguaXNmaWxlKGFwKToKICAgICAgICAgICAgY29udGludWUK
ICAgICAgICB0cnk6CiAgICAgICAgICAgIGlmIG9zLnBhdGguZ2V0c2l6ZShhcCkgPiBNQVhfV0lQ
X0ZJTEVfQllURVM6CiAgICAgICAgICAgICAgICBjb250aW51ZQogICAgICAgIGV4Y2VwdCBPU0Vy
cm9yOgogICAgICAgICAgICBjb250aW51ZQogICAgICAgIGFkZC5hcHBlbmQocCkKICAgIHJtID0g
W3AgZm9yIHAgaW4gc29ydGVkKHNldChkZWxldGVkKSkgaWYgaXNfY29kZV9wYXRoKHApXQoKICAg
IGlmIG5vdCBhZGQgYW5kIG5vdCBybToKICAgICAgICBwcmludCgiW1dJUF0gYXVjdW4gY2hhbmdl
bWVudCBkZSBjb2RlIGxvY2FsIGEgZmlnZXIuIiwgZmx1c2g9VHJ1ZSkKICAgICAgICByZXR1cm4g
aGVhZCwgMAoKICAgIHByaW50KGYiW1dJUF0ge2xlbihhZGQpfSBmaWNoaWVyKHMpIGNvZGUgbW9k
aWZpZShzKS9ub3V2ZWF1KHgpLCAiCiAgICAgICAgICBmIntsZW4ocm0pfSBzdXBwcmVzc2lvbihz
KS4iLCBmbHVzaD1UcnVlKQogICAgaWYgZHJ5OgogICAgICAgIGZvciBwIGluIGFkZFs6MjBdOgog
ICAgICAgICAgICBwcmludChmIiAgICAgICArIHtwfSIsIGZsdXNoPVRydWUpCiAgICAgICAgZm9y
IHAgaW4gcm1bOjIwXToKICAgICAgICAgICAgcHJpbnQoZiIgICAgICAgLSB7cH0iLCBmbHVzaD1U
cnVlKQoKICAgICMgSW5kZXggdGVtcG9yYWlyZSBzZWVkZSBwYXIgbCdhcmJyZSBkZSBIRUFEIChu
ZSB0b3VjaGUgcGFzIGwnaW5kZXggcmVlbCkuCiAgICBpZHggPSBvcy5wYXRoLmpvaW4oUk9PVCwg
Ii5naXQiLCAiYWxpbmEtd2lwLWluZGV4IikKICAgIGlmIG9zLnBhdGguZXhpc3RzKGlkeCk6CiAg
ICAgICAgb3MucmVtb3ZlKGlkeCkKICAgIGVudiA9IHsiR0lUX0lOREVYX0ZJTEUiOiBpZHh9CiAg
ICByID0gZ2l0KCJyZWFkLXRyZWUiLCBoZWFkLCBlbnZfZXh0cmE9ZW52KQogICAgaWYgci5yZXR1
cm5jb2RlOgogICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihmInJlYWQtdHJlZSBIRUFEOiB7ci5z
dGRlcnIuc3RyaXAoKVs6MjAwXX0iKQoKICAgICMgTW9kZXMgZXhpc3RhbnRzIGRlcyBmaWNoaWVy
cyBzdWl2aXMgKHBvdXIgbmUgcGFzIHBlcmRyZSB1biAxMDA3NTUpLgogICAgZXhpc3RpbmdfbW9k
ZSA9IHt9CiAgICBmb3IgbGluZSBpbiBnaXRfb2soImxzLWZpbGVzIiwgIi1zIiwgIi16Iikuc3Bs
aXQoIlwwIik6CiAgICAgICAgaWYgbm90IGxpbmU6CiAgICAgICAgICAgIGNvbnRpbnVlCiAgICAg
ICAgbWV0YSwgXywgcGF0aCA9IGxpbmUucGFydGl0aW9uKCJcdCIpCiAgICAgICAgcGFydHMgPSBt
ZXRhLnNwbGl0KCkKICAgICAgICBpZiBsZW4ocGFydHMpID49IDE6CiAgICAgICAgICAgIGV4aXN0
aW5nX21vZGVbcGF0aF0gPSBwYXJ0c1swXQoKICAgIGxpbmVzID0gW10KICAgIGZvciBwIGluIGFk
ZDoKICAgICAgICBhcCA9IG9zLnBhdGguam9pbihST09ULCBwKQogICAgICAgIHNoYSA9IGdpdF9v
aygiaGFzaC1vYmplY3QiLCAiLXciLCAiLS0iLCBhcCkuc3RyaXAoKQogICAgICAgIG1vZGUgPSBl
eGlzdGluZ19tb2RlLmdldChwLCAiMTAwNjQ0IikKICAgICAgICBpZiBtb2RlIG5vdCBpbiAoIjEw
MDY0NCIsICIxMDA3NTUiLCAiMTIwMDAwIik6CiAgICAgICAgICAgIG1vZGUgPSAiMTAwNjQ0Igog
ICAgICAgIGxpbmVzLmFwcGVuZChmInttb2RlfSB7c2hhfVx0e3B9IikKICAgIGZvciBwIGluIHJt
OgogICAgICAgIGxpbmVzLmFwcGVuZChmIjAgMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAw
MDAwMDAwMDAwMFx0e3B9IikKCiAgICByID0gZ2l0KCJ1cGRhdGUtaW5kZXgiLCAiLS1pbmRleC1p
bmZvIiwgZW52X2V4dHJhPWVudiwKICAgICAgICAgICAgaW5wPSJcbiIuam9pbihsaW5lcykgKyAi
XG4iKQogICAgaWYgci5yZXR1cm5jb2RlOgogICAgICAgIHJhaXNlIFJ1bnRpbWVFcnJvcihmInVw
ZGF0ZS1pbmRleCBXSVA6IHtyLnN0ZGVyci5zdHJpcCgpWzozMDBdfSIpCiAgICByID0gZ2l0KCJ3
cml0ZS10cmVlIiwgZW52X2V4dHJhPWVudikKICAgIGlmIHIucmV0dXJuY29kZToKICAgICAgICBy
YWlzZSBSdW50aW1lRXJyb3IoZiJ3cml0ZS10cmVlIFdJUDoge3Iuc3RkZXJyLnN0cmlwKClbOjMw
MF19IikKICAgIHRyZWUgPSByLnN0ZG91dC5zdHJpcCgpCgogICAgaGVhZF90cmVlID0gZ2l0X29r
KCJyZXYtcGFyc2UiLCBmIntoZWFkfV57e3RyZWV9fSIpLnN0cmlwKCkKICAgIGlmIHRyZWUgPT0g
aGVhZF90cmVlOgogICAgICAgIHByaW50KCJbV0lQXSBhcmJyZSBpZGVudGlxdWUgYSBIRUFELCBy
aWVuIGEgY29tbWl0dGVyLiIsIGZsdXNoPVRydWUpCiAgICAgICAgcmV0dXJuIGhlYWQsIDAKCiAg
ICBpZiBkcnk6CiAgICAgICAgcHJpbnQoZiJbV0lQXSBEUlktUlVOIDogYXJicmUgV0lQPXt0cmVl
WzoxMl19IChjb21taXQgbm9uIGVjcml0KS4iLAogICAgICAgICAgICAgIGZsdXNoPVRydWUpCiAg
ICAgICAgcmV0dXJuIGhlYWQsIGxlbihhZGQpICsgbGVuKHJtKQoKICAgIG1zZyA9ICgiY2hvcmUo
c3luYyk6IHNuYXBzaG90IGxvY2FsIGNvZGUgV0lQXG5cbiIKICAgICAgICAgICAiQ29kZSBsb2Nh
bCBub24gY29tbWl0dGUgZmlnZSBhdmFudCByZWNvbmNpbGlhdGlvbiAoY2F0YWxvZy8gZXQgIgog
ICAgICAgICAgICJkYXRhIGV4Y2x1cykuXG5cbiIKICAgICAgICAgICAiQ28tQXV0aG9yZWQtQnk6
IENsYXVkZSBPcHVzIDQuOCA8bm9yZXBseUBhbnRocm9waWMuY29tPiIpCiAgICBjb21taXQgPSBn
aXRfb2soImNvbW1pdC10cmVlIiwgdHJlZSwgIi1wIiwgaGVhZCwgIi1tIiwgbXNnKS5zdHJpcCgp
CiAgICBnaXRfb2soInVwZGF0ZS1yZWYiLCBmInJlZnMvaGVhZHMve2JyYW5jaH0iLCBjb21taXQp
CiAgICBwcmludChmIltXSVBdIGNvbW1pdCBsb2NhbCB7Y29tbWl0WzoxMl19ICh7bGVuKGFkZCkr
bGVuKHJtKX0gY2hlbWlucykuIiwKICAgICAgICAgIGZsdXNoPVRydWUpCiAgICByZXR1cm4gY29t
bWl0LCBsZW4oYWRkKSArIGxlbihybSkKCgojIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t
LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCiMgUEhBU0UgMiA6
IHB1c2ggZmFzdC1mb3J3YXJkIHBhciBwbG9tYmVyaWUKIyAtLS0tLS0tLS0tLS0tLS0tLS0tLS0t
LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQpkZWYg
YnVpbGRfaW5kZXhfbGluZXMoYmFzZSwgd29yayk6CiAgICBkaWZmID0gZ2l0X29rKCItYyIsICJj
b3JlLnF1b3RlcGF0aD1mYWxzZSIsICJkaWZmLXRyZWUiLCAiLXIiLAogICAgICAgICAgICAgICAg
ICAiLS1uby1yZW5hbWVzIiwgIi0tbm8tY29tbWl0LWlkIiwgYmFzZSwgd29yaykKICAgIGxpbmVz
LCBkZWxldGlvbnMsIGNoYW5nZXMgPSBbXSwgMCwgMAogICAgZm9yIHJhdyBpbiBkaWZmLnNwbGl0
bGluZXMoKToKICAgICAgICBpZiBub3QgcmF3LnN0YXJ0c3dpdGgoIjoiKToKICAgICAgICAgICAg
Y29udGludWUKICAgICAgICBtZXRhLCB0YWIsIHBhdGggPSByYXcucGFydGl0aW9uKCJcdCIpCiAg
ICAgICAgaWYgbm90IHRhYjoKICAgICAgICAgICAgY29udGludWUKICAgICAgICBwYXJ0cyA9IG1l
dGFbMTpdLnNwbGl0KCkKICAgICAgICBpZiBsZW4ocGFydHMpIDwgNToKICAgICAgICAgICAgY29u
dGludWUKICAgICAgICBkc3Rtb2RlLCBkc3RzaGEsIHN0YXR1cyA9IHBhcnRzWzFdLCBwYXJ0c1sz
XSwgcGFydHNbNF1bMF0KICAgICAgICBpZiBzdGF0dXMgPT0gIkQiOgogICAgICAgICAgICBsaW5l
cy5hcHBlbmQoZiIwIDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDAwMDBcdHtw
YXRofSIpCiAgICAgICAgICAgIGRlbGV0aW9ucyArPSAxCiAgICAgICAgZWxzZToKICAgICAgICAg
ICAgbGluZXMuYXBwZW5kKGYie2RzdG1vZGV9IHtkc3RzaGF9XHR7cGF0aH0iKQogICAgICAgICAg
ICBjaGFuZ2VzICs9IDEKICAgIHJldHVybiBsaW5lcywgY2hhbmdlcywgZGVsZXRpb25zCgoKZGVm
IGZhc3RfZm9yd2FyZF9wdXNoKGJyYW5jaCwgcmVtb3RlLCBiYXNlX3JlZiwgZHJ5LCBub19mZXRj
aCk6CiAgICBoZWFkID0gZ2l0X29rKCJyZXYtcGFyc2UiLCAiSEVBRCIpLnN0cmlwKCkKICAgIGdp
dF9vaygidXBkYXRlLXJlZiIsICJyZWZzL2FsaW5hL2xvY2FsLXdvcmsiLCBoZWFkKQogICAgcHJp
bnQoZiJbRkZdIEhFQUQgbG9jYWwgc2F1dmVnYXJkZSA6IHtoZWFkWzoxMl19ICIKICAgICAgICAg
IGYiKHJlZiByZWZzL2FsaW5hL2xvY2FsLXdvcmspIiwgZmx1c2g9VHJ1ZSkKCiAgICBhYnNfdG1w
ID0gb3MucGF0aC5qb2luKFJPT1QsICIuZ2l0IiwgImFsaW5hLWZmLWluZGV4IikKICAgIHJlbW90
ZV9yZWYgPSBiYXNlX3JlZiBvciBmIntyZW1vdGV9L3ticmFuY2h9IgoKICAgIGZvciBhdHRlbXB0
IGluIHJhbmdlKDEsIDYpOgogICAgICAgIHByaW50KGYiW0ZGXSAtLS0gdGVudGF0aXZlIHthdHRl
bXB0fS81IC0tLSIsIGZsdXNoPVRydWUpCiAgICAgICAgaWYgbm90IG5vX2ZldGNoIGFuZCBiYXNl
X3JlZiBpcyBOb25lOgogICAgICAgICAgICBwcmludChmIltGRl0gZmV0Y2gge3JlbW90ZX0ge2Jy
YW5jaH0gLS1uby1maWx0ZXIgLi4uIiwgZmx1c2g9VHJ1ZSkKICAgICAgICAgICAgZiA9IGdpdCgi
ZmV0Y2giLCByZW1vdGUsIGJyYW5jaCwgIi0tbm8tZmlsdGVyIiwgIi0tcXVpZXQiKQogICAgICAg
ICAgICBpZiBmLnJldHVybmNvZGUgIT0gMDoKICAgICAgICAgICAgICAgIHByaW50KGYiW0ZGXSBX
QVJOIGZldGNoOiB7Zi5zdGRlcnIuc3RyaXAoKVs6MjAwXX0iLCBmbHVzaD1UcnVlKQoKICAgICAg
ICB0cnk6CiAgICAgICAgICAgIGJhc2Vfc2hhID0gZ2l0X29rKCJyZXYtcGFyc2UiLCByZW1vdGVf
cmVmKS5zdHJpcCgpCiAgICAgICAgZXhjZXB0IFJ1bnRpbWVFcnJvciBhcyBlOgogICAgICAgICAg
ICBwcmludChmIltGRl0gTk9fR086IHtyZW1vdGVfcmVmfSBpbnRyb3V2YWJsZSAoe2V9KSIsIGZs
dXNoPVRydWUpCiAgICAgICAgICAgIHJldHVybiAyCiAgICAgICAgbWIgPSBnaXRfb2soIm1lcmdl
LWJhc2UiLCAicmVmcy9hbGluYS9sb2NhbC13b3JrIiwgYmFzZV9zaGEpLnN0cmlwKCkKICAgICAg
ICBsaW5lcywgY2hhbmdlcywgZGVscyA9IGJ1aWxkX2luZGV4X2xpbmVzKG1iLCAicmVmcy9hbGlu
YS9sb2NhbC13b3JrIikKICAgICAgICBwcmludChmIltGRl0gYmFzZT17YmFzZV9zaGFbOjEyXX0g
bWVyZ2UtYmFzZT17bWJbOjEyXX0gIgogICAgICAgICAgICAgIGYifCB7Y2hhbmdlc30gbW9kaWYv
YWpvdXQsIHtkZWxzfSBzdXBwcmVzc2lvbihzKSIsIGZsdXNoPVRydWUpCiAgICAgICAgaWYgbm90
IGxpbmVzOgogICAgICAgICAgICBwcmludCgiW0ZGXSBhdWN1biBjaGFuZ2VtZW50IGxvY2FsIGEg
cG91c3NlciA7IHJpZW4gYSBmYWlyZS4iLAogICAgICAgICAgICAgICAgICBmbHVzaD1UcnVlKQog
ICAgICAgICAgICByZXR1cm4gMAoKICAgICAgICBpZiBvcy5wYXRoLmV4aXN0cyhhYnNfdG1wKToK
ICAgICAgICAgICAgb3MucmVtb3ZlKGFic190bXApCiAgICAgICAgZW52ID0geyJHSVRfSU5ERVhf
RklMRSI6IGFic190bXB9CiAgICAgICAgcHJpbnQoZiJbRkZdIHJlYWQtdHJlZSB7YmFzZV9zaGFb
OjEyXX0gKGluZGV4IHRlbXBvcmFpcmUpIC4uLiIsCiAgICAgICAgICAgICAgZmx1c2g9VHJ1ZSkK
ICAgICAgICByID0gZ2l0KCJyZWFkLXRyZWUiLCBiYXNlX3NoYSwgZW52X2V4dHJhPWVudikKICAg
ICAgICBpZiByLnJldHVybmNvZGU6CiAgICAgICAgICAgIHByaW50KGYiW0ZGXSBOT19HTyByZWFk
LXRyZWU6IHtyLnN0ZGVyci5zdHJpcCgpWzozMDBdfSIsIGZsdXNoPVRydWUpCiAgICAgICAgICAg
IHJldHVybiAyCiAgICAgICAgcHJpbnQoZiJbRkZdIHVwZGF0ZS1pbmRleCA6IHtsZW4obGluZXMp
fSBlbnRyZWUocykgZW4gbG90IC4uLiIsCiAgICAgICAgICAgICAgZmx1c2g9VHJ1ZSkKICAgICAg
ICByID0gZ2l0KCJ1cGRhdGUtaW5kZXgiLCAiLS1pbmRleC1pbmZvIiwgZW52X2V4dHJhPWVudiwK
ICAgICAgICAgICAgICAgIGlucD0iXG4iLmpvaW4obGluZXMpICsgIlxuIikKICAgICAgICBpZiBy
LnJldHVybmNvZGU6CiAgICAgICAgICAgIHByaW50KGYiW0ZGXSBOT19HTyB1cGRhdGUtaW5kZXg6
IHtyLnN0ZGVyci5zdHJpcCgpWzozMDBdfSIsCiAgICAgICAgICAgICAgICAgIGZsdXNoPVRydWUp
CiAgICAgICAgICAgIHJldHVybiAyCiAgICAgICAgcHJpbnQoIltGRl0gd3JpdGUtdHJlZSAuLi4i
LCBmbHVzaD1UcnVlKQogICAgICAgIHIgPSBnaXQoIndyaXRlLXRyZWUiLCBlbnZfZXh0cmE9ZW52
KQogICAgICAgIGlmIHIucmV0dXJuY29kZToKICAgICAgICAgICAgcHJpbnQoZiJbRkZdIE5PX0dP
IHdyaXRlLXRyZWU6IHtyLnN0ZGVyci5zdHJpcCgpWzozMDBdfSIsCiAgICAgICAgICAgICAgICAg
IGZsdXNoPVRydWUpCiAgICAgICAgICAgIHJldHVybiAyCiAgICAgICAgdHJlZSA9IHIuc3Rkb3V0
LnN0cmlwKCkKICAgICAgICBwcmludChmIltGRl0gdHJlZT17dHJlZVs6MTJdfSIsIGZsdXNoPVRy
dWUpCiAgICAgICAgbXNnID0gKCJjaG9yZShzeW5jKTogcmVjb25jaWxlIGxvY2FsIHdvcmsgb250
byBvcmlnaW4vbWFpblxuXG4iCiAgICAgICAgICAgICAgICJGYXN0LWZvcndhcmQgcGx1bWJpbmcg
KHJlYmFzZSBpbXBvc3NpYmxlIG9uIHNoYWxsb3crcGFydGlhbCAiCiAgICAgICAgICAgICAgICJj
bG9uZSkuIENvZGUgZmlsZXMgZnJvbSBsb2NhbCBjb21taXRzIG9ubHk7IGNhdGFsb2cvIGtlcHQg
YXQgIgogICAgICAgICAgICAgICAib3JpZ2luL21haW4uXG5cbiIKICAgICAgICAgICAgICAgIkNv
LUF1dGhvcmVkLUJ5OiBDbGF1ZGUgT3B1cyA0LjggPG5vcmVwbHlAYW50aHJvcGljLmNvbT4iKQog
ICAgICAgIHIgPSBnaXQoImNvbW1pdC10cmVlIiwgdHJlZSwgIi1wIiwgYmFzZV9zaGEsICItbSIs
IG1zZykKICAgICAgICBpZiByLnJldHVybmNvZGU6CiAgICAgICAgICAgIHByaW50KGYiW0ZGXSBO
T19HTyBjb21taXQtdHJlZToge3Iuc3RkZXJyLnN0cmlwKClbOjMwMF19IiwKICAgICAgICAgICAg
ICAgICAgZmx1c2g9VHJ1ZSkKICAgICAgICAgICAgcmV0dXJuIDIKICAgICAgICBjb21taXQgPSBy
LnN0ZG91dC5zdHJpcCgpCiAgICAgICAgcHJpbnQoZiJbRkZdIGNvbW1pdD17Y29tbWl0WzoxMl19
IiwgZmx1c2g9VHJ1ZSkKCiAgICAgICAgaWYgZHJ5OgogICAgICAgICAgICBkID0gZ2l0X29rKCJk
aWZmIiwgIi0tbmFtZS1vbmx5IiwgY29tbWl0LCAicmVmcy9hbGluYS9sb2NhbC13b3JrIikKICAg
ICAgICAgICAgbm9uY2F0ID0gW3AgZm9yIHAgaW4gZC5zcGxpdGxpbmVzKCkKICAgICAgICAgICAg
ICAgICAgICAgIGlmIHAgYW5kIG5vdCBwLnN0YXJ0c3dpdGgoImNhdGFsb2cvIildCiAgICAgICAg
ICAgIHByaW50KGYiW0ZGXSBEUlktUlVOIDogY29tbWl0IGNvbnN0cnVpdCA7IGRpZmYgY29kZSB2
cyBsb2NhbCA9ICIKICAgICAgICAgICAgICAgICAgZiJ7bGVuKG5vbmNhdCl9ICgwID0gY29udGVu
dSBpZGVudGlxdWUpLiAiCiAgICAgICAgICAgICAgICAgICJtYWluIGluY2hhbmdlLCBhdWN1biBw
dXNoLiIsIGZsdXNoPVRydWUpCiAgICAgICAgICAgIGlmIG5vbmNhdFs6NV06CiAgICAgICAgICAg
ICAgICBwcmludChmIiAgICAgZGl2ZXJnZW5jZXM6IHtub25jYXRbOjVdfSIsIGZsdXNoPVRydWUp
CiAgICAgICAgICAgIHJldHVybiAwCgogICAgICAgIGdpdF9vaygidXBkYXRlLXJlZiIsIGYicmVm
cy9oZWFkcy97YnJhbmNofSIsIGNvbW1pdCkKICAgICAgICBwcmludChmIltGRl0gcHVzaCB7cmVt
b3RlfSB7YnJhbmNofSAuLi4iLCBmbHVzaD1UcnVlKQogICAgICAgIHAgPSBnaXQoInB1c2giLCBy
ZW1vdGUsIGJyYW5jaCkKICAgICAgICBvdXQgPSAocC5zdGRvdXQgb3IgIiIpICsgKHAuc3RkZXJy
IG9yICIiKQogICAgICAgIGlmIHAucmV0dXJuY29kZSA9PSAwOgogICAgICAgICAgICBwcmludCgi
W0ZGXSA9PT0+IFBVU0ggT0sgPD09PSIsIGZsdXNoPVRydWUpCiAgICAgICAgICAgIHByaW50KGYi
W0ZGXSBIRUFEIHBvdXNzZSA6IHtjb21taXRbOjEyXX0iLCBmbHVzaD1UcnVlKQogICAgICAgICAg
ICByZXR1cm4gMAogICAgICAgIGlmIGFueShzIGluIG91dCBmb3IgcyBpbiAoIm5vbi1mYXN0LWZv
cndhcmQiLCAiZmV0Y2ggZmlyc3QiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgICAgICAg
InJlamVjdGVkIiwgInN0YWxlIGluZm8iKSk6CiAgICAgICAgICAgIHByaW50KCJbRkZdIG9yaWdp
biBhIGF2YW5jZSBwZW5kYW50IGwnb3BlcmF0aW9uIDsgbm91dmVsbGUgIgogICAgICAgICAgICAg
ICAgICAidGVudGF0aXZlLi4uIiwgZmx1c2g9VHJ1ZSkKICAgICAgICAgICAgY29udGludWUKICAg
ICAgICBwcmludChmIltGRl0gTk9fR08gcHVzaDoge291dC5zdHJpcCgpWzo0MDBdfSIsIGZsdXNo
PVRydWUpCiAgICAgICAgcmV0dXJuIDEKCiAgICBwcmludCgiW0ZGXSBOT19HTzogdHJvcCBkZSB0
ZW50YXRpdmVzIChvcmlnaW4gYXZhbmNlIHRyb3Agdml0ZSkuIiwKICAgICAgICAgIGZsdXNoPVRy
dWUpCiAgICByZXR1cm4gMQoKCmRlZiBtYWluKCk6CiAgICBnbG9iYWwgR0lULCBST09UCiAgICBh
cCA9IGFyZ3BhcnNlLkFyZ3VtZW50UGFyc2VyKCkKICAgIGFwLmFkZF9hcmd1bWVudCgiLS1naXQi
LCBkZWZhdWx0PSJnaXQiKQogICAgYXAuYWRkX2FyZ3VtZW50KCItLXJvb3QiLCBkZWZhdWx0PU5v
bmUsCiAgICAgICAgICAgICAgICAgICAgaGVscD0icmFjaW5lIGR1IGRlcG90IChzaW5vbiBBTElO
QV9ST09UIG91IGRldXggbml2ZWF1eCBhdS1kZXNzdXMpIikKICAgIGFwLmFkZF9hcmd1bWVudCgi
LS1yZW1vdGUiLCBkZWZhdWx0PSJvcmlnaW4iKQogICAgYXAuYWRkX2FyZ3VtZW50KCItLWJyYW5j
aCIsIGRlZmF1bHQ9Tm9uZSkKICAgIGFwLmFkZF9hcmd1bWVudCgiLS1kcnktcnVuIiwgYWN0aW9u
PSJzdG9yZV90cnVlIikKICAgIGFwLmFkZF9hcmd1bWVudCgiLS1uby1mZXRjaCIsIGFjdGlvbj0i
c3RvcmVfdHJ1ZSIpCiAgICBhcC5hZGRfYXJndW1lbnQoIi0tbm8tY29tbWl0IiwgYWN0aW9uPSJz
dG9yZV90cnVlIiwKICAgICAgICAgICAgICAgICAgICBoZWxwPSJuZSBmaWdlIHBhcyBsZSBXSVAs
IHBvdXNzZSBzZXVsZW1lbnQgY2UgcXVpIGVzdCBjb21taXRlIikKICAgIGFwLmFkZF9hcmd1bWVu
dCgiLS1iYXNlIiwgZGVmYXVsdD1Ob25lLCBoZWxwPSJkZWJ1ZzogYnVpbGQgb24gdGhpcyByZWYi
KQogICAgYXJncyA9IGFwLnBhcnNlX2FyZ3MoKQogICAgR0lUID0gYXJncy5naXQKICAgIGlmIGFy
Z3Mucm9vdDoKICAgICAgICBST09UID0gb3MucGF0aC5hYnNwYXRoKGFyZ3Mucm9vdCkKICAgIGJy
YW5jaCA9IGFyZ3MuYnJhbmNoIG9yIGN1cnJlbnRfYnJhbmNoKCJtYWluIikKCiAgICB0cnk6CiAg
ICAgICAgaWYgbm90IGFyZ3Mubm9fY29tbWl0OgogICAgICAgICAgICBzbmFwc2hvdF93aXAoYnJh
bmNoLCBhcmdzLmRyeV9ydW4pCiAgICBleGNlcHQgRXhjZXB0aW9uIGFzIGU6ICAjIG5vcWE6IEJM
RTAwMQogICAgICAgIHByaW50KGYiW1dJUF0gTk9fR08gc25hcHNob3QgKHtlfSkgOyBvbiBwb3Vz
c2UgY2UgcXVpIGVzdCBkZWphICIKICAgICAgICAgICAgICAiY29tbWl0ZS4iLCBmbHVzaD1UcnVl
KQoKICAgIHJldHVybiBmYXN0X2ZvcndhcmRfcHVzaChicmFuY2gsIGFyZ3MucmVtb3RlLCBhcmdz
LmJhc2UsCiAgICAgICAgICAgICAgICAgICAgICAgICAgICAgYXJncy5kcnlfcnVuLCBhcmdzLm5v
X2ZldGNoKQoKCmlmIF9fbmFtZV9fID09ICJfX21haW5fXyI6CiAgICBzeXMuZXhpdChtYWluKCkp
Cg==
#ALINA_B64_END

