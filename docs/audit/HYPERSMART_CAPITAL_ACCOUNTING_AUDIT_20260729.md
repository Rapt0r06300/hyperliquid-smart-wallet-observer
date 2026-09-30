# Audit capital, marge, exposition et ROI - 2026-07-29

## Verdict

Le runtime paper distingue maintenant explicitement le capital de depart, le
cash libre, la marge immobilisee, l'exposition brute, l'exposition nette, les
notionnels par jambe, le levier, le PnL au mid et le PnL liquidable.

Le champ historique `max_total_exposure_usdt` reste accepte pour compatibilite,
mais son role reel est documente comme plafond de marge. Les nouveaux appels
peuvent utiliser `max_total_margin_usdt`. La methode
`_gross_exposure_usdt()` retourne desormais le notionnel brut reel.

## Contrat economique

Pour chaque position :

- `margin_locked_usd = gross_exposure_usd / leverage_effective`;
- `gross_exposure_usd` additionne toutes les jambes;
- `net_directional_exposure_usd` additionne les jambes signees;
- le PnL au mid reste informatif;
- le PnL liquidable et le ROI strict restent indisponibles sans prix de sortie
  executable;
- le turnover additionne les notionnels ouverts et fermes;
- la marge moyenne est mesuree sur les changements distincts d'etat de capital,
  et ne depend donc pas de la frequence de rafraichissement de l'interface.

## Preuve runtime

Commande :

```powershell
$env:PYTHONPATH='src'
.\portable_runtime\python\python.exe tools\audit_capital_accounting.py `
  --output runtime\audit\v2_capital_accounting\capital_accounting.json
```

Resultat :

- paire cross-venue `100 + 100 USD`;
- exposition brute `200 USD`;
- marge `20 USD` a `10x`;
- exposition directionnelle nette `0 USD`;
- cash libre `980 USD`;
- PnL liquidable et equity autoritaire calcules depuis le prix executable;
- apres reduction de 50 %, exposition brute `100 USD`, marge `10 USD`;
- turnover cumule `300 USD`;
- chaine d'evenements valide;
- statut global `PASS`.

## Tests

La regression paper/ledger elargie donne :

```text
281 passed, 1 warning in 28.49s
```

Les tests couvrent notamment les quatre denominateurs de ROI, les jambes
cross-venue, les prix liquidables absents, les reductions partielles, les
schemas de jambes incompatibles, le levier et les plafonds de marge.

## Securite

Ce bloc est strictement local et paper. Il ne contient aucun client d'ecriture,
aucune signature, aucune cle privee et aucun ordre reel.
