# Audit du book-walk L2 executable - 2026-07-29

## Verdict

Le moteur paper marche maintenant le seul cote executable du carnet :

- `BUY` consomme les asks, du prix le plus bas au plus haut ;
- `SELL` consomme les bids, du prix le plus haut au plus bas ;
- chaque niveau consomme est conserve dans un `BookLevelFill` immuable ;
- le VWAP provient de la quantite reellement remplie ;
- la profondeur absente reste absente ;
- un fill partiel ne devient jamais un full fill invente.

L'ancien `simulation.slippage_model` n'a plus sa propre formule. Il adapte le
resultat de `paper_trading.exec_model.simulate_depth_execution`.

## Preuve runtime

Commande :

```text
python tools/audit_executable_book_walk.py
  --output runtime/audit/v2_book_walk/executable_book_walk.json
```

Cas BUY :

- demande : `152 USDC` ;
- asks : `101 x 1`, puis `102 x 1` ;
- quantite remplie : `1.5` ;
- VWAP : `101.3333333333` ;
- niveaux : `101` puis `102` ;
- le bid volontairement favorable a `1` est ignore.

Cas SELL :

- demande : `149 USDC` ;
- bids tries : `100 x 0.5`, puis `99 x 1` ;
- quantite remplie : `1.5` ;
- VWAP : `99.3333333333` ;
- l'ask volontairement favorable a `1000` est ignore.

Cas profondeur insuffisante :

- demande : `500 USDC` ;
- profondeur ask visible : `101 USDC` ;
- rempli : `101 USDC` ;
- manque : `399 USDC` ;
- statut : `PARTIAL_FILL`.

Le script conclut `passed=true`, `paper_only=true` et
`real_execution=false`.

## Tests

Les tests de toutes les familles `test_execution*`, du simulateur historique
et du nouveau contrat L2 donnent :

```text
83 passed
```

Commit code : `5371b43`.

