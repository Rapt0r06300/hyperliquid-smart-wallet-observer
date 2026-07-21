# Outils de test & rapports

> **Cet index est GENERE** par `tools/ranger_racine.py` a partir des en-tetes `REM` de
> chaque script. *Un index ecrit a la main ment des la premiere modification.*
> Pour le regenerer : **`RANGER-LA-RACINE.cmd`** (a la racine).

## 🔑 Par ou commencer

**`TOUT-VERIFIER.cmd`** — le point d'entree **unique**. Il enchaine les 8 verifications
qui disent encore quelque chose aujourd'hui. Les rapports atterrissent dans `rapports/`.

*Je n'ai pas fusionne les 100 scripts : la plupart sont des **enquetes closes**. Les
relancer toutes prendrait des heures pour un mur de texte sans valeur.*
***Un script qui fait tout ne dit plus rien.***

## Comment ils marchent

Double-clic. Chaque script **remonte tout seul** a la racine du projet
(`cd /d "%~dp0.."`) et ecrit sa sortie dans **`rapports/`**.

🔒 Tous sont en **lecture seule / paper-only**. Aucun n'envoie d'ordre reel.

## Restes a la racine (ne PAS deplacer)

| script | pourquoi |
|---|---|
| `LANCER_HYPERSMART.cmd` | le **runtime** de la simulation |
| `LANCER-TOUT.cmd` | la chaine **carry** complete (scanner -> noyau -> PaperIntent) |
| `TEST-AUDIT-complet.cmd` | l'audit — **CLAUDE.md le designe a la racine** |
| `MOISSONNER-GITHUB.cmd` | **le moissonneur** — depose dans `runtime/research/github_repos_v24/` |

---

## ✅ Les 8 outils VIVANTS (lances par `TOUT-VERIFIER.cmd`)

| script | ce qu'il fait |
|---|---|
| `CHECK-SAFETY.cmd` | SECURITE : 0 ordre reel, 0 cle, 0 signature |
| `VERIFIER-BRANCHEMENTS.cmd` | les garde-fous sont-ils DANS la porte ? (audit AST) |
| `LES-LEVIERS.cmd` | tous les leviers pour ouvrir plus -- calcules, pas opines |
| `LA-PROFONDEUR.cmd` | le carnet porte-t-il notre taille ? (4 jambes) |
| `LE-VERDICT.cmd` | nos carrys battent-ils un depot passif dans HLP ? |
| `COUVERTURE-LIGNES.cmd` | la couverture REELLE des tests |
| `VERIFIER-TASKLIST.cmd` | l'etat des taches |
| `CONSULTER-MEMOIRE.cmd` | ce que le projet a appris |

---

## 📦 Les 92 enquetes CLOSES

*Elles ont servi une fois, elles ont rendu leur verdict. **On ne les supprime pas** —
elles sont la preuve de ce qui a ete mesure. Mais on ne les relance pas en routine.*

