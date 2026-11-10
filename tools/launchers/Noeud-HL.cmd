@echo off
chcp 65001 >nul
setlocal
title Noeud HL (Ubuntu dedie)
echo.
echo Noeud Hyperliquid - distro DEDIEE Ubuntu. On ne touche PAS Salad.
echo Laisse la fenetre OUVERTE. Ctrl+C pour arreter.
echo.
wsl -d Ubuntu -e true >nul 2>nul
if not "%errorlevel%"=="0" goto noubuntu
for /f "delims=" %%p in ('wsl -d Ubuntu wslpath "%~dp0..\..\tools\noeud_run.sh"') do set "SHP=%%p"
wsl -d Ubuntu bash -c "sed -i 's/\r$//' '%SHP%'"
wsl -d Ubuntu bash "%SHP%"
echo.
echo Noeud arrete.
pause
exit /b 0

:noubuntu
echo Distro Ubuntu absente. Lance d'abord Installer Noeud HL.cmd
pause
exit /b 0
