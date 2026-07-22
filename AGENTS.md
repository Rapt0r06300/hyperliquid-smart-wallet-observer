# AGENTS.md — consignes pour tout agent/IA travaillant sur HyperSmart Observer

> **Dernière mise à jour : 2026-07-22.** Un AGENTS.md périmé est pire que pas d'AGENTS.md : il
> oriente vers la mauvaise cible avec autorité. **Si tu le lis et qu'il contredit
> `docs/ETAT_ET_FEUILLE_DE_ROUTE.md`, c'est l'état qui gagne — et tu mets ce fichier à jour dans
> la foulée.**

## 🏆 ÉTAT D'ESPRIT : GAGNANT (le cap, non négociable)

**L'objectif est un PnL paper POSITIF et un ROI POSITIF. Point.** On y croit, on pousse fort, on
explore TOUTES les pistes, on ne se contente jamais de « ça ne marche pas » — on cherche la piste
suivante. Flo a promis de l'argent à ses parents : cet objectif est sérieux, et on le vise pour
de vrai.

**Ce qui sépare un vrai gagnant d'un joueur qui se ment : le gagnant refuse le faux gain.** Un PnL
maquillé, un edge d'illusion (le +0,54 $ d'arbitrage au mid qui perd −2,7 $ à l'exécution), un
gain sorti d'une baisse de sécurité — tout ça trahirait l'objectif au lieu de le servir. Donc la
règle du gagnant est double et indivisible :

1. **Ambition maximale** : tout est permis pour TROUVER l'edge (collecte massive, univers large,
   nouveaux signaux, backtests, IA). Aucune timidité. « Tout est possible. »
2. **Honnêteté totale** : on ne GARDE un edge que s'il survit aux coûts réels (frais + spread +
   slippage + latence) ET bat l'alternative (cash/HLP), mesuré sur données vraies. Un chiffre ou
   rien. La discipline (tests, no-real-trade, vérité des données) **n'est pas un frein à
   l'objectif — elle EST le chemin** vers un PnL positif qui tient dans la durée.

En cas de doute entre « annoncer un beau chiffre » et « dire la vérité » : **la vérité**, toujours.
Un PnL positif honnête vaut infiniment plus qu'un faux, parce que lui seul se répète.

## Règle n°1 (absolue, non négociable)

**Aucune exécution réelle.** Aucun ordre réel, aucun `/exchange` réel, aucun argent réel,
aucune clé privée, aucun seed/mnemonic, aucune signature réelle, aucun wallet-connect pour
agir, aucun dépôt/retrait, aucun endpoint d'exécution activé.
`READ-ONLY-MAINNET · LOCAL-DECISION · PAPER-ONLY · DENY-BY-DEFAULT`.

Un signal n'est jamais un ordre ; un paper-trade n'est jamais un ordre. Les mots *trade,
order, buy, sell, hedge, arbitrage* sont **autorisés** en test/mock/paper/doc/dashboard :
seule l'**action réelle** est interdite. Donnée incertaine / trop vieille / incomplète →
`NO_TRADE`.

**Tout le reste est autorisé** (décision explicite de Flo, 08/07) : scraping public agressif,
collecte 24/7, multi-sources, backfill massif, toute analyse, tout backtest, toute simulation.

## Où tu travailles (ne pas confondre — c'est la confusion la plus coûteuse du projet)

| chemin | rôle | y toucher ? |
|---|---|---|
| `src/hl_observer/` | **LE runtime actif.** Toute nouvelle idée va ici. | oui |
| `tools/` | collecteurs, feeders, CLI. **Rechargés à chaque passe** → une modif ici est active en ≤ 10 min, sans redémarrage. | oui |
| `hyper_smart_observer/dydx_v4/` | vrai dYdX legacy, pointe `indexer.dydx.trade`. **Ce n'est PAS la simulation.** | non |
| `hyper_smart_observer/` (hors dydx_v4) | legacy/compat isolé | non |

Une modif dans `src/` ne prend effet **qu'au prochain redémarrage** de Flo. Le dire dans le
rapport final, toujours.

## Ne jamais toucher

- la session en cours quand Flo dit qu'elle tourne (lecture seule sur `runtime/`) ;
- `runtime/data/*.jsonl` et `runtime/replay/` : append-only, jamais de réécriture ni de purge ;
- les lanceurs `.cmd` sans vérifier que `cd /d "%~dp0"` reste correct ;
- les très gros fichiers tronqués par le mount (`src/hl_observer/cli.py`, `ui/routes.py`) via
  Write/bash — passer par de petits modules importés ;
- une constante de sécurité (`SECURITE_LIQUIDATION`, plafonds de risque) pour améliorer un
  chiffre : voir « le piège » plus bas.

## Ce qui est DÉJÀ tranché par la mesure

