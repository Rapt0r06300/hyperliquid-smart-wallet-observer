@echo off
chcp 65001 >nul
setlocal
title Installation noeud HL (Ubuntu dedie)
echo.
echo Noeud Hyperliquid - distro DEDIEE Ubuntu. On ne touche PAS Salad.
echo Laisse la fenetre OUVERTE. Ctrl+C pour arreter.
echo.
wsl -d Ubuntu -e true 2>nul
if errorlevel 1 goto noubuntu
for /f "delims=" %%p in ('wsl -d Ubuntu wslpath "%~dp0tools\noeud_setup.sh"') do set "SHP=%%p"
wsl -d Ubuntu bash -c "sed -i 's/\r$//' '%SHP%'"
wsl -d Ubuntu bash "%SHP%"
echo.
echo Noeud arrete.
pause
exit /b 0

:noubuntu
echo Ubuntu absent. Installation d'une distro Ubuntu SEPAREE de Salad...
wsl --install -d Ubuntu
echo.
echo Termine la config Ubuntu : choisis un identifiant et un mot de passe.
echo Puis RELANCE ce fichier.
pause
exit /b 0
