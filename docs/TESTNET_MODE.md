# HyperSmart Testnet Mode

## Objectif

Le coeur cible d'HyperSmart n'est plus une simulation paper complexe qui tente d'imiter toute
l'exécution Hyperliquid. Le coeur cible devient :

```text
mainnet_readonly_observer
-> decision_engine
-> testnet safety guard
-> testnet_executor
-> testnet positions/fills/PNL
-> logs/dashboard
```

Le mainnet sert uniquement a observer les donnees reelles publiques/read-only : prix, carnets,
wallets, fills accessibles, funding et signaux. Toute execution externe doit rester sur testnet.

## Couches

### mainnet_readonly_observer

Package : `src/hl_observer/mainnet_readonly_observer/`

Responsabilites :
- lire `/info` mainnet uniquement ;
- lire `allMids`, `l2Book`, `clearinghouseState`, `userFills` si disponible ;
- retourner un etat partiel honnete si une source echoue ;
- ne jamais executer.

### decision_engine

Package : `src/hl_observer/decision_engine/`

Responsabilites :
- recevoir un signal/candidat ;
- verifier fraicheur, spread, slippage, liquidite, edge, score ;
- produire `ENTER`, `REDUCE`, `EXIT` ou `NO_TRADE` ;
- expliquer chaque decision par evidence.

### testnet_executor

Package : `src/hl_observer/testnet/`

Responsabilites :
- verifier tous les garde-fous testnet ;
- appeler un `TestnetExchangeAdapter` ;
- ouvrir/reduire/fermer uniquement sur testnet ;
- lire positions/fills/PNL testnet ;
- journaliser chaque refus et chaque resultat.

## Adapters

### FakeTestnetExchangeAdapter

Usage :
- tests unitaires ;
- preuve locale sans reseau ;
- validation de la chaine `SIGNAL -> DECISION -> ORDER -> POSITION -> PNL`.

Ce n'est pas le produit final.

### HyperliquidTestnetAdapter

Usage cible :
- execution testnet Hyperliquid avec fausse monnaie ;
- uniquement URL testnet ;
- desactive par defaut.

Etat actuel :

`READY_BUT_LOCKED_SIGNATURE_REQUIRED`

Le transport signe testnet n'est pas branche dans ce socle minimal. Cette limitation est
volontaire : aucune cle, signature ou wallet ne doit etre introduit sans sprint explicite,
revue de securite et tests de refus mainnet.

## Commandes

Preuve locale sans reseau :

```powershell
python -m hl_observer testnet-run --dry-confirmed --confirm-testnet --exchange fake --coin BTC --side long --notional 1 --limit-price 60000
```

Status :

```powershell
python -m hl_observer testnet-status --exchange fake
```

Adapter Hyperliquid verrouille :

```powershell
python -m hl_observer testnet-run --dry-confirmed --confirm-testnet --exchange hyperliquid --coin BTC --side long --notional 1 --limit-price 60000
```

Cette commande doit retourner un refus `READY_BUT_LOCKED_SIGNATURE_REQUIRED` tant que le transport
signe testnet n'est pas ajoute.

## Limites

- Le testnet peut avoir une liquidite differente du mainnet.
- Un PnL testnet n'est pas une preuve de rentabilite future.
- Les decisions doivent toujours utiliser les donnees reelles read-only disponibles et refuser si
  elles sont trop vieilles, incompletes ou contradictoires.
