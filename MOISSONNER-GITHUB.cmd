@echo off
setlocal
cd /d "%~dp0"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

REM ==================================================================================
REM   MOISSONNEUR GITHUB - UN LANCEUR, UN SCRIPT, DEUX PHASES ENCHAINEES
REM
REM   IMPORTANT : ce fichier est en ASCII PUR. Pas d'accent, pas de tiret cadratin,
REM   pas de guillemets francais. Avec chcp 65001, cmd.exe DECALE son analyseur sur
REM   les caracteres UTF-8 multi-octets : il perd des octets, le REM saute, et il
REM   tente d'EXECUTER les commentaires. Bug reel, constate le 2026-07-12.
REM
REM   ------------------------------------------------------------------------------
REM   PHASE 1 - RATISSER (budget de temps : cherche sans s'arreter)
REM   ------------------------------------------------------------------------------
REM     53 sujets x 5 tranches d'etoiles + 16 requetes en TEXTE LIBRE = 281 requetes.
REM     100 repos par page (le maximum autorise).
REM
REM     POURQUOI DES TRANCHES D'ETOILES : l'API GitHub PLAFONNE a 1000 resultats par
REM     requete. Chercher plus longtemps sur la meme requete ne rend RIEN de plus.
REM     En partitionnant (stars:5..20, 21..60, 61..200, 201..800, plus de 800),
REM     chaque tranche a son PROPRE quota de 1000. Couverture x5.
REM
REM     POURQUOI DU TEXTE LIBRE : beaucoup d'excellents repos n'ont AUCUN topic.
REM     Les chercher par topic seul, c'est les rater.
REM
REM     Tri AUTOMATIQUE, sur les pieges REELS rencontres :
REM       LICENCE      MIT/Apache = ADAPTABLE, GPL = IDEE SEULEMENT, aucune = INTOUCHABLE
REM       CREDIBILITE  0 etoile, abandonne, promet des rebates qui n'existent pas sur HL,
REM                    mauvais marche, forks x3 les etoiles (ferme a airdrop)
REM
REM   ------------------------------------------------------------------------------
REM   PHASE 2 - LIRE SANS LIRE (enchainee automatiquement)
REM   ------------------------------------------------------------------------------
REM     Telecharge les README des repos retenus et les GREPPE sur 13 concepts.
REM     Chacun vient d'un echec DOCUMENTE, pas d'un mot a la mode :
REM
REM       file_attente       notre MM suppose "10 pct du flux" : un chiffre INVENTE
REM       selection_adverse  le maker est rempli quand il a TORT
REM       avellaneda         coter autour d'un prix de reservation, pas du mid
REM       latence_modele     latence du FLUX vs latence des ORDRES
REM       carnet_rejeu       on lit des snapshots, on ne REJOUE rien
REM       impact_marche      l'hypothese qui expliquerait nos -7,97 bps
REM       funding_carry      la seule piste a structure reelle
REM       mempool            le flux d'ordres AVANT execution
REM       liquidation        flux FORCE, previsible depuis l'etat public
REM       biais_backtest     150 M de scenarios sans garde-fou branche
REM       validation_oos     8 garde-fous codes, combien branches ?
REM       protections        global_stop / stop_per_pair : on n'a RIEN
REM       kappa              proba de fill selon la distance au mid : jamais mesure
REM
REM       L'OEIL N'EST PAS EXHAUSTIF. LE GREP L'EST.
REM
REM     Le rapport dit AUSSI quels concepts PERSONNE ne couvre.
REM     Un concept rare, c'est peut-etre la que ca se joue.
REM
REM   ------------------------------------------------------------------------------
REM   USAGE
REM   ------------------------------------------------------------------------------
REM     MOISSONNER-GITHUB.cmd                  5 min de ratissage, PUIS le grep
REM     MOISSONNER-GITHUB.cmd --minutes 15     15 min de ratissage
REM     MOISSONNER-GITHUB.cmd --sans-concepts  ratisser seulement
REM     MOISSONNER-GITHUB.cmd --phase2-seule   grepper la recolte precedente
REM     MOISSONNER-GITHUB.cmd --min-concepts 2 seuil plus permissif
REM
REM     set GITHUB_TOKEN=ghp_...               (lecture seule) TRIPLE la moisson
REM
REM     Ctrl-C a tout moment : on trie et on ecrit ce qui a ete recolte.
REM
REM   UN REPO BIEN CLASSE N'EST PAS UNE IDEE QUI MARCHE.
REM   C'est un repo dont on peut PROUVER qu'il merite une heure humaine.
REM
REM   100 pct LECTURE SEULE. Aucun clone, aucun code execute, aucun ordre. JAMAIS.
REM ==================================================================================

python tools\moissonner_github.py %*

echo.
echo   ------------------------------------------------------------------
echo     data\reports\github_moisson.json    la recolte, triee
echo     data\reports\github_concepts.json   qui touche QUOI, avec la PREUVE
echo   ------------------------------------------------------------------
echo.
pause
