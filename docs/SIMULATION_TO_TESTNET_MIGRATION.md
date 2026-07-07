# Migration Simulation -> Testnet

## Pourquoi changer

La simulation paper complete a permis de tester les idees, mais elle est devenue trop complexe :

- trop de modules de couts, exits, ledger, bridges GitHub ;
- risque de bugs de PnL ou de graphes ;
- risque de croire a une execution qui n'est pas celle d'un vrai exchange.

La nouvelle direction est plus concrete : observer le vrai marche en lecture seule, decider
localement, puis tester l'execution sur testnet avec de la fausse monnaie.

## Ce qui reste de la simulation locale

La simulation locale reste utile pour :

- tests unitaires ;
- fake adapters ;
- fallback hors reseau ;
- garde-fous ;
- replay/backtest offline ;
- verification de DecisionEngine/RiskEngine.

Elle ne doit plus etre le produit principal ni la source de verite finale du PnL.

## Ce qui devient testnet

Le nouveau chemin cible est :

```text
signal reel read-only
-> decision locale
-> guard testnet
-> ordre testnet
-> position testnet
-> fill testnet
-> PnL testnet
-> dashboard/logs
```

## Modules ajoutes

- `src/hl_observer/mainnet_readonly_observer/`
- `src/hl_observer/decision_engine/`
- `src/hl_observer/testnet/models.py`
- `src/hl_observer/testnet/adapters.py`
- `src/hl_observer/testnet/safety.py`
- `src/hl_observer/testnet/executor.py`
- `src/hl_observer/testnet/journal.py`
- `src/hl_observer/testnet/portfolio_tracker.py`
- `src/hl_observer/testnet/dashboard_payload.py`
- `src/hl_observer/testnet/commands.py`

## Modules legacy a isoler progressivement

Ne pas supprimer brutalement :

- `src/hl_observer/simulation/`
- `src/hl_observer/paper_trading/`
- anciens panels UI de simulation ;
- anciens replay/backtest paper.

Ils doivent rester disponibles, mais les nouveaux travaux doivent viser le flux testnet.

## Prochaine etape precise

Brancher un vrai transport signe Hyperliquid testnet dans `HyperliquidTestnetAdapter`, uniquement
apres :

1. revue des docs officielles Hyperliquid ;
2. stockage secret hors repo ;
3. tests de refus mainnet ;
4. dry-run fake adapter au vert ;
5. commande explicite `--confirm-testnet`.
