@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ============================================================
echo   POUSSER vers GitHub - pousseur principal HyperSmart
echo   Repare un git coince, importe les commits de Claude (bundle^)
echo   et pousse en FAST-FORWARD. Pas de --force aveugle (ne perd rien^).
echo ============================================================
echo.
where git >nul 2>nul || ( echo   [ERREUR] git introuvable dans le PATH. & pause & exit /b 1 )

REM --- 1) Reparation defensive (verrou / rebase / am coinces) ---
if exist ".git\index.lock" del /f /q ".git\index.lock" >nul 2>nul
git am --quit >nul 2>nul
git rebase --quit >nul 2>nul
if exist ".git\rebase-apply" rmdir /s /q ".git\rebase-apply" >nul 2>nul
if exist ".git\rebase-merge" rmdir /s /q ".git\rebase-merge" >nul 2>nul
if exist ".git\MERGE_HEAD" del /f /q ".git\MERGE_HEAD" >nul 2>nul

REM --- 2) Etat actuel de GitHub ---
echo   [1/3] Recuperation de l'etat de GitHub...
git fetch origin main
if errorlevel 1 ( echo   [ERREUR] fetch origin echoue (reseau/acces GitHub^). & pause & exit /b 1 )

REM --- 3) Source a pousser : le bundle de Claude s'il est present, sinon le main local ---
set "PUSH_REF=HEAD"
set "VIA=main local"
if not exist "hypersmart_launcher.bundle" goto :apres_bundle
git bundle verify "hypersmart_launcher.bundle" >nul 2>nul
if errorlevel 1 goto :apres_bundle
git fetch "hypersmart_launcher.bundle" a-pousser >nul 2>nul
if errorlevel 1 goto :apres_bundle
set "PUSH_REF=FETCH_HEAD"
set "VIA=bundle de Claude"
:apres_bundle
echo   [2/3] Source a pousser : %VIA%.

REM --- 4) Push fast-forward (jamais de force aveugle) ---
echo   [3/3] Envoi vers origin/main...
git push origin %PUSH_REF%:main
if errorlevel 1 (
  echo.
  echo   [REFUSE] GitHub a diverge de ce que tu essaies de pousser.
  echo   NE FORCE PAS a l'aveugle : tu perdrais le travail deja en ligne.
  echo   Demande a Claude un bundle a jour (il le reconstruit sur l'etat actuel de GitHub^),
  echo   puis relance ce fichier.
  echo.
  pause
  exit /b 2
)
echo.
echo   [OK] A jour sur https://github.com/Rapt0r06300/hyperliquid-smart-wallet-observer
echo        (fast-forward, rien d'ecrase^).
echo.
pause
endlocal
exit /b 0
