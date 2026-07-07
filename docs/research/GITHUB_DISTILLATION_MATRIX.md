# HyperSmart - GitHub Distillation Matrix

Date: 2026-07-06

Objectif: remplacer le "bus GitHub" direct par une distillation propre. Les
repos externes restent une mine d'idees, mais ils ne doivent pas ecrire des
positions dans la simulation tant que leurs regles n'ont pas ete portees,
mesurees, testees et validees dans le pipeline unique HyperSmart.

Pipeline cible:

```text
Hyperliquid read-only data
-> normalized features
-> opportunity detector
-> risk engine
-> PaperEngine canonique
-> PaperLedger
-> dashboard / logs / replay A-B
```

Regle de base:

- les repos externes peuvent inspirer une regle;
- les profils externes peuvent rester en shadow/evidence;
- aucune strategie externe ne bypass le RiskEngine;
- aucune strategie externe ne bypass le PaperEngine;
- aucune activation live-paper sans replay A/B positif net de frais;
- aucune promesse de PnL positif.

## Repos prioritaires

| Priorite | Repo | Idee a distiller | Port HyperSmart | Module cible | Statut | Activation |
|---:|---|---|---|---|---|---|
| 1 | whale-wallet-mirror-copy-trader | consensus whale, sizing proportionnel, copy lag | cluster de deltas leader frais par coin/sens | `copying`, `risk`, `paper_trading` | SHADOW_RESEARCH | PF replay positif apres frais, sans lookahead |
| 2 | Solana-Copy-trading-bot | decouverte leaders, budget latence, logs de session | mesure d'age fill leader + rejet stale | `copying.latency`, `logs`, `dashboard` | SHADOW_RESEARCH | fraicheur sub-seconde prouvee et PF replay ameliore |
| 3 | hyberliquid-arbitrage-bot | discrepancy cross-source, spread sanity | signal de contexte read-only, jamais ordre direct | `arbitrage`, `source_health`, `features` | SHADOW_RESEARCH | sources live + spread net positif apres couts |
| 4 | freqtrade | dry-run discipline, walk-forward, anti-overfit | replay A/B et promotion de flags seulement si out-of-sample OK | `backtest`, `experiments`, `risk` | SHADOW_RESEARCH | walk-forward positif, drawdown acceptable |
| 5 | hummingbot | abstraction connector, inventory/risk caps | connecteurs read-only/testnet futurs + limites inventaire | `connectors`, `risk`, `paper_trading` | SHADOW_RESEARCH | aucune action reelle; abstractions seulement |
| 6 | passivbot | sizing, exposure caps, discipline de risque | caps paper; pas de martingale automatique | `risk.sizing`, `exits`, `paper_trading` | SHADOW_RESEARCH | drawdown replay reduit; averaging-down bloque |
| 7 | prediction-market-backtesting | replay sans lookahead, rapports reproductibles | parite replay paper vs live paper | `backtest.replay`, `paper_ledger`, `reports` | VALIDATION | toujours actif pour verifier, jamais forcer trade |
| 8 | Polymarket agents | agent analyste, pas executant | IA/Ollama en explication shadow-only | `ai`, `evidence`, `dashboard` | SHADOW_RESEARCH | aucune autorite hot-path |
| 9 | TradingView lightweight-charts | chart stable, tooltips, UX trading | UI basee sur ledger canonique et vrais marks | `ui.static`, `dashboard` | UI_ONLY | aucune donnee synthetique |

## Pourquoi on coupe le bus direct

Le bus direct donne une illusion dangereuse: "34 moteurs actifs" peut produire
des ordres papier incoherents, parfois contradictoires, sans preuve que ces
regles sont adaptees a Hyperliquid. Cela cree des pics PnL, du bruit, et rend
les pertes difficiles a expliquer.

La nouvelle approche force chaque idee a passer par:

1. une fiche de distillation;
2. un port Hyperliquid local;
3. un test unitaire;
4. un replay A/B;
5. une validation de frais/slippage/latence;
6. une activation explicite si elle ameliore le profit factor net.

