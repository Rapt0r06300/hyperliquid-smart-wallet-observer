@echo off
chcp 65001 >nul
setlocal
set "ALINA_LAUNCH_RUN_ID=%DATE%_%TIME%_%RANDOM%_%RANDOM%"
set "ALINA_LAUNCH_MODE=install-wsl-node"
set "ALINA_LAUNCH_PYTHON=not-used"
set "FINAL_RC=0"
set "SHP="
title Installation noeud HL (Ubuntu dedie)
call "%~dp0tools\launcher_log.cmd" "Installer Noeud HL" START preflight "installer-entry" ""
echo.
echo Noeud Hyperliquid - distro DEDIEE Ubuntu. On ne touche PAS Salad.
echo Laisse la fenetre OUVERTE. Ctrl+C pour arreter.
echo.
wsl -d Ubuntu -e true >nul 2>nul
set "WSL_PREFLIGHT_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "Installer Noeud HL" RESULT wsl-preflight "wsl -d Ubuntu -e true" "%WSL_PREFLIGHT_RC%"
if not "%WSL_PREFLIGHT_RC%"=="0" goto noubuntu
for /f "delims=" %%p in ('wsl -d Ubuntu wslpath "%~dp0tools\noeud_setup.sh"') do set "SHP=%%p"
if not defined SHP set "PATH_RC=1"
if defined SHP set "PATH_RC=0"
call "%~dp0tools\launcher_log.cmd" "Installer Noeud HL" RESULT path-resolution "wslpath-noeud_setup.sh" "%PATH_RC%"
if not "%PATH_RC%"=="0" goto path_failed
wsl -d Ubuntu bash -c "sed -i 's/\r$//' '%SHP%'"
set "NORMALIZE_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "Installer Noeud HL" RESULT normalize-script "sed-crlf-normalization" "%NORMALIZE_RC%"
if not "%NORMALIZE_RC%"=="0" goto normalize_failed
wsl -d Ubuntu bash "%SHP%"
set "NODE_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "Installer Noeud HL" RESULT node-setup "noeud_setup.sh" "%NODE_RC%"
set "FINAL_RC=%NODE_RC%"
goto finish

:noubuntu
call "%~dp0tools\launcher_log.cmd" "Installer Noeud HL" STEP install "wsl --install -d Ubuntu" ""
echo Ubuntu n'est pas installe. Installation d'une distro Ubuntu SEPAREE de Salad...
echo (Une fenetre d'installation va s'ouvrir ; cela peut prendre quelques minutes.)
wsl --install -d Ubuntu
set "FINAL_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "Installer Noeud HL" RESULT install "wsl --install -d Ubuntu" "%FINAL_RC%"
echo.
echo Quand Ubuntu demande : choisis un identifiant + un mot de passe.
echo Ensuite RELANCE ce fichier (Installer Noeud HL.cmd).
goto finish

:path_failed
echo [ERREUR] Impossible de resoudre le chemin WSL du script de configuration.
set "FINAL_RC=1"
goto finish

:normalize_failed
echo [ERREUR] Echec de normalisation du script de configuration.
set "FINAL_RC=%NORMALIZE_RC%"
goto finish

:finish
call "%~dp0tools\launcher_log.cmd" "Installer Noeud HL" EXIT completion "installer-finished" "%FINAL_RC%"
echo.
echo Installation/configuration terminee. Code retour: %FINAL_RC%.
pause
endlocal & exit /b %FINAL_RC%
