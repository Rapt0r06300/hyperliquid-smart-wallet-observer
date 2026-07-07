# HyperSmart — Recherche "mode grinder" (beaucoup de mini-positions, copy + arbitrage)

Date: 2026-07-07. Sources: repos locaux `runtime/research/github_repos_v24/` + X + web.
Objectif produit demandé par Flo: reproduire les bots qui ouvrent plein de petites
positions et ramassent du PnL un peu partout — copy wallet + arbitrage.

## 1. Comment ces bots gagnent vraiment (mécanique, pas marketing)

### a) Copy trading (ApexLiquid, Copin, pvp.trade, MaxIsOntoSomething/Hyperliquid_Copy_Trader)
- Suivent PLUSIEURS leaders en même temps → naturellement beaucoup de petites positions.
- Sizing PROPORTIONNEL: taille = (mon capital / capital leader) × position leader.
- Dry mode par défaut, liste de coins bloqués, cap de levier par asset.
- Contrainte HL: notional minimum $10/ordre — les mini-fills sous ce seuil sont skippés.
- Leur talon d'Achille (documenté): la latence de copie tue les leaders scalpeurs;
  ils gagnent sur les leaders "swing" qui tiennent leurs positions.

### b) Arbitrage funding delta-neutre (32_gajesh2007, 30_rustjesty, Hummingbot)
- LE vrai "ramasser du PnL partout": positions simultanées sur N symboles,
  long spot/perp d'un côté + short de l'autre → zéro risque directionnel,
  encaisse le funding HORAIRE de Hyperliquid.
- Réglages du repo 32: entrée si edge funding ≥ 20 bps, sortie si < 5 bps,
  500$/jambe, max 10k$ total, top-5 symboles auto-découverts,
  filtre anti-spike (rate dans 2σ de la moyenne 24h), SL/TP par position,
  max hold, kill-switch drawdown portefeuille.
- Rendements nets documentés (web 2026): 3–12% APR sur majors, 20–60% sur
  long-tail (HYPE, nouvelles listes). Break-even ~1.3 bps/8h en maker.
- Le whale exemple: milliards de volume, risque net < 100k$ — 3-5 ordres
  enfants par entrée, toujours delta-neutre.

### c) Grid / market making (35_passivbot, chainstacklabs grid, MM bots X)
- Des centaines de micro-fills MAKER: profit = spread encaissé + rebate.
- passivbot: grille contrarian + take-profit markup rapproché après chaque
  re-entrée — beaucoup de petits gains, risque = moyenne à la baisse (à capper).
- Chainstack grid: 10 niveaux, bande ±5%, 10% du compte max, SL/TP/DD configurables.

### d) L'économie qui rend les mini-positions viables (le point clé)
- Fees HL: taker 4.5 bps base / maker 1.5 bps, rebates jusqu'à -0.3 bps.
- Notre simulation actuelle paie ~taker+spread+slippage (~12 bps par côté)
  → les micro-trades directionnels meurent (mesuré: fee drag 59%).
- Les grinders survivent parce que: fills MAKER (1.5 bps ou rebate),
  et/ou source de PnL = FUNDING récurrent (pas la direction),
  et/ou edge cross-venue encaissé instantanément.
- Latence HL: 200–500 ms par ordre — le scalping directionnel pur n'est pas
  copiable; le funding/maker grinding l'est.

## 2. Ce qu'on a DÉJÀ dans le moteur (primitives Codex, sous-utilisées)
- `funding/funding_rate_scanner.py` → FundingSignal (FUNDING_SPIKE).
- `market_making/market_making_paper.py` → PaperMakerQuote.
- `fusion_runtime` produit déjà: funding_signals, maker_quotes,
  delta_neutral_positions, funding_payments, triangular_opportunities.
- Ce qui MANQUE: matérialiser ces primitives en VRAIES positions paper
  multiples dans le ledger (aujourd'hui seul le copy directionnel ouvre).

## 3. Plan "mode grinder" (paper only, ledger unique, réversible)
1. **GRINDER-FUNDING**: matérialiser des paires delta-neutres paper multi-symboles
   (règles du repo 32: entrée ≥20 bps, sortie <5 bps, anti-spike 2σ, N symboles,
   petites jambes), PnL funding horaire crédité au ledger + fees maker modélisés.
2. **COST-MODEL MAKER**: option de fill maker dans le simulateur d'exécution
   (1.5 bps + probabilité de fill selon spread/queue) — condition de survie des
   mini-positions; A/B taker vs maker sur les mêmes signaux.
3. **COPY MULTI-LEADERS PROPORTIONNEL**: suivre plus de leaders simultanément
   avec sizing proportionnel et floor $10 (au lieu de refuser petit = accepter
   petit MAIS maker + leaders swing seulement, holding > 15 min).
4. **GRID PAPER (option)**: profil passivbot-like cappé (pas de martingale infinie).
Chaque brique: flag env dédié, tests, replay A/B avant activation par défaut.
Modes cohabitants: SNIPER (edge net élevé, peu de trades) + GRINDER (beaucoup de
petites positions à coût unitaire quasi nul). Le ledger reste l'arbitre.


## 4. Implémentation livrée (2026-07-07)

| Brique | Code | Flag (défaut OFF) | Tests |
|---|---|---|---|
| Coût maker + adverse selection | `paper_trading/exec_model.py`, `paper_engine.py` | `HYPERSMART_EXECUTION_STYLE=maker`, `HYPERSMART_MAKER_ADVERSE_SELECTION_BPS` | `test_maker_execution_style.py` (3) |
| Funding arb delta-neutre paper | `funding/funding_arb_paper.py` + câblage `fusion_runtime` → `fusion_persistent_adapter` → ledger | `HYPERSMART_FUNDING_ARB_PAPER=1` (+ `_MIN_EDGE_BPS_H`, `_MAX_PAIRS`, `_LEG_NOTIONAL_USDT`…) | `test_funding_arb_paper.py` (6) + `test_funding_arb_wiring.py` (3) |
| Copy multi-leaders proportionnel | levier existant `HYPERSMART_DISTILLED_MAX_PAPER_ENTRIES` (cap dur 5) + whale sizing | preset launcher commenté | `test_grinder_preset.py` (3) |

Comptabilité funding-arb sans double compte: OPEN débite les coûts d'entrée,
ACCRUAL crédite le funding, CLOSE débite les coûts de sortie. Chaque événement
est un enregistrement ledger `FUNDING_ARB_*` dédupliqué, `execution=forbidden`.

Limitations honnêtes: paires funding refermées à plat après un restart serveur
(store process-local); pas de PnL prix modélisé sur les paires (couverture
supposée parfaite = optimiste sur la divergence, pessimiste sur les frais des
deux jambes); filtre "leaders swing" (holding > 15 min) pas encore implémenté.

Prochaine étape d'activation: lancer une session avec le bloc GRINDER
décommenté, laisser tourner ≥ 48h, puis `closed-ledger-replay` + comparaison
PF net vs baseline avant de passer un flag en défaut.
