@echo off
chcp 65001 >nul
title Noeud Hyperliquid local (PAPER / lecture seule)
rem Relance le noeud DEJA installe (si pas installe, utilise 'Installer Noeud HL.cmd').
set "FLAGS=run-non-validator --write-fills"
echo.
echo Lancement du noeud Hyperliquid local...
echo (Laisse cette fenetre OUVERTE : le noeud tourne tant qu'elle est ouverte.)
echo.
wsl --status >nul 2>&1
if errorlevel 1 (
  echo WSL2 absent. Lance d'abord 'Installer Noeud HL.cmd'.
  pause
  exit /b 1
)
wsl bash -lc "test -x ~/hl-visor || { echo Binaire ~/hl-visor introuvable - lance d abord Installer Noeud HL.cmd; exit 1; }; mkdir -p ~/hl/data; echo Noeud en cours (Ctrl+C pour arreter)...; ~/hl-visor %FLAGS%"
echo.
echo Noeud arrete.
pause
