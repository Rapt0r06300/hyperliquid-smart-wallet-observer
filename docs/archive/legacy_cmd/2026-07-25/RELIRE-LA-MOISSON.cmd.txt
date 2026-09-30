@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ==================================================================================
REM   RELIRE LA MOISSON  --  rentabiliser un scan deja fait (choix B de Flo, 15/07)
REM
REM   Le dernier run a trouve BEAUCOUP de depots (jusqu'a 176k) mais n'a eu le temps
REM   d'en LIRE qu'une petite part, et par etoiles (donc des gros repos ML d'abord).
REM
REM   Ce lanceur NE RE-SCANNE PAS. Il reprend les depots deja sauvegardes et les RELIT
REM   INTELLIGEMMENT : ceux de NOTRE domaine d'abord (funding, perp, arbitrage, micro-
REM   structure...), puis il ouvre le CODE des meilleurs (etape 3 = l'architecture).
REM   -> il donne enfin sa chance a la bonne recolte, sans attendre 8 h de plus.
REM
REM   Duree : ~3 h (assez pour lire les meilleurs depots + ouvrir le code), puis il ECRIT
REM   le rapport moisson-fini.md a la racine. NE FERME PAS la fenetre "MOISSON 12h - travail"
REM   avant la fin, sinon le .md ne sera pas ecrit (mais l'etat reste sauve : on peut relancer).
REM
REM   Ta cle GitHub reste en memoire de cette fenetre, jamais ecrite sur le disque.
REM   POUR FERMER A TOUT MOMENT : double-clique FERMER-MOISSON.cmd
REM ==================================================================================

echo.
echo   ================================================================
echo     RELIRE LA MOISSON  (sans re-scanner)
echo   ================================================================
echo.

if not exist "%~dp0data\reports\moisson_10h_etat.json" (
  echo   Aucun etat sauvegarde trouve ^(data\reports\moisson_10h_etat.json^).
  echo   Lance d'abord une moisson normale ^(LANCER-MOISSON-12H.cmd^).
  echo.
  pause
  exit /b 0
)

echo   Colle ta cle GitHub (elle commence par ghp_ ou github_pat_).
echo   Elle sert a LIRE les README et le code (5000 req/h au lieu de 60).
echo.

if not "%GITHUB_TOKEN%"=="" (
  echo   Une cle est deja presente : on l'utilise.
  goto :demarrer
)

set /p GITHUB_TOKEN=  Ta cle GitHub :

if "%GITHUB_TOKEN%"=="" (
  echo.
  set /p SANS=  Aucune cle. Relire quand meme SANS cle ? tape O pour oui :
  if /I not "!SANS!"=="O" (
    echo   Annule. Relance ce fichier avec ta cle.
    pause
    exit /b 0
  )
)

:demarrer
REM  on nettoie SEULEMENT les fichiers du tableau de bord -- PAS l'etat (les depots trouves).
if exist "%~dp0moisson-termine.flag" del "%~dp0moisson-termine.flag" >nul 2>&1
if exist "%~dp0moisson-en-cours.txt" del "%~dp0moisson-en-cours.txt" >nul 2>&1

REM  on lance le TRAVAIL en mode relire, dans une fenetre reduite (elle herite de la cle)
start "MOISSON 12h - travail (NE PAS FERMER)" /min "%~dp0_relire_worker.cmd"

REM  ... et CETTE fenetre devient le tableau de bord SANS CLIGNOTEMENT ni SAUT.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\voir_dashboard.ps1" -Root "%~dp0"

echo.
echo   ================================================================
echo     RELECTURE TERMINEE.  Resultat : moisson-fini.md  (a la racine)
echo     Journal detaille     : moisson_console.txt
echo   ================================================================
echo.
pause