**`docs/LOIS_MESUREES.md`** — 13 verdicts datés, chacun avec le chiffre qui l'a tranché et la
donnée qui justifierait de rouvrir le dossier. Source unique :
`src/hl_observer/research/lois_mesurees.py` (le doc est généré, ne pas l'éditer à la main).

Ne relance pas le copy-trading global, le market-making dans le spread, le lead-lag BTC→alts
ou le funding perp↔perp sans avoir lu la loi correspondante. **Un argument neuf ne suffit
pas : il faut une donnée neuve.** Le registre est branché dans `recherche_scenario` — une
pépite qui retombe sur un mécanisme réfuté affiche le rappel automatiquement.

## Le piège (il s'est produit, il se reproduira)

Presque toutes les façons d'augmenter le PnL affiché reviennent à **prendre plus de risque
sans le mesurer** : baisser `securite_liquidation`, monter le levier, réduire un plancher de
break-even, élargir un seuil. Un backtest sur une fenêtre calme **ne contient pas** la
liquidation qu'on vient de rendre possible — le PnL monte, le risque de ruine aussi, et seul
le premier est mesuré. `carry_backtest.verdict()` **refuse** explicitement ce type de gain.

Le bon levier ressemble toujours à ça : *même risque, mieux placé* (allocation par rendement
net, renfort sans fermeture, plus de données).

## Ordre de travail (les 7 étapes, dans cet ordre)

1. **`git log -1 --date`** — savoir ce qui est committé avant de croire quoi que ce soit ;
2. comprendre l'archi existante (renforcer, ne pas créer une 3ᵉ architecture) ;
3. protéger le travail local (ne rien supprimer brutalement) ;
4. **mesurer avant de proposer** — un chiffre ou rien ;
5. coder proprement, petits modules importables ;
6. **tester** — un nouveau module sans test = échec bloquant (voir plus bas) ;
7. vérifier que le no-real-trade tient, et le dire dans le rapport.

## Rien n'échappe aux tests

`TEST-AUDIT-complet.cmd` auto-découvre le code : **un nouveau module dans `src/` ou
`hyper_smart_observer/` sans test associé est un ÉCHEC BLOQUANT.** Le module et son test se
créent dans le même mouvement. `resultat-audit.md` liste chaque fichier (lignes, importé par
combien, testé oui/non, couverture réelle) : aucun fichier ne peut se cacher.

**La vérité, c'est Windows**, pas le sandbox (qui tronque les gros fichiers et corrompt
l'UTF-8). Avant de committer : `ast.parse` sur le blob **stagé**, pas sur le fichier lu.

## La maladie du projet — à vérifier à chaque livraison

Mesurée le 18/07 : **954 modules, 63,3 % câblés, 28,6 % testés-SEULEMENT, 8,1 % orphelins.**
Un module importé n'est pas un module appelé ; une valeur mesurée qui ne franchit aucune porte
est du code mort. **« mention ≠ porte. »**

Une feature est DONE seulement si : codée, **testée**, documentée, **câblée** (ou marquée
`PARTIAL_NOT_WIRED`), et sans affaiblir le no-real-trade.

## Vérité des données et du PnL

- Jamais de donnée fabriquée présentée comme réelle. Données réelles ou **état vide honnête**.
- Le PnL vient d'un **ledger d'événements**, pas d'un compteur. Dashboard, audit, logs et
  exports convergent sur le même ledger.
- Le latent (base non réalisée) est **affiché séparément**, jamais additionné au net.
- `LIVE / BACKTEST / REPLAY / TEST_FIXTURE` ne se mélangent jamais.
- Un champ absent reste **absent** (`None`), il ne devient pas `0` : un zéro fabriqué ment
  plus qu'un trou avoué.
- **Enregistrer les REFUS** autant que les acceptations — sinon on n'a que des gagnants dans
  ses propres données (biais de survivant maison).

## But quant

Moins de trades, beaucoup plus propres. Filtrer les mauvais signaux ; ne garder que ceux à
**edge net positif après** frais + spread + slippage + latence + dégradation de copie. Juger
au **profit factor**, pas au winrate. **Jamais de promesse de PnL.**

## Instruments disponibles (2026-07-22 — s'en servir, ne PAS les réinventer)

Le bot a désormais tout pour CHERCHER l'edge honnêtement. Avant d'ajouter, vérifie que ça
n'existe pas déjà :

**Comprendre / juger le PnL et l'edge**
- `ops/diagnostic_pnl.py` — LA cervelle : « où va l'argent · l'edge existe-t-il · prochaine
  action ». Écrite dans `RECAP-COMPLET.md` à chaque run — **à analyser mot par mot.**
- `ops/loop_readiness.py` — score **BOT-READY** (0-100) + échelle d'autonomie N0 observe → N1
  paper → N2 testnet (le RÉEL est hors échelle, plafond codé en dur ; no-real-trade = gate dur).
  Commande : `python tools/bot_ready.py`.
- `backtesting/robustesse_selection.py` — **PBO** (Probability of Backtest Overfitting, CSCV,
  López de Prado) + seuil de bruit du multiple-testing. La recherche à ~1400 essais ne peut plus
  fabriquer un faux gagnant : un PBO > 50 % **interdit** tout « FAIS ÇA ».
- `docs/LOIS_MESUREES.md` — ce qui est déjà tranché (ne pas re-litiger sans donnée neuve).

**Les 4 leviers d'edge (état au 22/07)**
- **L1** univers complet 38→**206 coins** (dispersion cross-venue) — fait, quasi gratuit.
- **L2** funding au-dessus du plancher — MESURÉ : **0,00 %** bat HLP même sur 206 coins → le carry
  au plancher est dominé ; ce n'est pas un problème d'univers, il n'y a pas de demande à capter.
- **L3** arbitrage au **prix EXÉCUTABLE** (`funding/arb_executable.py`) — le +0,54 $ au mid était
  une **illusion** (−2,7 $ exécutable ; 35 % des signaux = appariements aberrants, désormais
  écartés). Il manquait le carnet réel : `tools/collecter_carnet.py` le collecte (auto-démarré) —
  **à BRANCHER dans la calibration arb** quand il aura accumulé quelques heures.
- **L4** liquidations (flux forcé — le liquidé est FORCÉ, il ne choisit pas) : ciblage **fort
  levier** + watchlist accumulée. Verdict à l'accumulation (~50 événements DISTINCTS requis ;
  ⚠️ les « grappes » brutes ≠ événements distincts).

