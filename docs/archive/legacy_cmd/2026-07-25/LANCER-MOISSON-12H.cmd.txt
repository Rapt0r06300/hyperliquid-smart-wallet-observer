@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

REM ==================================================================================
REM   LANCER LA MOISSON DE 12 HEURES  --  AVEC TABLEAU DE BORD SANS CLIGNOTEMENT
REM
REM   Ce fichier ouvre DEUX fenetres :
REM     1) une fenetre "travail" reduite, qui moissonne pendant 12 h ;
REM     2) CETTE fenetre, qui devient le TABLEAU DE BORD et se rafraichit EN PLACE
REM        (plus de clignotement, plus de "saut", plus de "quand je descends ca remonte").
REM
REM   Ta cle GitHub reste dans la memoire de cette fenetre, jamais ecrite sur le disque.
REM
REM   ------------------------------------------------------------------------------
REM   CE QUE LE MOISSONNEUR FAIT (resultat -> moisson-fini.md a la racine)
REM   ------------------------------------------------------------------------------
REM     - 17 sources GRATUITES (GitHub, arXiv, OpenAlex, OpenReview, Semantic Scholar,
REM       PapersWithCode, PyPI, crates.io, HN, StackExchange...) + le quant chinois.
REM     - 46 DOMAINES : gagner, SURVIVRE, la mecanique de l'exchange, notre code, le
REM       systeme quantitatif.
REM     - L'ETAPE 1 (LE SCAN) DURE ~8 H et cherche SANS JAMAIS S'ARRETER : quand la liste de
REM       requetes s'epuise, elle se RE-ALIMENTE toute seule (pagination des requetes fecondes
REM       + topics GitHub des repos trouves), en restant DANS NOTRE DOMAINE (rien de hors-sujet).
REM       Puis l'etape 2 (tri), l'etape 3 (code) et l'etape 4 (papiers) sur les ~4 h restantes.
REM         ETAPE 1 scan ~8h . ETAPE 2 tri ~2h . ETAPE 3 code ~1h . ETAPE 4 papiers ~1h
REM     - Analyse EN PROFONDEUR tout depot a substance, lit le CODE et le CORPS des
REM       meilleurs papiers, repeche par SEMANTIQUE ce que les mots-cles ratent, dedup
REM       inter-sources, meta-classement, et un BILAN DE COUVERTURE honnete.
REM
REM   Il ne se perd jamais, ne meurt jamais (reprise), ne ment jamais (tout non-lu compte).
REM
REM   OPTION HEBDOMADAIRE (ne chercher que le NOUVEAU) :  MOISSONNER-GITHUB.cmd --depuis-dernier
REM   POUR FERMER LA MOISSON A TOUT MOMENT :  double-clique FERMER-MOISSON.cmd
REM ==================================================================================

echo.
echo   ================================================================
echo     MOISSON DE 12 HEURES
echo   ================================================================
echo.
echo   Colle ta cle GitHub (elle commence par ghp_ ou github_pat_).
echo   Une cle en LECTURE SEULE suffit (droit "public_repo").
echo   Pour en creer une : github.com/settings/tokens
echo   SANS cle : 60 requetes/heure au lieu de 5000, et pas de recherche dans le code.
echo.

if not "%GITHUB_TOKEN%"=="" (
  echo   Une cle est deja presente : on l'utilise.
  goto :demarrer
)

set /p GITHUB_TOKEN=  Ta cle GitHub :

if "%GITHUB_TOKEN%"=="" (
  echo.
  set /p SANS=  Aucune cle. Lancer quand meme SANS cle ? tape O pour oui :
  if /I not "!SANS!"=="O" (
    echo   Annule. Relance ce fichier avec ta cle.
    pause
    exit /b 0
  )
)

:demarrer
REM  on nettoie les traces d'un run precedent
if exist "%~dp0moisson-termine.flag" del "%~dp0moisson-termine.flag" >nul 2>&1
if exist "%~dp0moisson-en-cours.txt" del "%~dp0moisson-en-cours.txt" >nul 2>&1

REM  on lance le TRAVAIL dans une fenetre reduite (elle herite de la cle GitHub)
start "MOISSON 12h - travail (NE PAS FERMER)" /min "%~dp0_moisson_worker.cmd"

REM  ... et CETTE fenetre devient le tableau de bord SANS CLIGNOTEMENT ni SAUT.
REM  L'afficheur (voir_dashboard.ps1) redessine EXACTEMENT la hauteur de la fenetre a
REM  chaque fois -> il ne peut pas defiler. Il ne fait que LIRE moisson-en-cours.txt.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\voir_dashboard.ps1" -Root "%~dp0"

echo.
echo   ================================================================
echo     MOISSON TERMINEE.  Resultat : moisson-fini.md  (a la racine)
echo     Journal detaille   : moisson_console.txt
echo   ================================================================
echo.
pause
