@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   VERDICT-T1 - le verdict qui FAIT FOI.
REM   ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py).
REM
REM   POURQUOI CE FICHIER EXISTE
REM     Le processus d'ecoute a charge le code Python A SON DEMARRAGE (21h28). Les
REM     correctifs ecrits APRES (fenetre continue, tolerance d'horizon, bornes de file)
REM     ne sont PAS dans ce processus. Le verdict qu'il imprimera tout seul a la fin
REM     serait calcule avec l'ANCIEN moteur -- celui qui mesurait a travers les trous.
REM
REM     CE script relit les MEMES fichiers avec le code CORRIGE. C'est lui la verite.
REM
REM   ON PEUT LE LANCER A TOUT MOMENT : il calcule sur ce qui est DEJA capte.
REM   Un marche qui a assez de flux rend son verdict tout de suite. Les autres disent
REM   honnetement qu'ils n'en ont pas assez -- et c'est une reponse, pas une panne.
REM
REM   Lecture seule. Aucun ordre, aucune cle, aucune signature.
REM ==================================================================================
echo.
echo =============================================================
echo   VERDICT T1 - sur toute la donnee deja captee
echo =============================================================
echo.
echo   [1/2] Les tests du moteur (il doit etre sain AVANT de trancher)
python -m pytest -q --tb=short -p no:cacheprovider ^
  tests\test_market_making_bornes_de_file.py ^
  tests\test_market_making_flow.py ^
  tests\test_verifier_ecoute.py
echo.
echo   [2/2] Le verdict
python tools\mesurer_flux_market_making.py --verdict-seulement --inclure KAITO
echo.
pause