## Premiere decision implementee

`HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION` est desactive par defaut.

Effet:

- les profils GitHub externes restent evalues;
- leurs executions restent visibles dans le ledger comme `ENGINE_EVALUATION`;
- leurs ordres directs sont comptes comme shadow;
- ils ne peuvent plus ouvrir/fermer une position par defaut;
- seul le PaperEngine canonique reste la source normale des positions.

## Durcissement 2026-07-07 (coupe du bus renforcee)

1. **Scope des profils**: `HYPERSMART_EXTERNAL_PROFILES_SCOPE` controle quels
   profils GitHub sont evalues par le bus:
   - `priority` (defaut): seuls les 9 repos de la matrice ci-dessus;
   - `all`: bus complet historique, recherche locale uniquement;
   - `off`: aucun profil externe evalue.
   Effet: plus de "34 moteurs actifs" par defaut. Les runtimes Polymarket/Solana
   incompatibles ne sont plus evalues a chaque cycle.

2. **Double verrou de materialisation**: la materialisation directe exige
   maintenant DEUX flags. Un seul ne suffit plus (raison ledger:
   `EXTERNAL_DIRECT_REQUIRES_AB_RESEARCH_ACK`).

Activation de recherche locale (A/B controle uniquement):

```powershell
$env:HYPERSMART_EXTERNAL_GITHUB_DIRECT_MATERIALIZATION="1"
$env:HYPERSMART_AB_RESEARCH_ACK="1"
```

Cette activation sert uniquement a des tests A/B locaux controles. Elle ne doit
pas etre le mode normal. Tests: `tests/test_external_profile_scope.py`.

## Vertical slice branchee

La premiere tranche utile est maintenant branchee sans contourner le moteur
canonique:

```text
position_deltas locaux + allMids Hyperliquid reels
-> fusion_heartbeat_input
-> distilled_signal_candidates mesures
-> distilled_opportunity_detector
-> fusion_runtime
-> PaperEngine canonique
-> dashboard / logs / replay
```

Contraintes de cette tranche:

- un candidat distille n'est cree que si le delta local contient deja des
  mesures explicites: `edge_remaining_bps`, `liquidity_score` et
  `copy_degradation_bps`;
- aucune valeur edge/liquidite/cout n'est inventee depuis un simple vote;
- le coin doit avoir un prix local Hyperliquid `allMids`;
- le detecteur exige consensus frais, edge net, liquidite et cout de copie;
- si le vote classique ne produit pas d'entree mais que l'opportunite
  distillee passe les gates, elle repasse quand meme par le `PaperEngine`;
- si le prix reel manque, le `PaperEngine` refuse avec
  `MARKET_PRICE_INVALID`;
- les executions de profils GitHub externes restent des evaluations shadow par
  defaut.

## Runtime PnL / logs - statut 2026-07-06

La distillation doit rester pilotee par le ledger, pas par l'affichage "34
moteurs actifs". Le diagnostic local actuel montre que le probleme dominant
n'est pas seulement "pas assez de trades", mais surtout la qualite nette des
trades acceptes:

- source analysee: `logs/logs a envoyer`;
- source de verite: ledger papier canonique exporte dans les snapshots, puis
  `simulation_pnl_ledger_latest.jsonl` des que le serveur est relance avec le
  nouvel export;
- decisions PnL detectees: 11 decisions acceptees, dont 9 sorties papier;
- gagnantes/perdantes: 3 / 6 sur les sorties closes;
- PnL net ledger ferme: -1.247179 USDC;
- PnL portefeuille live verifie au check API: environ -3.27 USDC;
- positions ouvertes live: 23;
- exposition paper ouverte: environ 920.57 USDT;
- latent ouvert: environ -1.56 USDC;
- frais/couts: 0.477042 USDC;
- `fee_drag_ratio`: 0.585901;
- `profit_factor_net`: 0.613670;
- `closed-ledger-replay`: `no_trade_baseline` reste meilleur que les
  strategies testees sur cet extrait;
