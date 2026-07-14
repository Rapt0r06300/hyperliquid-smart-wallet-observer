@echo off
title REPLAY 4H - PROGRESSION EN DIRECT (lecture seule, ne touche pas au run)
cd /d "%~dp0"
echo ============================================================
echo   SUIVI DU REPLAY 4H (live). Cette fenetre LIT le log,
echo   elle ne touche PAS au run. Ferme-la quand tu veux : le
echo   replay continue. Rouvre ce fichier pour re-suivre.
echo ============================================================
echo.
:wait
if not exist "runtime\scenarios\replay_4h.log" (
  echo En attente du log... (le run demarre^)
  timeout /t 3 >nul
  goto wait
)
powershell -NoProfile -Command "Get-Content 'runtime\scenarios\replay_4h.log' -Wait -Tail 30"
