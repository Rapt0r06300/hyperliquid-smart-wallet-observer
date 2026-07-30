# Audit V2 - Execution copy-vault canonique

Date : 2026-07-29  
Bloc : 12  
Commit source : `9562e45`

## Verdict

`DONE`. Les cohortes copy-vault autorisees ne calculent plus leurs fills ou leur
PnL avec un moteur economique parallele. Elles deleguent les operations
`OPEN`, `ADD`, `REDUCE` et `CLOSE` au `PaperEngine` canonique, qui produit les
mutations de position et les evenements du `PaperLedger`.

Les fichiers JSON historiques des cohortes restent des projections de
compatibilite. Ils ne sont pas une seconde source de verite economique.

## Cablage prouve

- `cohortes.py` selectionne l'evenement leader et demande une verite
  d'execution L2 complete et fraiche.
- `cohort_paper_bridge.py` transforme cette decision en `LeaderDelta`.
- `PaperEngine.apply_delta()` applique le book-walk, les frais, la mutation de
  position et le ledger.
- `PaperEngine.restore_position()` hydrate un etat deja comptabilise sans
  creer de fill, frais ou PnL supplementaire.
- Une entree sans `edge_remaining_bps` mesurable est refusee avec
  `EDGE_UNMEASURABLE`.
- Une entree sans wallet score mesurable est refusee avec
  `WALLET_SCORE_UNMEASURABLE`.
- Le chemin `RAW_PROBE` reste shadow et ne peut pas materialiser de PnL.

## Preuves de comportement

Le test d'integration avec un carnet Hyperliquid L2 enregistre verifie :

1. un carnet top-of-book incomplet est refuse ;
2. deux executions du meme intent sur le meme snapshot donnent le meme prix et
   le meme cout ;
3. le notional traverse plusieurs niveaux du carnet ;
4. un edge absent ne cree ni position ni PnL ;
5. une reduction leader de 25 % ferme exactement 25 % de la position paper ;
6. restaurer deux fois une position n'ajoute aucun evenement economique ;
7. les snapshots du ledger acceptes portent `strict_pnl_allowed=true`.

## Tests executes

```text
python -m pytest -q tests/test_cohortes.py tests/test_cohort_paper_bridge_v2.py tests/test_canonical_paper_execution_v2.py
30 passed in 1.79s
```

Controles supplementaires :

- compilation Python cible : OK ;
- Ruff `F821,F822,F823` : OK ;
- `git diff --check` : OK.

## Securite

- execution locale paper uniquement ;
- aucune route `/exchange` ;
- aucun ordre reel ;
- aucune cle privee ;
- aucune signature.
