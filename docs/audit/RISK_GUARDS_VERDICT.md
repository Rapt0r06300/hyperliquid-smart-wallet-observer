# T3b — Les 25 garde-fous de `risk/` : branchés ou enterrés. Rien dans l'entre-deux.

> Décidé le 2026-07-12. **Ce document ne fait pas foi à lui seul** : la vérité est dans
> `src/hl_observer/risk/tombstones.py`, et elle est **testée** par
> `tests/test_risk_guards_no_limbo.py`. Un document ment sans bruit ; un test, non.

## Le problème, en une phrase

L'audit T3 a trouvé des garde-fous de risque avec des **tests verts** et **aucun appelant en
production**. Le kill-switch était « testé ». Personne ne l'appelait. La suite était verte.

**Un garde-fou testé que personne n'appelle ne protège de rien : il rassure.** C'est pire que
son absence, parce qu'on croit être couvert.

## 🚩 Correction honnête, d'entrée : ils étaient **25**, pas 21

J'ai annoncé « 21 garde-fous morts ». Le chiffre venait d'un **grep tronqué**. Il en manquait
quatre : `advanced_risk_manager`, `liquidity_guard`, `slippage_guard`, `stale_data_guard`.

Ce n'est pas moi qui les ai trouvés — c'est le **test d'invariant**, à sa première exécution.
D'où la leçon centrale de cette tâche :

> **Un inventaire se fait une fois et se trompe. Un invariant se vérifie à chaque exécution.**

## La grille de décision (appliquée aux 25, sans exception)

Un garde-fou est **BRANCHÉ** seulement si les **trois** conditions tiennent :

1. il protège d'une panne **structurellement possible sur le chemin paper vivant** — pas d'un
   risque d'exécution réelle, qui ne peut pas survenir puisqu'aucun ordre n'est jamais émis ;
2. **aucun garde-fou vivant ne couvre déjà** la même chose (pas de doublon) ;
3. le point de décision vivant peut **réellement l'alimenter** (pas un garde-fou affamé).

Le critère 3 est le plus important et le plus négligé : **un garde-fou nourri de `None` ne
protège de rien.**

## La surface de risque VIVANTE (ce qui a déjà le pouvoir)

| Point de décision (vivant) | Garde-fous appelés |
|---|---|
| `ui/fusion_persistent_adapter._portfolio_open_refusal` | max positions · exposition brute · `directional_refusal` (net + par coin) · `engine_budget_refusal` · **+ 2 branchés par T3b** |
| `signals/v26_entry_vetos.apply_v26_entry_vetos` | `graded_halt` · `protections_v26` |
| `ui/routes.py:1981` | `evaluate_microstructure_guard` |
| `paper_trading/v26_exit_pipeline` | `protections_v26` · `force_exit_all_positions` |
| `copy_wallet/wallet_mirror_runtime` · `arbitrage/*` | `evaluate_v19_risk_gates` |

## ✅ BRANCHÉS (2)

### `portfolio_correlation` — la panne qu'on a **réellement subie**

Sa première ligne dit tout : *« 7 positions LONG sur des alts corrélés ≠ 7 paris : c'est UN gros
pari directionnel déguisé. »* Nos **19 ouvertures SHORT sur 21** en sont la version réalisée.

`directional_exposure` (vivant) plafonne le **net total** et la concentration **par coin** — il
voyait donc SOL-short et AVAX-short comme deux paris indépendants. Ils ne le sont pas.

Branché dans `_portfolio_open_refusal`. Raisons de refus : `CORR_TOO_MANY_SAME_GROUP_SAME_SIDE`,
`CORR_GROUP_NET_EXPOSURE_EXCEEDED`.

> 🚨 **Piège mortel évité.** Le défaut d'usine du module est
> `max_group_net_exposure_usdt = 120 $`. Notre notionnel est de **500 $ par trade** (marge 50 ×
> levier 10). Branché tel quel, ce garde-fou aurait refusé **100 % des entrées** — mot pour mot
> le bug « 0 trade GARANTI par arithmétique » du 11/07. Le plafond est donc exprimé en **% de
> l'equity** (`HYPERSMART_MAX_GROUP_NET_EXPOSURE_PCT`, défaut **80 %** : plus haut qu'un coin
> seul à 60 %, plus bas que le net total à 100 %).

