@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"

REM ==================================================================================
REM   MOISSONNEUR GITHUB v3 - RATISSER, TRIER SUR LA SUBSTANCE, PUIS **LIRE LE CODE**
REM
REM   IMPORTANT : ASCII PUR. Pas d'accent, pas de tiret cadratin, pas de guillemets
REM   francais. Avec chcp 65001, cmd.exe DECALE son analyseur sur les caracteres UTF-8
REM   multi-octets : il perd des octets, le REM saute, il tente d'EXECUTER les
REM   commentaires. Bug REEL, constate le 2026-07-12.
REM
REM   ================================================================================
REM   LES 3 DEFAUTS QUE LA v3 CORRIGE - MESURES, PAS SUPPOSES
REM   ================================================================================
REM
REM   [1] IL PERDAIT DES REPOS **EN SILENCE** - dont LE MEILLEUR DU CORPUS.
REM       L'ancienne version ne tentait que  README.md  sur  main/master.
REM       -> 235 repos perdus, dont :
REM            nkaz001/hftbacktest  4270 etoiles  **NOTRE CIBLE N.1**
REM            backtrader 22413 - zipline 19967 - alphalens - catalyst
REM            19 repos a plus de 1000 etoiles
REM       Et l'erreur etait AVALEE : comptee comme "README vide", pas comme
REM       "JE N'AI PAS SU LE LIRE".
REM       -> v3 : l'API /repos/{o}/{r}/readme resout nom + extension + branche.
REM          Repli sur 11 noms x 5 branches. Et si ca echoue, **ELLE LE DIT**.
REM
REM   [2] LE TRI MESURAIT LA **VERBOSITE**, PAS LA SUBSTANCE.
REM       Mesure sur les 5617 repos :
REM            n_concepts = 0   -> mediane  15 etoiles
REM            n_concepts = 12  -> mediane   5 etoiles       ANTI-CORRELE.
REM       Le champion (12/13 concepts) a 5 etoiles et un README qui RECITE le
REM       catalogue du metier. Le grep recompensait celui qui cite le plus de mots.
REM       -> v3 note sur 3 signaux qu'un README bavard NE PEUT PAS SIMULER :
REM            FORMULES   citer "Avellaneda" est gratuit ; poser
REM                       lambda(d) = A * exp(-kappa*d) veut dire qu'on a CALCULE.
REM            AVEUX      le signal le PLUS FORT. "not a substitute for real VPIN".
REM                       Dans un corpus ou TOUT LE MONDE promet de l'alpha,
REM                       **avouer une limite est la seule signature de l'honnetete**.
REM            CHIFFRES   "ameliore le PnL" est gratuit. "-7,97 bps sur 24133
REM                       signaux OOS" engage celui qui l'ecrit.
REM       Et les ETOILES pesent peu : les 4 repos les plus exactement sur cible
REM       avaient **1, 2, 3 et 3 etoiles**.
REM
REM   [3] IL NE LISAIT JAMAIS LE **CODE**. Il s'arretait au README = la page de vente.
REM       LE CHIFFRE QUI TRANCHE :
REM            8 passes de tri sur 5617 repos  ->  **3 idees**
REM            20 min a lire le code d'UN repo ->  **5 bugs** dans notre simu
REM       ***TRIER NE REMPLACERA JAMAIS LIRE.***
REM       -> v3 PHASE 3 : ouvre l'arbre du repo, choisit les fichiers dont le CHEMIN
REM          annonce nos sujets, telecharge la source et la GREPPE.
REM          Livrable : **repo - fichier - LIGNE - le code - POURQUOI**.
REM          Pas un classement. **Une liste de lecture.**
REM
REM   ================================================================================
REM   LES 3 PHASES
REM   ================================================================================
REM     PHASE 1  RATISSER      53 sujets x 5 tranches d'etoiles + 16 requetes libres.
REM                            Les tranches contournent le plafond de 1000 resultats
REM                            de l'API : chaque tranche a son PROPRE quota.
REM     PHASE 2  GREPPER       les README (recuperes par l'API, enfin) sur 13 concepts,
REM                            chacun issu d'un echec DOCUMENTE de notre bot.
REM     PHASE 3  LIRE LE CODE  <<< LA NOUVEAUTE. La seule etape qui ait jamais donne
REM                            quelque chose.
REM
REM   ================================================================================
REM   USAGE
REM   ================================================================================
REM     MOISSONNER-GITHUB.cmd                   5 min de ratissage, puis grep, puis CODE
REM     MOISSONNER-GITHUB.cmd --minutes 15      15 min de ratissage
REM     MOISSONNER-GITHUB.cmd --sans-concepts   ratisser seulement
REM     MOISSONNER-GITHUB.cmd --phase2-seule    grepper la recolte precedente
REM     MOISSONNER-GITHUB.cmd --lire-seulement  SAUTER la moisson, LIRE LE CODE
REM                                             (utile : la moisson de 5617 est deja faite)
REM
REM     set GITHUB_TOKEN=ghp_...                (lecture seule) 60/h -> 5000/h
REM                                             **La phase 3 en a vraiment besoin.**
REM
REM     Ctrl-C a tout moment : on trie et on ecrit ce qui a ete recolte.
REM
REM   UN REPO BIEN CLASSE N'EST PAS UNE IDEE QUI MARCHE.
REM   C'est un repo dont on peut PROUVER qu'il merite vingt minutes de lecture.
REM
REM   100 pct LECTURE SEULE. Aucun clone. AUCUN CODE TELECHARGE N'EST EXECUTE. JAMAIS.
REM ==================================================================================

REM  ================================================================================
REM   PAR DEFAUT : LE RUN DE 10 HEURES. Les 15 idees, cablees.
REM
REM   #1  LE CANARI          AVANT TOUT. Si le trieur ne retrouve pas ce qu'on SAIT
REM                          bon, LE RUN S'ARRETE et ne rend AUCUN verdict.
REM                          Un outil qui echoue sur ce qu'il connait n'a rien a
REM                          dire sur ce qu'il ne connait pas.
REM   #2  les COMMITS        les bugs que d'autres ont DEJA PAYES
REM   #3  le DIFFERENTIEL    on note le DELTA, pas le niveau
REM   #4  les ISSUES         des aveux INVOLONTAIRES
REM   #5  les TESTS          la carte des PEURS de l'auteur
REM   #6  les CONSTANTES     du calibrage gratuit
REM   #7  le CACHE BRUT      re-juger HORS LIGNE, en 10 secondes
REM   #8  la DEDUP par code  ne pas lire 30 fois le meme bot
REM   #9  le BANDIT          une ressource rare se pilote
REM   #10 les CITATIONS      une etoile est un clic ; une citation est un choix
REM   #11 les AUTEURS        les gens sont plus constants que les projets
REM   #12 la REPRODUCTIBILITE un backtest qu'on ne peut pas rejouer est une
REM                          AFFIRMATION, pas une preuve
REM   #13 la CHRONOLOGIE     les repos nes juste apres un changement de protocole
REM   #14 la CONTRADICTION   chercher ce qui nous donne TORT
REM   #15 les ZONES VIERGES  ce que PERSONNE ne fait
REM
REM   IL NE MEURT JAMAIS -- ET IL NE MENT JAMAIS.
REM     quota      -> on ATTEND et on reessaie a l'infini
REM     reseau     -> backoff + jitter, borne, puis on passe ET ON COMPTE
REM     exception  -> chaque phase est ISOLEE : une phase qui casse ne tue pas le run
REM     Ctrl-C     -> checkpoint apres CHAQUE requete, on reprend EXACTEMENT la
REM     mensonge   -> chaque blessure est COMPTEE et PUBLIEE
REM
REM   Pour regarder sans interrompre : ouvrir  moisson-en-cours.txt
REM
REM   USAGE :
REM     MOISSONNER-GITHUB.cmd                  10 heures (defaut)
REM     MOISSONNER-GITHUB.cmd --heures 2       2 heures
REM     MOISSONNER-GITHUB.cmd --repartir-de-zero
REM     MOISSONNER-GITHUB.cmd --ancien-scan    l'ancien pipeline (rien n'est supprime)
REM
REM     set GITHUB_TOKEN=ghp_...   gratuit, lecture seule.
REM     SANS LUI : 60 req/h au lieu de 5000, et la recherche DANS LE CODE est
REM     IMPOSSIBLE. Le moissonneur le DIT au lieu de faire semblant.
REM  ================================================================================

