# HyperSmart Observer — État & Feuille de route

> **Document maître.** Source de vérité des règles = `CLAUDE.md` (racine) + `AGENTS.md`.
> Ce fichier résume **où on en est**, **comment on travaille**, et **ce qui reste à faire**.
> Dernière mise à jour : **2026-07-21** (§3bis : allocation par rendement net).

---

## 1. Objectif

Observer **Hyperliquid mainnet en lecture seule**, scorer les wallets smart-money, et
**simuler en paper local** un bot de **copy-trading + arbitrage** de type « grinder » (beaucoup
de petites positions propres). But : produire un **PnL paper réaliste**, proche du réel, **sans
jamais le maquiller ni le promettre**. Cible produit ultérieure : décision locale → exécution
**testnet uniquement** (fausse monnaie), jamais mainnet.

## 2. Ligne rouge sécurité (non négociable)

**TOUT est autorisé SAUF l'exécution réelle.** Interdits absolus : ordre réel, `/exchange` réel,
argent réel, clé privée, seed/mnemonic, signature réelle, wallet-connect pour agir, dépôt/retrait.
`READ-ONLY-MAINNET · LOCAL-DECISION · TESTNET-ONLY · DENY-BY-DEFAULT`. Un signal n'est jamais un
ordre ; un paper-trade n'est jamais un ordre. Donnée incertaine/trop vieille/incomplète → `NO_TRADE`.

## 3. État actuel (2026-07-08)

**Le run tourne** (`LANCER_HYPERSMART.cmd` → `python -m hl_observer ui`, port 8794, dashboard `/v2`).

Acquis récents (tous committés) :

- **Sizing réaliste — PnL en dollars, plus de centimes.** Le `$50` est la **MARGE** par position,
  pas le notional. Marge $50 × **levier 10** = **notional $500** → PnL = 500 × Δprix = des dollars.
  `20 positions × $50 = $1000` (solde). Cause du bug : double bride dans
  `ui/fusion_persistent_adapter.py::_cap_paper_notional_and_quantity` (corrigée). Prouvé live (+$6).
- **Dashboard relabellisé** : affiche la **MARGE $50/position** (notional/levier) au lieu du $500.
- **Firehose userFills multiplexé (V27)** : Hyperliquid cape `userFills` à 10 wallets/connexion ;
  on ouvre **N connexions parallèles** → jusqu'à 40 leaders suivis en **temps réel** (au lieu du
  top-10). Env `HYPERSMART_FILLS_MULTIPLEX=1`, `_CONNECTIONS=4`. Plafond dur 8 (anti-ban).
- **WS-first** (câblé, OFF par défaut) : coupe les REST redondants couverts par le WS.
- **Enregistrement replay** : `runtime/replay/candidates.jsonl` + `marks.jsonl` (avec **coin** —
  bug coin-vide corrigé, sans quoi le replay était inutilisable).
- **Anti-bloat DB** actif (`HYPERSMART_DISABLE_RAW_STORAGE=1`) — la cause du crash du 1er run 48h.

## 3bis. Le capital allait aux mauvais coins (2026-07-21)

**Ce qu'on a mesuré, pas ce qu'on croyait.** Sur les 11 positions vivantes :

| coin | rendement net | marge engagée |
|---|---:|---:|
| BTC | **2,221 bps/j** (le meilleur) | **25 $** (le moins financé) |
| STABLE | 1,326 bps/j (parmi les pires) | **126 $** (le plus financé) |

Corrélation entre la marge engagée et le rendement net : **−0,596**. On finançait le plus les
coins les moins rentables — depuis toujours, sans qu'aucun écran ne le trahisse.

**La cause, nommée.** `marge_par_position` divise le capital en parts *égales* ; le seul
modulateur (`facteur_taille`) repose sur le **z-score du funding**. Or, au plancher
protocolaire (0,125 bps/h), *tous* les coins sont au même taux **par construction de la venue**
(`F = premium + clamp(0,125 − premium, ±5)`). Un z-score y mesure du **bruit** : un coin dont
l'historique traîne sous le plancher affiche un z élevé sans qu'il y ait rien à capter.

