@echo off
REM  Ferme proprement la moisson (fenetre "travail") et l'afficheur, s'ils tournent.
REM  Cible par TITRE de fenetre -- pas de filtre python large. Le run est reprenable.
taskkill /FI "WINDOWTITLE eq MOISSON 12h*" /T /F >nul 2>&1
taskkill /FI "WINDOWTITLE eq Tableau de bord*" /T /F >nul 2>&1
if exist "%~dp0moisson-termine.flag" del "%~dp0moisson-termine.flag" >nul 2>&1
echo   Moisson fermee. Rien n'est perdu : relancer reprend ou on s'etait arrete.
exit /b 0
