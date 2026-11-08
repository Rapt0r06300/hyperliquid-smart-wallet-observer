@echo off
chcp 65001 >nul
setlocal
title Installation du noeud Hyperliquid (Ubuntu dedie - ne touche pas Salad)
set "DISTRO=Ubuntu"
set "URL_BINAIRE=https://binaries.hyperliquid.xyz/Mainnet/hl-visor"
set "FLAGS=run-non-validator --write-fills"
echo.
echo ==================================================================
echo   Noeud Hyperliquid local - distro DEDIEE %DISTRO%
echo   On n'utilise PAS Salad. Rien n'y est touche.
echo   Non-validateur : aucune cle, aucun ordre (PAPER / lecture seule).
echo ==================================================================
echo.
wsl -d %DISTRO% -e true 2>nul
if errorlevel 1 (
  echo La distro %DISTRO% n'existe pas. Je l'installe (separee de Salad).
  echo A la 1re ouverture : choisis un nom d'utilisateur + un mot de passe, puis RELANCE ce fichier.
  wsl --install -d %DISTRO%
  echo.
  pause
  exit /b 0
)
echo Ubuntu OK. Telechargement + lancement du noeud...
echo (Laisse cette fenetre OUVERTE. Un mot de passe sudo peut etre demande pour installer curl.)
echo.
wsl -d %DISTRO% bash -lc "set -e; if ! command -v curl >/dev/null; then echo Installation de curl dans Ubuntu...; sudo apt-get update -y && sudo apt-get install -y curl; fi; mkdir -p ~/hl/data; echo Telechargement du noeud...; curl -fL -o ~/hl-visor %URL_BINAIRE%; chmod +x ~/hl-visor; DQ=$(printf '"'); echo {${DQ}chain${DQ}:${DQ}Mainnet${DQ}} > ~/visor.json; echo; echo Donnees cote Windows : \wsl.localhost\%DISTRO%oot\hl\data; echo; echo Lancement du noeud (Ctrl+C pour arreter)...; ~/hl-visor %FLAGS%"
echo.
echo Noeud arrete.
pause
endlocal
