# Audit cross-venue non atomique - 2026-07-29

## Verdict

`DONE` pour le bloc 8 de la roadmap V2.

Commit de code : `0fb83c7` (`fix(cross-venue): model non-atomic leg execution`).

Le moteur paper ne suppose plus que deux jambes cross-venue sont executees au
meme instant et sur le meme carnet. Il applique la sequence suivante :

`DETECTED -> LEG1_FILLED/PARTIAL -> LEG2_FILLED/PARTIAL -> EXITING si residu -> MATCHED/CLOSED`

## Contrat implemente

- chaque jambe consomme son propre snapshot L2 causal ;
- un delai non nul interdit la reutilisation du snapshot de la jambe 1 ;
- la jambe 2 utilise son carnet observe apres la latence mesuree ;
- les distributions P50, P95 et P99 proviennent d'echantillons de latence ;
- le scenario P50 est le ledger principal ;
- P95 et P99 utilisent des ledgers isoles et ne contaminent pas le PnL principal ;
- les deux ordres de jambes sont supportes et testes ;
- la quantite de couverture est calculee dans l'actif, pas seulement en quote ;
- une jambe 2 partielle ou absente declenche un debouclage causal de la jambe 1 ;
- le reliquat non deboucle reste explicitement visible et invalide le resultat strict ;
- le PnL de residu vient d'un vrai couple de fills paper, jamais d'un malus arbitraire ;
- aucun client d'ecriture, ordre externe, secret ou signature n'existe dans ce module.

## Tests

La suite cible cross-venue, paper, liquidite, capital et ledger retourne
`57 passed`. Ruff retourne `All checks passed` sur les trois nouveaux fichiers.

## Preuve runtime read-only

Commande :

```powershell
$env:PYTHONPATH='src'
.\portable_runtime\python\python.exe tools\audit_cross_venue_non_atomic.py
```

Sources publiques lues :

- Hyperliquid mainnet `/info`, type `l2Book`, lecture seule ;
- Binance public depth, lecture seule.

La preuve a execute localement les deux ordres :

1. BUY Hyperliquid puis SELL Binance ;
2. BUY Binance puis SELL Hyperliquid.

Latences observees pendant ce run :

- Hyperliquid vers Binance : P50 `241 ms`, P95 `251.8 ms`, P99 `251.96 ms` ;
- Binance vers Hyperliquid : P50 `240 ms`, P95 `251.6 ms`, P99 `252.72 ms`.

Les deux ledgers ont retourne :

- `pnl_audit.status=TRUSTED` ;
- `event_chain_valid=true` ;
- snapshots de jambes distincts ;
- residu deboucle ou expose explicitement ;
- `paper_only=true` ;
- `real_execution=false`.

Le run n'a pas trouve un edge positif sur les carnets observes. Il conserve
donc les valeurs negatives (`-0.0508964443 USDC` et `-0.1330539039 USDC`) au
lieu de les embellir. Cette absence d'opportunite rentable est une preuve de
verite, pas un echec du mecanisme d'execution.

Rapport runtime :

`runtime/audit/v2_cross_venue_non_atomic/non_atomic_execution.json`

## Limites honnetes

- la preuve runtime est une observation ponctuelle, pas une estimation de
  rentabilite ;
- les carnets peuvent rester quasi stables entre P50, P95 et P99 ;
- le PnL final d'une paire encore ouverte exige ses marks liquidables ou sa
  fermeture ;
- le risque de venue, de funding et de convergence sera traite dans les blocs
  suivants, sans etre invente ici.

## Securite

Simulation locale uniquement. Aucune route d'ecriture, aucun ordre reel,
aucune cle privee et aucune signature.
