# Testnet Implementation Report

## Resume

HyperSmart migre vers un modele plus simple et plus verifiable :

```text
mainnet read-only -> decision locale -> guard testnet -> executor testnet -> positions/fills/PNL testnet
```

La simulation paper complete reste presente en legacy/minimal guardrail, mais elle n'est plus le
centre du produit.

## Livré

- `MainnetReadOnlyObserver` pour lire Hyperliquid mainnet via `/info` uniquement.
- `LocalDecisionEngine` pour transformer un `SignalCandidate` en decision locale explicable.
- `TestnetExchangeAdapter` generique.
- `FakeTestnetExchangeAdapter` pour tests unitaires sans reseau.
- `HyperliquidTestnetAdapter` prepare, strictement testnet, statut `READY_BUT_LOCKED_SIGNATURE_REQUIRED`.
- `TestnetSafetyGuard` fail-closed.
- `TestnetExecutor` avec open/reduce/close, retry, journal et lecture portfolio.
- `TestnetPortfolioTracker` et payload dashboard.
- CLI `testnet-run` et `testnet-status`.
- Tests dedies `tests/test_testnet_mode_controlled.py`.
- Tests de tranche verticale `tests/test_testnet_pipeline_slice.py` :
  mainnet read-only fake client -> decision locale -> requete testnet.

## Ce qui est volontairement verrouillé

Le vrai transport signe Hyperliquid testnet n'est pas active dans ce socle. Il manque
volontairement :

- stockage secret hors repo ;
- composant de signature testnet ;
- integration signer -> adapter ;
- tests d'integration reseau testnet ;
- verification manuelle faucet/mock funds.

Jusqu'a ce sprint futur, l'adapter Hyperliquid retourne `READY_BUT_LOCKED_SIGNATURE_REQUIRED`.

## Commande de preuve locale

```powershell
python -m hl_observer testnet-run --dry-confirmed --confirm-testnet --exchange fake --coin BTC --side long --notional 1 --limit-price 60000
```

Resultat attendu : statut `accepted`, adapter `fake_hyperliquid_testnet`, position testnet fake
ouverte dans le payload. Cette commande ne prouve que la chaine logique locale sans reseau.

## Commande Hyperliquid testnet verrouille

```powershell
python -m hl_observer testnet-run --dry-confirmed --confirm-testnet --exchange hyperliquid --coin BTC --side long --notional 1 --limit-price 60000
```

Resultat attendu tant que la signature testnet n'est pas branchee :
`READY_BUT_LOCKED_SIGNATURE_REQUIRED`.

## Commande de statut

```powershell
python -m hl_observer testnet-status --exchange fake
```

## Limite testnet

Hyperliquid est la premiere plateforme a cibler car elle expose un testnet public coherent avec
le besoin du projet. Sa liquidite testnet peut cependant differer du mainnet : le PnL testnet sert
a valider le chemin technique et les decisions, pas a promettre une performance future.

## Verification 2026-07-04

- `python -m pytest -q tests/test_testnet_pipeline_slice.py tests/test_testnet_mode_controlled.py tests/test_no_real_trade_foundations.py tests/test_safety_audit.py` -> 14 passed.
- `python -m hl_observer safety-audit` -> tous les checks OK.
- `python -m hl_observer audit-safety` -> tous les checks OK.
- `python -m hl_observer testnet-run --dry-confirmed --confirm-testnet --exchange fake ...` -> accepted.
- `python -m hl_observer testnet-run --dry-confirmed --confirm-testnet --exchange hyperliquid ...` -> rejected, `READY_BUT_LOCKED_SIGNATURE_REQUIRED`.
