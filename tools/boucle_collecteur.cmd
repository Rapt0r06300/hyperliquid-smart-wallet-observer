@echo off
REM ============================================================================
REM  BOUCLE DE COLLECTEUR — un seul script pour les 3 collecteurs, SANS FENETRE
REM ============================================================================
REM  Usage :  boucle_collecteur.cmd <nom> <script.py> <intervalle_s> [args...]
REM
REM  POURQUOI CE FICHIER (19/07) : les 3 collecteurs (carry-feeder, marks,
REM  liquidations) ouvraient chacun une fenetre cmd au demarrage du bot. Flo :
REM  « y'a plein de fenetres qui s'ouvrent et je veux pas ca ». C'est moi qui les
REM  avais ajoutees ; elles sont supprimees.
REM
REM  MAIS un processus cache qui echoue en SILENCE serait exactement la maladie
REM  qu'on vient de corriger (105 `except: pass` -> 0). Chaque passe est donc
REM  horodatee dans runtime\logs\<nom>.log, avec le code de sortie.
REM
REM  Le log est TRONQUE au demarrage de chaque session : on veut la session en
REM  cours, pas un fichier de 2 Go apres trois jours (le bot a deja crashe une
REM  fois sur un disque plein).
REM
REM  Securite : lecture seule cote marche. 0 ordre, 0 cle, 0 signature.
REM ============================================================================
setlocal
cd /d "%~dp0.."
REM Runtime unique et valide : aucun repli silencieux vers un Python systeme/incomplet.
call "%CD%\tools\portable_env.cmd"
if errorlevel 1 exit /b 30

REM La boucle Python conserve TOUS les arguments (%*), publie un etat JSON atomique apres
REM chaque passe, relance rapidement avec backoff en cas de crash et archive les logs en gzip
REM sans troncature. Le garde anti-orphelin reste applique avant chaque passe.
"%HYPERSMART_PYTHON%" -m hl_observer.ops.collector_runner %*
exit /b %ERRORLEVEL%
