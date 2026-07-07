# HyperSmart - Replay A/B des flags candidats (2026-07-07)

Scope: simulation locale Hyperliquid, lecture seule, aucun ordre reel.
Source: `python -m hl_observer.cli closed-ledger-replay --from-logs "logs/logs à envoyer"`
(41 trades clos, politique causale sans lookahead, train/validation/holdout).

## Resultats

| Config | Net total | Train | Validation | Trades | Verdict |
|---|---:|---:|---:|---:|---|
| observed_all_closed_trades | -1.771 | -0.861 | -1.019 | 41 | frais (1.97) > brut |
| no_trade_baseline | 0.000 | 0.000 | 0.000 | 0 | reference |
| coin_cooldown_after_loss_1/3/5 | -0.699 | -0.320 | -0.489 | 39 | ameliore mais reste negatif |
| entry_context_only | +0.114 | +0.108 | +0.006 | 13 | POSITIF train+validation, 13/13 gagnants |
| notional_at_least_40 | +0.114 | +0.108 | +0.006 | 13 | POSITIF, meme selection |

## Decisions

1. ACTIVE: `HYPERSMART_MIN_PAPER_NOTIONAL_USDT=40` (launcher + gate runtime
   `PAPER_NOTIONAL_BELOW_MINIMUM` dans `fusion_persistent_adapter`).
   Justification: filtre causal, train ET validation positifs, coherent avec le
   fee drag mesure (~59% du brut). Limite honnete: 13 trades selectionnes,
   validation +0.006 seulement, holdout vide. A re-verifier apres plus de data.
2. NON ACTIVE: cooldown par coin (reste negatif sur cet extrait).
3. NON ACTIVE: edge 45 bps / consensus 3 / max positions 5 / drawdown guard —
   soit deja actifs au launcher (consensus 3, edge 28/55), soit non mesurables
   par le replay actuel (les trades clos ne portent pas tous les champs). Ne pas
   activer sans preuve.
4. VALIDATION DIRECTION: `entry_context_only` positif = les trades AVEC preuve
   mesurable (edge/consensus/liquidite) sont le sous-ensemble rentable. Cela
   confirme la strategie de distillation vs bus direct.

Aucune promesse de PnL: un replay positif sur 13 trades n'est pas une garantie.
