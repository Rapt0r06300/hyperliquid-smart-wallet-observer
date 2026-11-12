@echo off
chcp 65001 >nul
setlocal
set "ALINA_LAUNCH_RUN_ID=%DATE%_%TIME%_%RANDOM%_%RANDOM%"
set "ALINA_LAUNCH_MODE=run-wsl-node"
set "ALINA_LAUNCH_PYTHON=not-used"
set "FINAL_RC=0"
set "SHP="
title Noeud HL (Ubuntu dedie)
call "%~dp0tools\launcher_log.cmd" "Noeud-HL" START preflight "node-entry" ""
echo.
echo Noeud Hyperliquid - distro DEDIEE Ubuntu. On ne touche PAS Salad.
echo Laisse la fenetre OUVERTE. Ctrl+C pour arreter.
echo.
wsl -d Ubuntu -e true >nul 2>nul
set "WSL_PREFLIGHT_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "Noeud-HL" RESULT wsl-preflight "wsl -d Ubuntu -e true" "%WSL_PREFLIGHT_RC%"
if not "%WSL_PREFLIGHT_RC%"=="0" goto noubuntu
for /f "delims=" %%p in ('wsl -d Ubuntu wslpath "%~dp0tools\noeud_run.sh"') do set "SHP=%%p"
if not defined SHP set "PATH_RC=1"
if defined SHP set "PATH_RC=0"
call "%~dp0tools\launcher_log.cmd" "Noeud-HL" RESULT path-resolution "wslpath-noeud_run.sh" "%PATH_RC%"
if not "%PATH_RC%"=="0" goto path_failed
wsl -d Ubuntu bash -c "sed -i 's/\r$//' '%SHP%'"
set "SED_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "Noeud-HL" RESULT normalize-script "sed-crlf-normalization" "%SED_RC%"
if not "%SED_RC%"=="0" goto normalize_failed
wsl -d Ubuntu bash "%SHP%"
set "NODE_RC=%ERRORLEVEL%"
call "%~dp0tools\launcher_log.cmd" "Noeud-HL" RESULT node-run "noeud_run.sh" "%NODE_RC%"
set "FINAL_RC=%NODE_RC%"
goto finish

:noubuntu
call "%~dp0tools\launcher_log.cmd" "Noeud-HL" RESULT preflight "ubuntu-distro-missing" "1"
echo Distro Ubuntu absente. Lance d'abord Installer Noeud HL.cmd
set "FINAL_RC=1"
goto finish

:path_failed
echo [ERREUR] Impossible de resoudre le chemin WSL du script du noeud.
set "FINAL_RC=1"
goto finish

:normalize_failed
echo [ERREUR] Echec de normalisation du script du noeud.
set "FINAL_RC=%SED_RC%"
goto finish

:finish
call "%~dp0tools\launcher_log.cmd" "Noeud-HL" EXIT completion "node-launcher-finished" "%FINAL_RC%"
echo.
echo Noeud arrete. Code retour: %FINAL_RC%.
pause
endlocal & exit /b %FINAL_RC%
