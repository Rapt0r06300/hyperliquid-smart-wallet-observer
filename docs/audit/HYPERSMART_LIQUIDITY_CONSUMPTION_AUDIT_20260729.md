# Audit de consommation de liquidite paper - 2026-07-29

## Verdict

Le runtime paper partage maintenant la profondeur L2 visible entre les
strategies. Une unite visible ne peut pas etre reutilisee par plusieurs plans
sur le meme etat de carnet.

## Contrat

La consommation est indexee par :

`(venue, coin, execution_side, price_level, snapshot_id)`

Un retry du meme `plan_id` retourne exactement le premier resultat sans
consommer une seconde fois. Une nouvelle liquidite n'apparait que lorsqu'un
nouveau `snapshot_id` causal est observe.

## Preuve runtime

Commande :

```powershell
$env:PYTHONPATH='src'
.\portable_runtime\python\python.exe tools\audit_liquidity_consumption.py `
  --output runtime\audit\v2_liquidity_consumption\liquidity_consumption.json
```

Resultat mesure sur une ask visible de `1 HYPE @ 100` :

- plan 1 demande 60 USDC et remplit 60 USDC (`0.6 HYPE`);
- plan 2 demande 60 USDC et remplit seulement 40 USDC (`0.4 HYPE`);
- le total rempli reste exactement `1 HYPE`;
- plan 3 est refuse avec `LIQUIDITY_ALREADY_CONSUMED`;
- le retry du plan 1 est idempotent (`replayed=true`);
- un nouveau snapshot permet de nouveau un fill de 60 USDC.

Le JSON de preuve porte `passed=true`, `paper_only=true` et
`real_execution=false`.

## Tests

```text
67 passed in 6.18s
```

Les tests couvrent l'overfill, le fill partiel, l'epuisement, l'idempotence,
l'independance BUY/SELL, l'independance des venues et le renouvellement par
snapshot.

## Securite

Ce composant ne contient aucun client reseau, aucune signature, aucune cle et
aucune route d'execution externe. Il modifie uniquement la verite d'execution
paper locale.
