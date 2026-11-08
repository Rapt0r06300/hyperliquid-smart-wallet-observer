@echo off
chcp 65001 >nul
setlocal
title Installation du noeud Hyperliquid local (PAPER / lecture seule)

rem ===========================================================================
rem  Noeud Hyperliquid LOCAL — fills de TOUS les users, gratuit, PAPER.
rem  Source officielle a verifier : https://github.com/hyperliquid-dex/node
rem  (si le nom du binaire ou du flag change, edite URL_BINAIRE / FLAGS ci-dessous)
rem ===========================================================================
set "URL_BINAIRE=https://binaries.hyperliquid.xyz/Mainnet/hl-visor"
set "FLAGS=run-non-validator --write-fills"

echo.
echo ==================================================================
echo   Installation du noeud Hyperliquid local
echo   - Non-validateur : aucune cle, aucun ordre (PAPER / lecture seule)
echo   - Ecrit node_fills_by_block = tous les fills de tous les users
echo ==================================================================
echo.

rem --- 1) WSL2 present ? ---
wsl --status >nul 2>&1
if errorlevel 1 (
  echo WSL2 n'est pas installe. Je lance l'installation ^(fenetre admin + redemarrage^).
  echo Apres le redemarrage, RELANCE ce fichier en double-clic.
  powershell -NoProfile -Command "Start-Process cmd -ArgumentList '/c wsl --install' -Verb RunAs"
  echo.
  pause
  exit /b 0
)

echo WSL2 OK. Telechargement + lancement du noeud dans Ubuntu...
echo ^(Laisse cette fenetre OUVERTE : le noeud tourne tant qu'elle est ouverte.^)
echo.

rem --- 2) telecharger le binaire + config + lancer ---
wsl bash -lc "set -e; mkdir -p ~/hl/data; echo Telechargement...; curl -fL -o ~/hl-visor %URL_BINAIRE%; chmod +x ~/hl-visor; echo {\"chain\":\"Mainnet\"} > ~/visor.json; echo; echo Chemin Windows des donnees : \\wsl.localhost\Ubuntu$HOME/hl/data/node_fills_by_block; echo; echo Lancement du noeud (Ctrl+C pour arreter)...; ~/hl-visor %FLAGS%"

echo.
echo Noeud arrete. Les donnees sont dans ~/hl/data (cote WSL).
pause
endlocal