> 🚨 **2ᵉ piège évité.** Le module exige `side` en majuscules et rend `CORR_INVALID_SIDE` sinon.
> Un runtime qui dit `"buy"` aurait fait refuser **tout**. On normalise ; si le sens reste
> indéchiffrable, on **saute** ce garde-fou (les autres s'appliquent) — bloquer 100 % des entrées
> sur un désaccord de vocabulaire serait pire que le risque couvert.

### `trade_budget` — anti-surtrading

`max_concurrent` était déjà vivant (`HYPERSMART_MAX_OPEN_POSITIONS`, 12). Le **nombre de trades
par jour**, non. Le firehose V27 est conçu pour maximiser les signaux : le surtrading est
structurellement possible. Le compte vient du **ledger** (source de vérité), pas d'un compteur
mémoire qui divergerait au premier redémarrage.

**Honnêteté :** à nos volumes (21 trades sur tout un run), ce plafond **ne mord pas**. C'est un
disjoncteur — il ne sert à rien jusqu'au jour où il sert.

> 🚨 **3ᵉ piège évité, attrapé par mon propre test.** `can_open` fait
> `if trades_today >= max_trades_per_day: REFUSE`. Avec un plafond à **0** (ce que j'entendais
> comme « pas de plafond »), ça donne `0 >= 0` → **refus de 100 % des entrées**. Un plafond ≤ 0
> signifie désormais explicitement *aucun plafond* : le garde-fou est sauté.

## ⚰️ ENTERRÉS (23)

« Enterré » ne veut pas dire « effacé ». Le fichier reste sous git, récupérable. Ça veut dire :
**aucun chemin de production ne doit l'appeler, et c'est maintenant une règle testée.**

### La pile V9, remplacée par la pile V26 (vivante)

| Module | Remplacé par (vivant) |
|---|---|
| `kill_switch` | `portfolio_drawdown_kill_switch` + `graded_halt` RED + le contrôle inline de `risk_engine_v3` |
| `circuit_breaker` | `graded_halt` (machine à états GREEN/AMBER/RED) |
| `trade_circuit_breaker` | idem — c'était la **3ᵉ** implémentation du même concept |
| `loss_halts` | `graded_halt` + `protections_v26` + `equity_hard_stop_loss` |
| `entry_guard` | `v26_entry_vetos` — `entry_guard` se décrivait lui-même comme un « wiring helper » composant `circuit_breaker` + `exec_gates` : **ses trois dépendances sont mortes** |
| `exec_gates` | `v26_entry_vetos` (fraîcheur, liquidité, edge) + `microstructure_guard` |
| `advanced_risk_manager` | toute la pile V26 (halt, régime, microstructure) |

### Doublons de garde-fous vivants

| Module | Remplacé par (vivant) |
|---|---|
| `correlated_exposure` | `portfolio_correlation` (branché ci-dessus) — deux morts faisaient la même chose |
| `portfolio_risk` | `directional_exposure`. ⚠️ Son `data_anomaly` (saut de prix) est une **bonne idée**, mais **affamée** : le point de décision n'a pas de couple (prix précédent, prix nouveau). Le manque est le **flux**, pas le garde-fou → tâche dédiée |
| `position_sizing`, `sizing_v2` | `adaptive_sizing` / `kelly_sizer` / `proportional_paper_sizer` |
| `trade_floor` | `HYPERSMART_MIN_PAPER_NOTIONAL_USDT` + le plancher d'edge net |
| `slippage_model`, `slippage_guard` | les coûts **mesurés** sur le carnet L2 réel (`live_costs_for`, P2-2). ⚠️ **Danger si ressuscités** : un slippage *constant* est exactement le bug que P2-2 a corrigé. Les rebrancher serait une **régression**, pas une protection |
| `latency_model` | `signal_decay` + les gates de fraîcheur. Voir Z1 : la courbe edge/horizon est **plate** — pénaliser la latence ne rapporte rien |
| `atr_trailing_stop` | `sltp_runtime` (le moteur de sortie vivant) |
| `market_manipulation_flags` | `microstructure_guard` + `abnormal_spread_detector` |
| `liquidity_guard` | `microstructure_guard` (profondeur du vrai carnet) |
| `stale_data_guard` | les gates de fraîcheur — LE gate le plus appliqué du projet, auquel ce module ne participait pas |

### Impossibles en paper (il n'existe aucun ordre réel)

| Module | Pourquoi |
|---|---|
| `duplicate_order_guard` | déduplication d'ID d'ordre broker. Il n'y a pas de broker |
| `partial_fill_pair_guard` | le risque de **jambe nue** est déjà verrouillé, autrement, par `funding_carry_economics` (11/07). ⚠️ Si **Q2** (arbitrage à jambes réelles) aboutit, cette tombe devra être rouverte **explicitement** |
| `reconciliation_guard` | un stub d'**une ligne**. Aucun état broker à réconcilier |

### Ce n'est pas un garde-fou, c'est une stratégie

`scale_out` — la prise de profit partielle est un **choix de stratégie**. Un garde-fou *refuse* ;
il n'optimise pas. L'idée vit dans **H-179** (table ROI par paliers).

## L'invariant, et pourquoi il change tout

`tests/test_risk_guards_no_limbo.py` **échoue** si :

- un module de `risk/` n'est **ni** joignable depuis la production **ni** dans le registre
  → c'est un **limbe** : personne ne sait s'il compte. Interdit ;
- un module **enterré** redevient importé par la production → **résurrection accidentelle**.
  Interdit sans décision écrite ;
- un module déclaré **branché** n'est en fait pas atteignable → la tombstone mentirait *dans
  l'autre sens* (on se croirait protégé).

Plus trois tests qui **appellent le vrai point de refus** et vérifient qu'il refuse — et,
surtout, **qu'il laisse passer** un pari sain. Ce test-là est le plus important des deux :
*un garde-fou qui refuse tout est pire qu'un garde-fou absent — il rend un PnL de zéro, et on
se croit prudent.*

**On ne peut plus ajouter un garde-fou de risque sans décider, par écrit, s'il a le pouvoir ou
s'il est mort. Le 26ᵉ ne pourra plus se cacher.**

---

# T3c — le même invariant sur le chemin des SORTIES (`paper_trading/` + `exits/`)

> Décidé le 2026-07-12, dans la foulée. C'est là que **30 % de la perte de −64 $** a été faite
> (autopsie du 11/07). C'est le dernier endroit où l'on peut se permettre un doute sur qui a
> réellement le pouvoir.

## 🚩 Rebelote : j'annonçais 8 morts. Il y en avait **17**.

Le test — pas moi — a trouvé :

- **3 de plus dans `paper_trading/`** : `can_buy_amount_simulator`, `hedge_reconciliation`,
  `liquidity_route_simulator` ;
- **4 dans `exits/`**, un paquet que je n'avais même pas ouvert : `leader_exit_monitor`,
  `partial_take_profit`, `time_stop`, `trailing_stop` — quatre **stubs d'une ligne**.

Deuxième fois dans la même journée (T3b : 21 annoncés, 25 réels). La leçon ne change pas, elle
se confirme : **un inventaire se fait une fois et se trompe ; un invariant se vérifie à chaque
exécution.**

## ✅ Le 3ᵉ branchement : le garde-fou qui aurait empêché le bug des −64 $

`barrier_calibration.breakeven_winrate(tp, sl, coût)` calcule le winrate d'équilibre imposé par
une structure de barrières : `p* = (SL + c) / ((TP − c) + (SL + c))`.

L'autopsie du 11/07 avait trouvé : *« TP raboté à 28 bps pour 13 bps de frais → breakeven 87 %
→ perte GARANTIE »*. La correction avait été de **changer la config**. Rien n'empêchait la
rechute. Et il y a pire, mesuré aujourd'hui :

| Source de la config | TP | SL | coût | Winrate d'équilibre | |
|---|---|---|---|---|---|
| `start_hypersmart_simulation.ps1` (le lanceur) | 110 | 60 | 12 | **42 %** | ✅ atteignable |
| **Défaut du code** (`sltp_runtime.py:57-58`) | 30 | 40 | 12 | **74 %** | ❌ perte garantie |

Le flag du lanceur a **déjà disparu deux fois** dans ce projet (poller L2, jambe funding). Si ça
se reproduit, le bot repart **en silence** sur une configuration à perte garantie.

Branché dans `_portfolio_open_refusal`. Raison de refus :
`BARRIERS_BREAKEVEN_WINRATE_IMPOSSIBLE(74pct_needed_max_60pct_tp30_sl40_cost12)`.

**Testé dans les deux sens** : il refuse le défaut du code, il **laisse passer** la config du
lanceur. (Sinon on aurait remplacé une perte lente par un PnL de zéro — en se croyant prudent.)

## ⚰️ Enterrés (17)

`take_profit_stop_loss_local`, `trailing_stop_local`, `trailing_stop`, `time_stop`,
`leader_exit_monitor`, `exit_engine`, `exit_policy`, `exit_policy_runtime` — tous **doublés par
`sltp_runtime`**, le moteur de sortie vivant (`ui/routes.py:2398` → `vol_adjusted_barriers`).
Les quatre de `exits/` sont littéralement des fonctions d'une ligne, sans état, sans frais,
sans ledger.

`position_tracking`, `journal` — **doublons du ledger et de l'état vivant**. Deux livres de
positions = deux vérités possibles. Deux journaux = deux PnL possibles. La règle du projet
l'interdit.

`liquidity_route_simulator`, `can_buy_amount_simulator` — enveloppes mortes autour de
`exec_model.simulate_depth_execution` et de la profondeur du **vrai carnet L2** (P2-2).

`hedge_reconciliation` — **impossible en paper** : une jambe ne peut pas « échouer à passer »,
il n'y a pas d'exchange. ⚠️ Se rouvre explicitement si **Q2** (arbitrage à jambes réelles) aboutit.

`max_chase_guard` — doublon du cap de dégradation de copie (`degr<=13`), vivant.

`fill_outcomes`, `order_types` — nouveau motif : **`REALISME_PAS_GARDE_FOU`**. Les brancher
rendrait le PnL plus **pessimiste** (donc plus honnête). Ce n'est pas un refus, c'est un
changement de **simulateur**. Ça se mesure avant de se décider.

`partial_take_profit` — stratégie, pas garde-fou (→ H-179).

## 🔒 Le cliquet global — ce qui manquait vraiment à MEGATEST

L'invariant ne juge que 3 paquets. Le reste du dépôt compte **305 modules** import-inatteignables.
On ne peut pas tous les trancher ce soir. Mais on peut **empêcher le nombre d'augmenter** :

```
PLAFOND_MORTS_GLOBAL     = 305
PLAFOND_ORPHELINS_GLOBAL = 104
```

Un cliquet ne tourne que dans un sens. Sans lui, le 306ᵉ module mort arriverait exactement
comme les 305 autres : **en silence**. (Il tourne dans MEGATEST : `audit_report.py` lance toute
la suite pytest.)

## 🚩 Et le pire : **mon audit cachait huit modules**

Le cliquet a d'abord affiché **305 > 300**, mon chiffre de référence. Avant de déplacer le
plafond, j'ai mesuré le delta (`tools/diff_cablage.py`). Ce n'était **pas une régression du
code** :

`tools/auditer_cablage.py` filtrait par **sous-chaîne** :

```python
IGNORE = ("__pycache__", "runtime/", "data/", ..., "_archive", "logs/")
if any(x in rel for x in IGNORE): continue
```

Intention : sauter le dossier de **données** `runtime/` à la racine. Effet réel :
`src/hl_observer/runtime/hot_path.py` contient *aussi* la sous-chaîne `"runtime/"` → **tout le
paquet de production `src/hl_observer/runtime/` était invisible.** Idem `"_archive"`, qui
mangeait `release/clean_archive.py`.

**Un module invisible ne peut jamais être déclaré mort.** L'outil dont le seul travail est de
trouver le code mort en cachait lui-même huit — dont `hot_path`, `event_driven_decider`,
`persistent_poll_runner`, `bounded_event_queue` : **le cœur du travail P4/P5, tous deux marqués
« completed »**. Filtre corrigé (ancré : préfixe de racine, ou segment entier), test
anti-régression posé, tâche **T3d** ouverte.

## Ce qui reste ouvert

- **T3d** — les 8 modules qui étaient invisibles : brancher ou enterrer, et statuer sur P4/P5.
- Le **garde-fou d'anomalie de prix** (`data_anomaly`) mérite d'exister — il lui manque un flux
  de mids au point de décision (tâche #591).
- `MidVolEstimator` n'est alimenté que **tant qu'il y a des positions ouvertes**
  (`_apply_sltp_exits_vol_adjusted_impl` sort tôt si `not positions`). Au démarrage à froid, les
  barrières « vol-ajustées » ne sont pas ajustées.

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