- coins perdants a tester en cooldown: MON, LIT, KBONK, LDO, MORPHO, NEAR;
- coins gagnants a conserver en observation: VVV, FARTCOIN.

Conclusion recherche-only: augmenter le nombre de moteurs ou rebrancher le bus
GitHub direct ne corrige pas ce profil. La prochaine activation doit passer par
un replay A/B net de frais sur les flags candidats:

| Flag candidat | Raison | Test A/B requis |
|---|---|---|
| `HYPERSMART_REQUIRE_PROFIT_FACTOR_REPLAY_GATE=true` | PF net < 1 | baseline vs gate PF |
| `HYPERSMART_MIN_PAPER_NOTIONAL_USDT=40` | frais/couts > 35% du brut | baseline vs no micro-trades |
| `HYPERSMART_MIN_EDGE_AFTER_COST_BPS=45` | edge trop faible apres frais | baseline vs edge net 45 bps |
| `HYPERSMART_MIN_CONSENSUS_WALLETS=3` | winrate ledger trop faible | baseline vs consensus 3 |
| `HYPERSMART_LOSS_STREAK_COOLDOWN=3` | serie de pertes max = 3 | baseline vs cooldown |
| `HYPERSMART_REPLAY_COIN_COOLDOWN_SET=MON,LIT,KBONK,LDO,MORPHO` | pertes concentrees par coin | baseline vs coin cooldown |
| `HYPERSMART_MAX_OPEN_PAPER_POSITIONS=5` | exposition ouverte trop elevee | baseline vs max open positions |
| `HYPERSMART_UNREALIZED_DRAWDOWN_GUARD_USDT=1.0` | latent ouvert negatif | baseline vs drawdown guard |

Regle: aucun de ces flags ne doit etre active comme "solution" tant que le
replay A/B ne montre pas une amelioration nette du profit factor sans lookahead.

Tests de couverture actuels:

- `tests/test_github_distillation_matrix.py`;
- `tests/test_distilled_opportunity_detector.py`;
- `tests/test_fusion_heartbeat_input.py`;
- `tests/test_fusion_paper_engine_adapter.py`;
- `tests/test_fusion_strategy_runtime.py`;
- `tests/test_fusion_persistent_adapter_external_profiles.py`;
- `tests/test_ui_simulation_status_fast.py`.
- `tests/test_ledger_pnl_calibration.py`;

## Portage realise 2026-07-07 (idee n°1 - whale consensus)

- `hl_observer/copying/whale_consensus_sizing.py`: sizing proportionnel au
  consensus (wallets frais alignes x fraicheur cluster x notional leaders),
  multiplicateur borne [0.30, 1.00] - ne peut QUE reduire la taille.
- Cable dans `run_distilled_opportunities_through_paper_engine` via
  `margin_scale` (additif, PaperEngine inchange par defaut).
- Flag: `HYPERSMART_WHALE_CONSENSUS_SIZING` (defaut OFF - conformement a la
  regle d'activation: replay A/B dedie requis avant activation).
- Tests: `tests/test_whale_consensus_sizing.py` (5).
- Replay A/B 2026-07-07 (`docs/release/REPLAY_AB_FLAGS_20260707.md`):
  `HYPERSMART_MIN_PAPER_NOTIONAL_USDT=40` ACTIVE au launcher (train+validation
  positifs); cooldown coins NON active (reste negatif); `entry_context_only`
  positif = confirme la direction distillation.

## Prochain portage concret

1. Refaire `OpportunityDetector` autour du consensus whale frais.
2. Refaire `RiskEngine` autour de frais, slippage, age signal, drawdown et
   copy degradation.
3. Refaire `ExitEngine` autour de TP/SL/trailing/time-stop explicables.
4. Brancher tout au PaperLedger canonique.
5. Lancer replay A/B et activer seulement les regles avec profit factor net
   meilleur que la baseline.
