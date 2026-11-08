@echo off
chcp 65001 >nul
setlocal
title Installation du noeud Hyperliquid (distro DEDIEE - ne touche pas Salad)
set "DISTRO=Ubuntu"
set "URL_BINAIRE=https://binaries.hyperliquid.xyz/Mainnet/hl-visor"
set "FLAGS=run-non-validator --write-fills"

echo.
echo ==================================================================
echo   Noeud Hyperliquid local - distro DEDIEE %DISTRO%
echo   IMPORTANT : on n'utilise PAS ta distro Salad. Rien n'y est touche.
echo   Non-validateur : aucune cle, aucun ordre (PAPER / lecture seule).
echo ==================================================================
echo.

rem --- Ubuntu dediee presente ? ---
wsl -d %DISTRO% -e true 2>nul
if errorlevel 1 (
  echo La distro %DISTRO% n'existe pas encore. Je l'installe ^(separee de Salad^).
  echo A la 1re ouverture d'Ubuntu : choisis un nom d'utilisateur + un mot de passe.
  echo Puis RELANCE ce fichier.
  wsl --install -d %DISTRO%
  echo.
  pause
  exit /b 0
)

echo Ubuntu OK. Preparation + telechargement + lancement du noeud...
echo ^(Laisse cette fenetre OUVERTE : le noeud tourne tant qu'elle est ouverte.^)
echo ^(Un mot de passe sudo peut etre demande pour installer curl dans Ubuntu.^)
echo.

wsl -d %DISTRO% bash -lc "set -e; if ! command -v curl >/dev/null; then echo Installation de curl dans Ubuntu...; sudo apt-get update -y && sudo apt-get install -y curl; fi; mkdir -p ~/hl/data; echo Telechargement du noeud...; curl -fL -o ~/hl-visor %URL_BINAIRE%; chmod +x ~/hl-visor; printf '{\"chain\":\"Mainnet\"}' > ~/visor.json; echo; echo Chemin Windows des donnees : \\wsl.localhost\%DISTRO%\root\hl\data; echo; echo Lancement du noeud (Ctrl+C pour arreter)...; ~/hl-visor %FLAGS%"

echo.
echo Noeud arrete.
pause
endlocal