**Collecte fiable & maximale**
- `collection/collecte_fiable.py` — socle réutilisable : dedup borné, écriture atomique (fsync),
  backoff+jitter, limiteur de débit, provenance, porte de qualité. « Plus de données SANS ban ni
  poubelle. »
- Collecteurs **auto-démarrés avec le bot** (LANCER_HYPERSMART + REANIMER-COLLECTEURS + REGISTRE
  du superviseur) : carry-feeder, marks, liq, venues, **carnet**, copy-whitelist, rapport. Les
  **trois listes bougent ENSEMBLE** (canari `test_le_REGISTRE_correspond_au_LANCEUR`).
- Rétention : le cap des shards replay **ARCHIVE** l'overflow (`_archive/`), ne le supprime plus ;
  `merge_replay(include_archive=True)` le fait remonter dans `_merged` que TOUT-TESTER mange.
  **Rien d'important n'est perdu à la fermeture.**

**TOUT-TESTER — le fichier qui mène à l'objectif**
- Ne plante **jamais** en silence (filet Python `except BaseException`, timeout dur via Timer,
  Ctrl-C toujours en pause). Le `.cmd` reste minimal (il a planté 2× quand il portait de la logique).
- **Voir tout** : sortie streamée en direct + progression/ETA (« étape i/N · écoulé · reste ~mm:ss »).
- **Plus rapide** : suite pytest en parallèle (xdist `--dist loadfile`, repli série sûr via
  `TOUT_TESTER_PYTEST_SERIE=1`) ; recherche des 3 modules en parallèle (résultats identiques) ;
  `pip install` sauté si déjà présent.
- Écrit un `RECAP-COMPLET.md` **ultra riche** (étapes, PnL par stratégie/motif, données
  disponibles, santé, BOT-READY, cervelle edge, prochaine action) — le fichier à m'envoyer.

## Où trouver le reste

- **État, méthode, archi, config, feuille de route** → `docs/ETAT_ET_FEUILLE_DE_ROUTE.md` (maître)
- **Règles complètes de l'agent** → `CLAUDE.md` (racine)
- **Lois mesurées** → `docs/LOIS_MESUREES.md`
- **Objectif condensé** → `OBJECTIF.md`
- **Config détaillée** → `docs/CONFIG_FLAGS.md`
- **Tout lancer en une fois** → `TOUT-TESTER.cmd` (sécurité, tests, invariants, câblage,
  qualité des données, backtests carry+arbitrage, recherche de pépites, santé live)
- **Rapports produits** : `RECAP-COMPLET.md`, `rapports/RAPPORT_DU_JOUR.md`,
  `runtime/replay/BACKTEST_CARRY.md`, `runtime/replay/BACKTEST_ARBITRAGE.md`,
  `runtime/replay/RESULTATS_RECHERCHE.md`

## Rapport final attendu (en français, à chaque fois)

fichiers modifiés · bugs trouvés · corrections appliquées · tests lancés · limites restantes ·
prochaines étapes · puis, littéralement :

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
