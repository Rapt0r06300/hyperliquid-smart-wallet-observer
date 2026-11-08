@echo off
chcp 65001 >nul
setlocal
title Installation noeud HL (Ubuntu dedie)
echo.
echo Noeud Hyperliquid - distro DEDIEE Ubuntu (on ne touche PAS Salad).
echo (Laisse la fenetre OUVERTE ; Ctrl+C pour arreter.)
echo.
wsl -d Ubuntu -e true 2>nul
if errorlevel 1 (
  echo Ubuntu absent : installation (SEPAREE de Salad)...
  wsl --install -d Ubuntu & echo Apres la 1re config Ubuntu (identifiant+mdp), RELANCE ce fichier. & pause & exit /b 0
  pause
  exit /b 1
)
for /f "delims=" %%p in ('wsl -d Ubuntu wslpath "%~dp0tools\noeud_setup.sh"') do set "SHP=%%p"
wsl -d Ubuntu bash -c "sed -i 's/\r$//' '%SHP%'"
wsl -d Ubuntu bash "%SHP%"
echo.
echo Noeud arrete.
pause
endlocal