if /I "%~1"=="--dossier-seul" goto :dossier
if /I "%~1"=="--lire-seulement" goto :lire
if /I "%~1"=="--ancien-scan" goto :ancien
if /I "%~1"=="--phases" goto :phases

python tools\moissonner_10h.py %*
echo.
echo   ------------------------------------------------------------------
echo     moisson-fini.md            ^<^<^< LE LIVRABLE (racine)
echo     moisson-en-cours.txt        le battement (pendant le run)
echo     data\reports\moisson_10h.json
echo   ------------------------------------------------------------------
echo.
pause
exit /b 0

:phases

echo.
echo   ==================================================================
echo     PHASE 1 - LE SCAN v5
echo
echo     [1] Il descend jusqu'a ZERO etoile. L'ancien s'arretait a 5.
echo         Or les 4 repos les plus EXACTEMENT sur cible avaient
echo         1, 2, 3 et 3 etoiles. Le scan ecartait A L'ENTREE le
echo         profil qu'on a MESURE comme le meilleur.
echo     [2] Il partitionne par DATE : le plafond de 1000 resultats
echo         tombe (24 tranches = 24 000 resultats par sujet).
echo     [3] Il cherche DANS LE CODE (/search/code) : un repo sans
echo         topic, sans etoile, au README muet, mais dont le CODE
echo         contient qty_ahead ou exp(-kappa.
echo         LE README EST LA PAGE DE VENTE. LE CODE EST LA VERITE.
echo     [4] Il est REPRENABLE : Ctrl-C / quota / coupure -^> on
echo         reprend exactement ou on s'etait arrete.
echo   ==================================================================
python tools\moissonner_scan.py %*
goto :lire

:ancien
python tools\moissonner_github.py %*
if errorlevel 1 goto :fin

:lire
echo.
echo   ==================================================================
echo     PHASE 3 - LIRE LE CODE  (trier ne remplacera jamais lire)
echo   ==================================================================
python tools\moissonner_lire_le_code.py

echo.
echo   ==================================================================
echo     PHASE 3bis - LES AUTRES SOURCES
echo
echo     arXiv (LA SOURCE DES FORMULES, gratuite, relue par des pairs)
echo     Hacker News (quelqu'un vient TOUJOURS dire pourquoi ca rate)
echo     quant.stackexchange (les reponses y sont NOTEES et CONTESTEES)
echo     X / Twitter -- SEULEMENT si X_BEARER_TOKEN est fourni.
echo                    L'API X est PAYANTE. Sans jeton : INDISPONIBLE,
echo                    et on le DIT. On ne fait pas semblant de chercher.
echo
echo     LE MEME FILTRE PARTOUT. Il ne demande pas D'OU ca vient, il
echo     demande CE QUE CA PROUVE :
echo       "+300 pct cette semaine"        -^>  score NEGATIF, ecarte
echo       "on a perdu, voici la formule"  -^>  garde
echo     Biais du survivant : tu vois celui qui a gagne, jamais les
echo     mille qui ont perdu avec la meme methode.
echo   ==================================================================
python tools\moissonner_sources.py

:dossier
echo.
echo   ==================================================================
echo     PHASE 4 - LE DOSSIER  --^>  moisson-fini.md  (a la racine)
echo
echo     Il suit le GRAPHE : awesome-lists (200 repos SANS topic que la
echo     recherche par topic ne verra JAMAIS), dependances, sources citees.
echo     Il CLASSE, il dit OU BRANCHER chez nous, et il ecrit un PLAN
echo     D'ACTION avec, pour chaque tache : le POURQUOI, l'APPORT, le
echo     COMMENT et le CRITERE DE FIN. Plus une CHECKLIST globale.
echo   ==================================================================
python tools\moisson_finale.py

:fin
echo.
echo   ------------------------------------------------------------------
echo     moisson-fini.md                           ^<^<^< LE LIVRABLE (racine)
echo     data\reports\moisson_finale.json           le meme, en machine
echo     data\reports\LISTE_DE_LECTURE.md           les lignes a ouvrir
echo     data\reports\github_moisson.json           la recolte brute, triee
echo     data\reports\github_concepts.json          qui touche QUOI, avec la PREUVE
echo   ------------------------------------------------------------------
echo.
pause
