@echo off
setlocal
title HyperSmart - Creer archive propre
cd /d "%~dp0"
echo HyperSmart Observer - archive propre
echo Projet: %CD%
echo.
echo Cette commande cree un ZIP propre directement sur le Bureau.
echo Elle n'archive jamais logs\, data\, .git\, SQLite, caches, .env ou archives.
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\create_clean_archive.ps1" -ProjectRoot "%~dp0"
if errorlevel 1 (
  echo.
  echo ERREUR: archive propre non creee. Voir le message PowerShell ci-dessus.
  pause
  exit /b 1
)
echo.
echo Archive propre creee avec succes sur le Bureau.
pause