**Ce qui a changé (4 commits, 68 tests neufs) :**

1. `carry_optimizer.facteur_zscore(z, funding)` — **garde du plancher** : au plancher ou en
   dessous, facteur neutre. Au-dessus, il retrouve tout son rôle. Branché dans le feeder.
2. `funding/carry_allocation_nette.py` — le capital déployable est réparti
   **∝ `gain_net_24h_bps` ³**, un nombre que le moteur calculait déjà et jetait. Mêmes
   garde-fous que la marge dynamique (réserve 20 %, plafond 40 %/coin, plancher 25 $).
   Exposant choisi sur mesure : net¹ +5,4 % · net² +10,0 % · **net³ +14,9 %** · net⁵ +20,5 %
   (colle au plafond de concentration). **Sur les positions réelles : +23,9 %.**
3. `funding/carry_renfort.py` — **RENFORT** : combler l'écart marge → cible en *ajoutant* du
   notional à une position vivante (on ne paie que l'entrée de l'ajout, **jamais de sortie**).
   Six règles : viable ce tick · l'ajout doit amortir son propre coût avant la fin de vie ·
   moyennes pondérées par le notional · écart minimum 40 % · un renfort/position/24 h ·
   **même porte de risque qu'une ouverture**.
4. Visibilité — badge « marge cible » et compteur de renforts sur le dashboard, section
   **10. Où va le capital** dans le rapport quotidien.

**Aucun levier ne bouge : aucune distance de liquidation ne bouge.** On déplace du capital, on
n'achète pas du risque.

**Deux bugs attrapés en chemin** (`tools/ecrire_carry_spot_inputs.py`) :

- le motif de refus du scan était une **phrase écrite en dur** (« liquidée même à 2x ») datant
  de l'époque où le scan démarrait à 2x ; il descend à 1,0x depuis. ETHFI — meilleur funding du
  board — était refusé chaque passe sans cause lisible. Le motif est maintenant réel et
  détaillé (verdict après enquête : **le refus d'ETHFI est correct** — la venue le plafonne à
  3x, donc marge de maintenance 16,7 %, donc même un short 1x saute sur +76 %. Ce qui était
  cassé, c'est notre capacité à le savoir) ;
- **crash latent** : `levier_max <= 0` renvoyé par l'API levait une `ValueError` non attrapée →
  toute la passe du feeder tombait → plus de shortlist → `INPUTS_PERIMES` → bot affamé. C'est
  le mode de panne exact du 19/07. Un coin malformé est désormais **écarté**, pas fatal.

## 4. Façon de procéder (méthode)

1. **Inspecter Git** → 2. **Comprendre l'archi** → 3. **Protéger le local** (rien supprimer
   brutalement) → 4. **Documenter** → 5. **Coder proprement** (petits modules importables sous
   `src/hl_observer`) → 6. **Tester** → 7. **Vérifier que mainnet reste 100 % lecture seule et
   testnet verrouillé**.

Principes quant : **moins de trades, plus propres.** Filtrer les mauvais signaux ; ne garder que
les signaux **frais, cohérents, liquides, à edge net positif** après frais + spread + slippage +
latence + dégradation de copie. Juger au **profit factor**, pas au winrate brut. **Jamais** de
promesse de PnL. **Vérité des données** : jamais de donnée fabriquée présentée comme réelle ; PnL
issu d'un **ledger d'événements**, dashboard/audit/logs convergent sur le même ledger.

Gotchas récurrents (voir mémoire agent) : le **mount sandbox tronque** la vue des gros fichiers
édités (Windows reste intact — vérifier via py_compile Windows / réécrire via heredoc) ; l'**index
git Windows** peut être périmé après des commits plumbing-sandbox (fix `reset --mixed HEAD~1` +
`git add` explicite, jamais `-A`).