| script | ce qu'il faisait |
|---|---|
| `ANALYSER-599.cmd` | #599 -- ou vivent les 16 % de lignes jamais executees ? — + #591 -- le garde-fou AFFAME (l'estimateur de vol n'etait nourri que si une |
| `BACKFILL-CANDLES.cmd` | BACKFILL D'HISTORIQUE -- « data-limited » etait une blessure AUTO-INFLIGEE. — `candleSnapshot(coin, interval, startTime, endTime)` etait DEJA ecrit, D |
| `BACKFILL-PROFOND.cmd` | LA VRAIE PROFONDEUR. — Hyperliquid plafonne `candleSnapshot` a ~5 000 bougies par coin, quel que soit le |
| `CHECK-112-121.cmd` | #112 : la latence des REFUS (fin du biais de survivant dans l'instrumentation). — #121 : le cliquet de couverture -- le nombre de modules non testes n |
| `CHECK-127.cmd` | #127 IMPROVE-20 : le regime, sans lire le futur. — + non-regression sur les gates de validation et la recherche de scenarios. |
| `CHECK-130-131.cmd` | 131 : la CAPACITE d'executer un ordre reel n'est PAS installee. — 130 : une pierre tombale ne peut citer qu'un remplacant VIVANT. |
| `CHECK-145.cmd` | #145 : le panneau d'arbitrage affichait un spread INVENTE sans le dire. — ASCII PUR, pas de pause -> "%~dp0rapports\check_145.txt" |
| `CHECK-3-ROUGES.cmd` | 3 tests rouges vus par la suite COMPLETE (sous coverage). Sont-ils A MOI ? — ASCII PUR, pas de pause -> "%~dp0rapports\check_3_rouges.txt" |
| `CHECK-304.cmd` | QUI est le 304e module mort ? On ne releve pas le plafond, on l'identifie. — ASCII PUR, pas de pause -> "%~dp0rapports\check_304.txt" |
| `CHECK-586-598.cmd` | #586 (H-181) : le bug de signe est-il corrige ? + la mesure REJOUEE. — #598          : QUI refuse le cluster frais ? (on LIT le motif) |
| `CHECK-591-599.cmd` | #591 -- le GARDE-FOU AFFAME : l'estimateur de vol n'etait nourri que si une — position etait DEJA ouverte -- alors que le veto d'ENTREE le consomme. |
| `CHECK-593-FULL.cmd` | T3e (#593) -- SUITE COMPLETE + SAFETY. La suite ciblee cache des rouges : — c'est la lecon de G2 (8 rouges) et du 13/07 (3 rouges). ASCII PUR, pas de  |
| `CHECK-593.cmd` | T3e (#593) -- P4/P5 : le coeur n'est appele par PERSONNE. — L'invariant « brancher ou enterrer » etendu a runtime/. |
| `CHECK-594-COMPLET.cmd` | #594 -- LA SUITE COMPLETE. Une sous-suite verte a deja cache 8 rouges (G2, 13/07). — ASCII PUR, pas de pause -> "%~dp0rapports\check_594_complet.txt" |
| `CHECK-594.cmd` | #594 / #310 -- UNE SEULE PORTE D'EDGE, et plus aucune re-ponderation d'une mesure. — ASCII PUR, pas de pause -> "%~dp0rapports\check_594.txt" |
| `CHECK-595-596.cmd` | #595 : le regime est BRANCHE dans la recherche (causal, seuil du TRAIN seul). — #596 : la VRAIE couverture -- celle des LIGNES executees. |
| `CHECK-595.cmd` | #595 : le regime est BRANCHE dans la recherche (causal, seuil du TRAIN seul). — Rapide. La couverture de lignes (#596) est dans COUVERTURE-LIGNES.cmd  |
| `CHECK-597.cmd` | #597 -- la porte des OUTILS de recherche. Le plafond BAISSE (304 -> 273). — ASCII PUR, pas de pause -> "%~dp0rapports\check_597.txt" |
| `CHECK-598-FIX.cmd` | #598 -- les 2 tests UI exigeaient un edge INVENTE. On leur donne une VRAIE mesure, — et on verrouille l'invariant : SANS mesure, le bot REFUSE. |
| `CHECK-600.cmd` | #600 -- os.kill(pid, 0) EST UN CTRL-C SOUS WINDOWS (signal 0 == CTRL_C_EVENT). — LA PREUVE : si ce fichier contient les 3 sections JUSQU'A "FIN", le C |
| `CHECK-601.cmd` | #601 -- les 5 rouges que la suite COMPLETE a enfin criees (le Ctrl-C la coupait — a 70 %, donc 1270 tests n'avaient JAMAIS tourne). |
| `CHECK-COHERENCE.cmd` | L'INCOHERENCE VUE PAR FLO : le registre refusait sur des MOTS-CLES. — Une zone morte doit declarer l'ENTREE qu'elle a mesuree. |
| `CHECK-CROSS-VENUE.cmd` | #365 / H-137 -- FUNDING CROSS-VENUE (HL <-> Binance <-> Bybit, MEME coin) — ⚠️ LE PIEGE : la 1re version annoncait **38 %% APR** sur l'exemple de la d |
| `CHECK-CTRLC.cmd` | L'INVARIANT anti-Ctrl-C : un outil qui lance pytest ne doit pas mourir de son — Ctrl-C. Rapide. ASCII PUR, pas de pause -> "%~dp0rapports\check_ctrlc. |
| `CHECK-DATA.cmd` | 1. BACKFILL 30 jours d'historique (candleSnapshot -- deja ecrit, jamais utilise) — 2. SUITE COMPLETE + SAFETY |
| `CHECK-FINAL.cmd` | 1) QUI est le 304e module mort ? (on ne releve pas le plafond, on l'identifie) — 2) Le defaut SL/TP n'est plus une perte garantie |
| `CHECK-H.cmd` | H-05 (#410) + H-30 (#435) : la coupe train/test FUYAIT (aucune purge, aucun embargo). — Purge + embargo branches dans les DEUX chemins de scenario_sea |
| `CHECK-H160.cmd` | Verification complete apres H-160 / GH-02 (sonde de biais recursif). — ASCII PUR, pas de pause -> "%~dp0rapports\check_h160.txt" |
| `CHECK-IDEA.cmd` | Lot IDEA -- SUITE COMPLETE + SAFETY. La suite ciblee cache des rouges (lecon G2). — ASCII PUR, pas de pause -> "%~dp0rapports\check_idea.txt" |
| `CHECK-M19.cmd` | #395 / M-19 -- les 7 garde-fous ANTI-OVERFIT etaient TOUS MORTS. — Le gate de deflation est branche dans les DEUX chemins de scenario_search. |
| `CHECK-P.cmd` | LOT P* -- #292 (le panneau de securite mentait) + #318 (la fraicheur etait fabriquee) — SUITE COMPLETE + SAFETY. ASCII PUR, pas de pause -> "%~dp0rapp |
| `CHECK-T1B.cmd` | #587 / T1b -- coter DANS le spread : la derniere porte ouverte du market making. — Mesure + suite COMPLETE + safety. ASCII PUR, pas de pause -> "%~dp0 |
| `CHECK-X.cmd` | X-04 (#365) : funding arb PERP<->PERP -- la voie de reouverture DESIGNEE. — X-11 (#372) : la carte des liquidations (liquidationPx qu'on JETAIT). |
| `COLLECTER-DEPOTS.cmd` | #362 / X-01 -- depots Arbitrum -> Hyperliquid. LECTURE ON-CHAIN SEULE. — L'ADRESSE DU PONT, **VERIFIEE SUR LA DOC OFFICIELLE** (2026-07-13) : |
| `CREER_ARCHIVE_PROPRE.cmd` | _(sans en-tete REM)_ |
| `DEBUG-NOYAU.cmd` | Pourquoi le noyau refuse-t-il le carry ? On lui demande sa PREUVE. — ASCII PUR, pas de pause -> "%~dp0rapports\debug_noyau.txt" |
| `DIAG-598.cmd` | #598 -- QUI refuse le cluster frais ? On LIT le motif, on ne le devine pas. — ASCII PUR, pas de pause -> "%~dp0rapports\diag_598.txt" |
| `DIAG-BORNES.cmd` | DIAG-BORNES - diagnostic JETABLE. ASCII PUR, pas de "chcp". — Ecrit le resultat dans diag_bornes.txt pour qu'il soit relisible. |
| `DIFF-CABLAGE.cmd` | Pourquoi le nombre de modules MORTS a-t-il bouge ? On MESURE, on ne devine pas. — ASCII PUR, pas de "chcp". Sans pause : tout va dans diff_cablage.txt |
| `ECOUTER-FLUX-4H.cmd` | T1 - TRANCHER KAITO : 4 h d'ecoute du canal PUBLIC `trades`. — ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py). |
| `ETAT-112-145.cmd` | ETAT REEL des 8 taches #112 -> #145. Prouve par EXECUTION, jamais par lecture. — ASCII PUR, pas de "chcp", pas de pause -> "%~dp0rapports\etat_112_145 |
| `FALSIFIER-CASHCAT.cmd` | FALSIFIER-CASHCAT - essayer de DETRUIRE le seul candidat positif du projet. — ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py). |
| `FINIR-CROSS-VENUE.cmd` | FINIR LA PARTIE FUNDING (2026-07-13) — 1. TESTS des 2 nouveaux modules (dont l'anti-regression du piege d'unite 8h/1h) |
| `FINIR-H90-H180.cmd` | #495-#585 (H-90 a H-180) -- 91 taches. **L'OR ETAIT DANS NOTRE CODE.** — 🎯 #543 -- LE NOMBRE LE PLUS IMPORTANT DU PROJET : |
| `FINIR-LES-BUGS.cmd` | LES BUGS REELS DES 91 TACHES (H-90 a H-180) -- executes, pas classes. — #543  FRAIS : 6 valeurs eparpillees (2.5 / 4.0 / 4.5 / 6.0) -> source unique. |
| `FINIR-LOT.cmd` | LOT #242 / #249 / #250 / #251 / #254 — 1. cointegration MESUREE sur donnees reelles (#242) |
| `FINIR-TOUS-LES-BUGS.cmd` | LES 8 BUGS REELS DES 91 TACHES -- TOUS EXECUTES (2026-07-13) — #543  FRAIS : 6 valeurs eparpillees (2.5/4.0/4.5/6.0) -> source unique + cliquet. |
| `FINIR-TOUT.cmd` | FINIR TOUT (2026-07-13) -- funding + archive S3 + triage H-46..H-89 — 🔒 DECISION DE FLO : **RIEN DE PAYANT.** |
| `G1-LOOKAHEAD.cmd` | G1 - LA RECHERCHE 150 M LIT-ELLE LE FUTUR ? — Test DIFFERENTIEL : on TORTURE les donnees, on ne lit pas le code. |
| `G2-NOYAU.cmd` | G2 - LE NOYAU UNIQUE. Un seul endroit decide, et il POSSEDE l'edge. — + l'invariant : aucun module de production ne FABRIQUE un edge d'entree. |
| `G2-REGRESSION.cmd` | G2 - LA SUITE COMPLETE. Le noyau touche 5 fichiers de production : il faut — prouver qu'il n'a rien casse ailleurs. ASCII PUR, pas de pause -> "%~dp0r |
| `GH01-INTERRUPTEURS.cmd` | GH-01 - L'INVARIANT SUR LES INTERRUPTEURS (celui qui manquait depuis le debut). — + le CLIQUET de cablage : le nouveau module ne doit pas etre MORT. |
| `H181-MESURE.cmd` | H-181 (#586) -- LA MESURE SUR LES VRAIES DONNEES, SEULE. — Le 13/07 a 14:20, cette mesure est morte sur un "^C" -- exactement le bug du |
| `H181-VAINQUEUR.cmd` | H-181 - LE TOP-40 DE LA RECHERCHE EST-IL DISCERNABLE DU HASARD ? — Controle par PERMUTATION : meme espace, meme couts, mais SANS edge. |
| `IMPROVE-130-131.cmd` | #131 -- la CAPACITE d'executer un ordre reel n'est PAS installee. — #130 -- une pierre tombale ne peut citer qu'un remplacant VIVANT (joignable + allu |
| `LANCER-LE-CARRY.cmd` | LE CARRY — **LA SEULE STRATEGIE MESUREE POSITIVE DU PROJET.** — Sur ~600 idees, UNE SEULE a survecu a la falsification : |
| `LISTER-RESTE.cmd` | Extrait TOUTES les taches non cochees de TASKLIST.md -> "%~dp0rapports\RESTE-A-FAIRE.txt" — ASCII PUR, pas de pause. |
| `MEGATEST.cmd` | MEGATEST - LES 7 CONTROLES HYPERSMART EN UN SEUL PASSAGE — IMPORTANT : ce fichier est en ASCII PUR, et il n'y a PAS de "chcp". |
| `MESURER-3-PISTES.cmd` | LES 3 DERNIERES PISTES (2026-07-13) — #517 -- LE MM SUR HIP-3. **La SEULE reouverture legitime** : ma zone morte prevoit |
| `MESURER-588.cmd` | T2b (#588) -- la jambe perp du carry HYPE peut-elle etre LIQUIDEE ? — Lecture seule (endpoint /info public). ASCII PUR, pas de pause -> "%~dp0rapports |
| `MESURER-597.cmd` | #597 -- la porte que l'audit ne voyait pas : les OUTILS de recherche. — ASCII PUR, pas de pause -> "%~dp0rapports\mesure_597.txt" |
| `MESURER-599.cmd` | #599 -- RE-MESURER la couverture sur la suite COMPLETE. — Celle du 13/07 14:07 (83,83 %) a ete calculee sur une suite TRONQUEE a 70 % par |
| `MESURER-CARRY-NEUTRE.cmd` | _(sans en-tete REM)_ |
| `MESURER-CROSS-VENUE.cmd` | #365 / H-137 -- FUNDING CROSS-VENUE, SUR LE **MEME COIN**. — X-04 a tue le perp<->perp entre coins DIFFERENTS (0/120). |
| `MESURER-FLUX-MM.cmd` | _(sans en-tete REM)_ |
| `MESURER-H160.cmd` | H-160 / GH-02 -- LE BIAIS RECURSIF : nos features changent-elles selon la — QUANTITE d'historique fournie ? (backtest = tout ; live = buffer borne) |
| `MESURER-SPREAD-CARNET.cmd` | _(sans en-tete REM)_ |
| `MESURER_SEUIL_FUNDING.cmd` | LE SEUIL D'ENTREE DU GRINDER EST-IL ATTEIGNABLE ?  (2026-07-11) — Le funding-arb (la seule strategie "grinder" cablee) n'a JAMAIS trade. Son verrou d' |
| `PAGE-KAITO.cmd` | PAGE-KAITO - la progression de T1, en direct. — ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py). |
| `POURQUOI-CA-CASSE.cmd` | POURQUOI CA CASSE - relance UNIQUEMENT les tests en echec, et les regroupe — par CAUSE RACINE. |
| `POURQUOI-ZERO-POSITION.cmd` | _(sans en-tete REM)_ |
| `Q1-TABLE-EDGE.cmd` | Q1 - LA TABLE D'EDGE MESUREE. L'edge brut ne vient plus d'une formule inventee. — 1. mesure le MARKOUT REEL de chaque signal enregistre (ce que le pri |
| `Q2-JAMBES.cmd` | Q2 - L'ARBITRAGE SE JUGE SUR DES JAMBES EXECUTABLES, JAMAIS SUR LE MID. — Tests de Q2 + les suites qui touchent l'arbitrage et le carnet (non-regressi |
| `Q2-MESURE.cmd` | Q2 - MESURE SUR LES VRAIS CARNETS ENREGISTRES. — Le bug d'extrapolation a-t-il deja menti ? De combien le mid ment-il ? |
| `Q3-AVANT-APRES.cmd` | Q3 - LE PRIX AVAIT-IL DEJA BOUGE AVANT QUE LE FILL SOIT PUBLIC ? — La CAUSE mecanique du "pas d'edge en copy-trading". Markout de T-300s a T+300s. |
| `Q3-TESTS.cmd` | Q3 + Z1 - LA ZONE MORTE EST DANS LE CODE, PAS SEULEMENT DANS UN .MD. — + le CLIQUET de cablage : un nouveau module MORT doit faire ECHOUER la suite. |
| `REFAIRE-242.cmd` | #242 REFAIT SUR **208 JOURS** (au lieu de 18,9 h). — Il etait mort « data-limited ». On avait l'historique a un appel de distance. |
| `SONDER-ARCHIVE-S3.cmd` | #462 / H-57 -- L'ARCHIVE S3 OFFICIELLE HYPERLIQUID — 🔴 J'AI AFFIRME 3 FOIS que le carnet L2 et les trades n'avaient AUCUNE source |
| `SUIVRE-MEGATEST.cmd` | OBSERVATEUR DU MEGATEST - a lancer dans une 2e fenetre, PENDANT que le test tourne. — ASCII PUR, pas de chcp : un octet non-ASCII ferait executer les  |
| `T2-CARRY.cmd` | T2 - LE CARRY DELTA-NEUTRE : la jambe SPOT existe-t-elle seulement ? — ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py). |
| `T2-FALSIFIER.cmd` | T2-FALSIFIER - essayer de DETRUIRE le carry delta-neutre avant d'y croire. — ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py). |
| `T2-TEST.cmd` | T2-TEST - le moteur du carry doit etre sain AVANT de trancher. — ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py). |
| `T3-CABLAGE-NOPAUSE.cmd` | T3 - AUDIT DE CABLAGE, version SANS PAUSE (le cmd est tier-click : on ne peut pas — lui envoyer de touche, un `pause` bloquerait la boucle). |
| `T3-CABLAGE.cmd` | T3 - AUDIT DE CABLAGE : "qui appelle ce module ?" — ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py). |
| `T3B-CABLAGE.cmd` | T3B - meme audit que T3-CABLAGE, mais SANS pause : tout va dans t3_cablage.txt. — ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py). |
| `T3B-GARDES.cmd` | T3b - BRANCHER ou ENTERRER les 21 gardes-fous de risk/. Rien dans l'entre-deux. — ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py). Sans pause  |
| `T3D-PROUVER.cmd` | T3d - Le hot path P4/P5 est-il VRAIMENT mort ? Preuve par EXECUTION. — ASCII PUR, pas de "chcp". Sans pause : tout va dans t3d_preuve.txt. |
| `TEST-EDGE.cmd` | TEST-EDGE - le cablage de l'edge mesure (Q1), plus les tests qu'il debloque. — ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py). |
| `TEST-T1.cmd` | TEST-T1 - le moteur de verdict SANS le nombre invente. — ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py). |
| `VERDICT-T1.cmd` | VERDICT-T1 - le verdict qui FAIT FOI. — ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py). |
| `VERIFIER-ECOUTE.cmd` | VERIFIER-ECOUTE - chercher la panne AVANT qu'elle ne coute la nuit. — ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py). |
| `VERIFIER-LE-CARRY.cmd` | VERIFIER LE CARRY **AVANT** DE CROIRE SES CHIFFRES — sur **365 JOURS**. — 🚩 D'ABORD : JE SUSPECTE MON PROPRE PARSEUR. |

---

*Aucun fichier n'a ete supprime. Chaque script a ete **deplace ET repare** :*
*`cd` remonte a la racine, `PYTHONPATH` pointe sur `src/`, les rapports vont dans*
*`rapports/`. **Sans cette reparation, les 100 scripts auraient tous casse.***
