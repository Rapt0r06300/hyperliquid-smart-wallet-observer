# HyperSmart - Ledger PnL Calibration 2026-07-06

Scope: simulation locale Hyperliquid, lecture seule, aucun ordre reel, aucun
mainnet executor.

## Etat observe

Commandes source:

```powershell
python -m hl_observer.cli logs-analyze --from-logs "C:\Users\flo\Desktop\Projet invest\logs\logs a envoyer"
python -m hl_observer.cli ledger-pnl-calibration --from-logs "C:\Users\flo\Desktop\Projet invest\logs\logs a envoyer"
python -m hl_observer.cli closed-ledger-replay --from-logs "C:\Users\flo\Desktop\Projet invest\logs\logs a envoyer" --output-dir "C:\Users\flo\Desktop\Projet invest\logs\logs a envoyer\optimization_reports"
python -m hl_observer.cli v19-pnl-audit --from-logs "C:\Users\flo\Desktop\Projet invest\logs\logs a envoyer"
```

Note Windows: le dossier reel garde son accent (`logs a envoyer` dans ce
document represente `logs à envoyer`).

Resultat frais:

- decisions analysees: 169;
- decisions acceptees: 11;
- sorties papier closes: 9;
- sorties gagnantes/perdantes: 3 / 6;
- PnL ferme ledger: -1.247179 USDC;
- PnL session portefeuille live verifie: environ -3.27 USDC au moment du check API;
- positions ouvertes live: 23;
- exposition paper ouverte: environ 920.57 USDT;
- latent ouvert: environ -1.56 USDC;
- frais/couts: 0.477042 USDC;
- fee drag ratio: 0.585901;
- winrate evenementiel: 0.333333;
- profit factor net: 0.613670;
- audit PnL: OK apres bascule sur logs frais par defaut;
- protection mode: actif.

## Causes probables

1. Les frais/couts dominent trop le brut.
2. Les trades perdants sont plus nombreux que les gagnants.
3. Les pertes sont concentrees sur MON, LIT, KBONK, LDO, MORPHO, NEAR.
4. Le tournoi replay ne trouve pas encore de configuration robuste meilleure
   que `no_trade_baseline` sur cet extrait.
5. Le `closed-ledger-replay` causal confirme que les strategies testees sur
   les sorties closes ne battent pas `no_trade_baseline`.
6. Le cooldown par coin n'aide pas sur cet extrait car les pertes sont
   reparties sur plusieurs coins.
7. La session garde trop de positions ouvertes: la perte live vient aussi du
   latent sur positions non encore fermees.
8. Les anciennes analyses append-only pouvaient melanger des historiques longs
   avec le snapshot frais. Ce point est corrige: l'audit lit les logs frais par
   defaut et ne force l'append-only que via
   `HYPERSMART_PNL_AUDIT_PREFER_APPEND_ONLY=1`.

## Flags candidats a tester en replay A/B

Ces flags ne doivent pas etre actives automatiquement. Ils doivent ameliorer le
profit factor net sans lookahead avant toute activation.

| Flag | Valeur candidate | Pourquoi | Test |
|---|---:|---|---|
| `HYPERSMART_REQUIRE_PROFIT_FACTOR_REPLAY_GATE` | `true` | PF net < 1 | baseline vs gate PF |
| `HYPERSMART_MIN_PAPER_NOTIONAL_USDT` | `40` | couts trop lourds sur petits trades | no micro-trades |
| `HYPERSMART_MIN_EDGE_AFTER_COST_BPS` | `45` | edge restant trop faible apres frais | edge net 45 bps |
| `HYPERSMART_MIN_CONSENSUS_WALLETS` | `3` | winrate trop faible | consensus 3 |
| `HYPERSMART_LOSS_STREAK_COOLDOWN` | `3` | serie max de pertes = 3 | cooldown |
| `HYPERSMART_REPLAY_COIN_COOLDOWN_SET` | `MON,LIT,KBONK,LDO,MORPHO` | pertes concentrees | coin cooldown |
| `HYPERSMART_MAX_OPEN_PAPER_POSITIONS` | `5` | 23 positions ouvertes exposent trop la session | max open positions |
| `HYPERSMART_UNREALIZED_DRAWDOWN_GUARD_USDT` | `1.0` | latent ouvert negatif | drawdown guard |

## Decisions de conception

- Le bus GitHub ne doit plus etre une source directe de trades.
- Les repos GitHub restent une source de regles, pas des executants.
- Les evaluations GitHub shadow ne comptent plus comme trades acceptes.
- `simulation_pnl_ledger_latest.jsonl` devient l'export compact prioritaire du
  PnL, des que le serveur est relance avec le nouveau code.
- Les sorties fermees exposees par le status dashboard gardent maintenant
  `entry_context_found` et les metriques d'entree quand elles existent.
- `logs-analyze`, `ledger-pnl-calibration`, `closed-ledger-replay`,
  `optimize-profit-config` et `v19-pnl-audit` utilisent maintenant la meme
  verite comptable.

## Prochaine action exacte

1. Relancer `LANCER_HYPERSMART.cmd` pour generer
   `logs\logs à envoyer\simulation_pnl_ledger_latest.jsonl`.
2. Lancer un run de 15-30 minutes.
3. Executer `logs-analyze`, `ledger-pnl-calibration`, `closed-ledger-replay`
   et `optimize-profit-config` sur les logs frais.
4. Ne pas augmenter le nombre d'entrees tant que `closed-ledger-replay` choisit
   `no_trade_baseline`.
5. Tester d'abord `HYPERSMART_MAX_OPEN_PAPER_POSITIONS=5`,
   `HYPERSMART_MIN_PAPER_NOTIONAL_USDT=40`, `HYPERSMART_MIN_EDGE_AFTER_COST_BPS=45`
   et `HYPERSMART_MIN_CONSENSUS_WALLETS=3` en replay A/B.
6. Activer seulement les flags qui ameliorent le PF net en replay A/B.

Profit garanti: non. Cette page sert a eviter les faux positifs et a rendre le
PnL explicable.
