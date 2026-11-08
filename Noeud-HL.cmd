@echo off
chcp 65001 >nul
title Noeud Hyperliquid local (Ubuntu dedie - ne touche pas Salad)
set "DISTRO=Ubuntu"
set "FLAGS=run-non-validator --write-fills"
echo.
echo Lancement du noeud dans la distro dediee %DISTRO% (pas Salad)...
echo (Laisse cette fenetre OUVERTE ; Ctrl+C pour arreter.)
echo.
wsl -d %DISTRO% -e true 2>nul
if errorlevel 1 (
  echo Distro %DISTRO% absente. Lance d'abord 'Installer Noeud HL.cmd'.
  pause
  exit /b 1
)
wsl -d %DISTRO% bash -lc "test -x ~/hl-visor || { echo Binaire introuvable - lance d abord Installer Noeud HL.cmd; exit 1; }; mkdir -p ~/hl/data; echo Noeud en cours (Ctrl+C pour arreter)...; ~/hl-visor %FLAGS%"
echo.
echo Noeud arrete.
pause
