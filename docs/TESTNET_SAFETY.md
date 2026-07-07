# Testnet Safety

## Regle principale

Mainnet reste lecture seule. Toute action externe doit etre refusee sauf si elle passe par
un adapter testnet explicite et verrouille.

## Flags obligatoires

Les valeurs sures par defaut sont :

```text
REAL_MAINNET_TRADING=false
TESTNET_ONLY=true
TESTNET_MODE=false
TESTNET_EXECUTION_ENABLED=false
REQUIRE_EXPLICIT_TESTNET_CONFIRMATION=true
CONFIRM_TESTNET_EXECUTION=false
TESTNET_EXCHANGE=hyperliquid
MAX_TESTNET_NOTIONAL=5
MAX_OPEN_TESTNET_POSITIONS=1
ALLOW_MAINNET_ORDER_SUBMISSION=false
```

Pour une action testnet externe, le guard exige :

- environnement `HL_ENV=testnet` ;
- `REAL_MAINNET_TRADING=false` ;
- `TESTNET_ONLY=true` ;
- `TESTNET_MODE=true` ;
- `TESTNET_EXECUTION_ENABLED=true` ;
- `CONFIRM_TESTNET_EXECUTION=true` ;
- option CLI `--confirm-testnet` ;
- URL adapter contenant `testnet` ;
- environnement adapter = `testnet` ;
- notional sous `MAX_TESTNET_NOTIONAL` ;
- positions ouvertes sous `MAX_OPEN_TESTNET_POSITIONS`.

## Refus journalises

Chaque refus du guard est ecrit dans :

```text
logs/logs à envoyer/testnet_decisions_latest.jsonl
```

Le journal doit expliquer :

- quel guard a bloque ;
- quelles raisons exactes ont ete declenchees ;
- quel signal/evidence a provoque la demande.

## Hyperliquid testnet

Le projet prepare `HyperliquidTestnetAdapter`, mais son etat actuel est :

```text
READY_BUT_LOCKED_SIGNATURE_REQUIRED
```

Cela signifie :

- l'URL testnet est controlee ;
- l'interface adapter existe ;
- les refus sont testes ;
- aucun transport signe n'est encore branche.

La prochaine etape sera un sprint separe pour brancher une signature testnet uniquement, sans
jamais exposer de secret dans le repo, les logs ou le dashboard.