## 5. Architecture (runtime actif)

- Runtime : **`src/hl_observer/`** (lancé par `hl_observer ui`).
  - Collecte HL : `hyperliquid/`, `collection/`, `realtime/`, `wallets/` (userFills live + multiplex).
  - Edge : `edge/edge_calculator.py` (`compute_net_edge`, plancher net ~30 bps).
  - Décision copy : `copying/` (`realtime_magic_score`, `viral_bot_engine`), `opportunities/`,
    `signals/` (vetos V26), `paper_trading/` (ledger, SL/TP, exits), `risk/`.
  - Sizing autoritatif : `ui/fusion_persistent_adapter.py::_cap_paper_notional_and_quantity`.
  - UI : `ui/dashboard_v2.py` (terminal `/v2`, read-only).
  - Replay/backtest : `backtesting/ab_flag_replay.py`, `scenario_grid.py`, `scenario_search.py`.
- **`hyper_smart_observer/dydx_v4/`** = dYdX v4 legacy, dormant/comparatif — **ne pas y porter**
  d'idées destinées à la simu Hyperliquid.

## 6. Feuille de route

**Immédiat** : laisser le run de 48h se dérouler (il enregistre des données replay valides).

**Après les 48h** — recherche massive de scénarios sur les données réelles (voir
`docs/REPLAY_SCENARIO_SEARCH.md`) :
```
python -m hl_observer.backtesting.scenario_search \
  --candidates runtime/replay/candidates.jsonl --marks runtime/replay/marks.jsonl \
  --max-scenarios 30000 --jobs 0 --out runtime/replay/scenario_report.json
```
On garde **uniquement les scénarios « robustes »** (net>0 sur train ET test out-of-sample, gate OK,
plateau de voisinage sain). Puis on applique le meilleur réglage au runtime.

**Ensuite** : prioriser les **baleines** (meilleur PnL/ROI) comme signaux forts sans délaisser les
autres ; éventuellement câbler `concurrent_fetch` (débit) ; à terme, `testnet_executor` verrouillé.

**Reste connu** : `interval=15` (le réglage poll-5s ne se propage pas au runner — à corriger dans
le poll-loop ps1) ; `HYPERSMART_MAX_OPEN_POSITIONS=20` ; A/B des flags V26 via `ab_flag_replay`.

## 7. Commandes clés

| But | Commande |
|---|---|
| Lancer le run | `LANCER_HYPERSMART.cmd` (dashboard `http://127.0.0.1:8794/v2`) |
| Recherche scénarios (après 48h) | `python -m hl_observer.backtesting.scenario_search ...` |
| A/B des flags V26 | `python -m hl_observer.backtesting.ab_flag_replay ...` |
| Tests ciblés | `set PYTHONPATH=src && python -m pytest -q tests/test_no_real_trade_foundations.py ...` |
| Sécurité | `python -m hl_observer safety-audit` · `python -m hl_observer doctor` |

## 8. Config (extraits ; détail dans `docs/CONFIG_FLAGS.md`)

`HYPERSMART_SIMULATION_LEVERAGE=10` · `HYPERSMART_MAX_POSITION_USDT=50` (marge/position) ·
`HYPERSMART_MAX_OPEN_POSITIONS=20` · `HYPERSMART_FILLS_MULTIPLEX=1` (+`_CONNECTIONS=4`) ·
`HYPERSMART_V26_RECORD_CANDIDATES=1` (+`_RECORD_PATH=runtime/replay`) · `HYPERSMART_DISABLE_RAW_STORAGE=1`.
Testnet : `REAL_MAINNET_TRADING=false`, `TESTNET_ONLY=true`, `CONFIRM_TESTNET_EXECUTION=true`, caps.

---
*Métriques descriptives ; aucune promesse de PnL. Ce document reflète l'état au 2026-07-08 ;
mettre à jour à chaque évolution majeure.*
