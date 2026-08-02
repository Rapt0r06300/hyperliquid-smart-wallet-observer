@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"
echo ============================================================
echo   REPARER le depot git PUIS POUSSER le chantier lanceur (14 commits)
echo   Non destructif : on debloque le rebase/am coince, on garde ton HEAD,
echo   puis on ajoute mes 14 commits PAR-DESSUS GitHub (fast-forward, sans force).
echo ============================================================
echo.
where git >nul 2>nul || ( echo   [ERREUR] git introuvable dans le PATH. & pause & exit /b 1 )

echo   [1/5] Nettoyage du verrou perime et du 'git am' coince...
if exist ".git\index.lock" del /f /q ".git\index.lock" && echo       index.lock supprime.
git am --quit 2>nul
if exist ".git\rebase-apply" rmdir /s /q ".git\rebase-apply"
if exist ".git\rebase-merge" rmdir /s /q ".git\rebase-merge"
if exist ".git\MERGE_HEAD" del /f /q ".git\MERGE_HEAD"
echo       Etat remis d'aplomb. HEAD / branche :
git rev-parse --short HEAD
git rev-parse --abbrev-ref HEAD
echo.
echo   [2/5] Recuperation de l'etat actuel de GitHub...
git fetch origin main
if errorlevel 1 ( echo   [ERREUR] fetch origin echoue (reseau/acces GitHub^). & pause & exit /b 1 )
echo.
echo   [3/5] Verification du bundle...
git bundle verify "hypersmart_launcher.bundle"
if errorlevel 1 ( echo   [ERREUR] hypersmart_launcher.bundle absent ou invalide a cote de ce .cmd. & pause & exit /b 1 )
echo.
echo   [4/5] Recuperation de mes 14 commits lanceur (par-dessus GitHub)...
git fetch "hypersmart_launcher.bundle" launcher-sur-github
if errorlevel 1 ( echo   [ERREUR] fetch du bundle echoue. & pause & exit /b 1 )
echo.
echo   [5/5] Envoi vers origin/main (fast-forward, sans force)...
git push origin FETCH_HEAD:main
if errorlevel 1 (
  echo.
  echo   [ATTENTION] Push refuse : GitHub a encore avance. NE FORCE PAS (tu perdrais du travail^).
  echo   Copie-moi le message ci-dessus et je reconstruis le bundle sur la nouvelle base.
  echo.
  pause
  exit /b 2
)
echo.
echo   [OK] Repare ET pousse : les 14 commits du chantier lanceur sont sur GitHub,
echo        sans avoir rien ecrase (les 442 commits + docs de GitHub sont conserves^).
echo.
echo   Optionnel — remettre ton depot LOCAL propre et aligne :
echo       git fetch origin
echo       git checkout main
echo       git reset --hard origin/main
echo   (cecaffba, ton ancienne ligne locale, reste dans le reflog si besoin^).
echo.
pause
endlocal
exit /b 0
