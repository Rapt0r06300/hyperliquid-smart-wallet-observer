@echo off
setlocal
cd /d "%~dp0"
REM ============================================================================
REM  POUSSER LE TRAVAIL LANCEUR (14 commits) vers GitHub — SANS RIEN PERDRE.
REM  GitHub avait avance de son cote : ce .cmd rejoue UNIQUEMENT mes 14 commits
REM  du chantier lanceur PAR-DESSUS l'etat actuel de GitHub -> fast-forward propre,
REM  aucun --force, les 442 commits + les docs deja sur GitHub sont conserves.
REM  Que du git (fetch + push). A double-cliquer sur TA machine.
REM ============================================================================
echo.
echo   === POUSSER LE CHANTIER LANCEUR (14 commits) vers GitHub ===
echo.
where git >nul 2>nul || ( echo   [ERREUR] git introuvable. Installe Git puis relance. & pause & exit /b 1 )

echo   [1/4] Recuperation de l'etat actuel de GitHub...
git fetch origin main
if errorlevel 1 ( echo   [ERREUR] fetch origin echoue (reseau / acces GitHub^). & pause & exit /b 1 )

echo   [2/4] Verification du bundle...
git bundle verify "hypersmart_launcher.bundle"
if errorlevel 1 ( echo   [ERREUR] bundle invalide ou introuvable a cote de ce .cmd. & pause & exit /b 1 )

echo   [3/4] Recuperation de mes 14 commits lanceur (par-dessus GitHub)...
git fetch "hypersmart_launcher.bundle" launcher-sur-github
if errorlevel 1 ( echo   [ERREUR] fetch du bundle echoue. & pause & exit /b 1 )

echo   [4/4] Envoi vers origin/main (fast-forward, sans force)...
git push origin FETCH_HEAD:main
if errorlevel 1 (
  echo.
  echo   [ATTENTION] Push refuse : GitHub a ENCORE avance depuis la preparation de ce bundle.
  echo   NE FORCE PAS (tu perdrais le travail ajoute sur GitHub entre-temps^).
  echo   Redemande-moi de reconstruire le bundle sur la nouvelle base de GitHub.
  echo.
  pause
  exit /b 2
)

echo.
echo   [OK] Chantier lanceur pousse sur origin/main (14 commits ajoutes, rien perdu^).
echo.
echo   Optionnel — aligner ton depot LOCAL sur l'etat pousse :
echo       git fetch origin
echo       git checkout main ^&^& git merge --ff-only origin/main
echo   (Tu peux ensuite supprimer ce .cmd, hypersmart_launcher.bundle et l'ancien
echo    hypersmart_428.bundle qui ne doit PLUS etre utilise^.)
echo.
pause
endlocal
exit /b 0
