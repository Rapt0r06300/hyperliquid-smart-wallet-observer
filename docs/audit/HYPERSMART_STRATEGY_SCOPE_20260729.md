# HyperSmart Strategy Scope - 2026-07-29

## Autorité

Le manifeste exécutable est `src/hl_observer/strategies/active_scope.py`.
Il ne possède aucun override par variable d'environnement. Une modification
du périmètre économique exige donc une modification de code revue et testée.

## Périmètre économique paper

| Famille | Statut | Peut produire ordre/PnL paper canonique |
|---|---|---:|
| `cross_venue_dislocation` | ACTIVE | oui |
| `lead_lag` | ACTIVE | oui |
| `copy_vault` | ACTIVE | oui |
| `twap_metaorder` | SHADOW | non |
| `ofi_microprice` | SHADOW | non |
| `entity_consensus` | SHADOW | non |
| `funding_carry` | DISABLED | non |
| `triangular_arbitrage` | RESEARCH_ONLY | non |
| `market_making` | RESEARCH_ONLY | non |
| `external_github_profiles` | DISABLED | non |

Les détecteurs hors périmètre peuvent continuer à produire une observation
read-only. Ils ne peuvent créer ni position, ni frais, ni funding, ni PnL.

## Preuves

- `tests/test_active_strategy_scope_v2.py` vérifie l'allowlist exacte.
- Un ancien flag `HYPERSMART_FUNDING_ARB_PAPER=1` est explicitement refusé
  dans le runtime officiel.
- Un ancien scope du bus GitHub demandé à `all` reste sans exécution dans le
  runtime officiel.
- Les deux lanceurs officiels fixent `HYPERSMART_FUNDING_ARB_PAPER=0`.

Preuve CLI réelle exécutée avec les deux anciens flags forcés :

```text
python -m hl_observer refactor-fusion-run --dry-run
fusion_runtime_orders=1
fusion_price_discrepancies=1
fusion_funding_signals=1
fusion_triangular_opportunities=2
funding_arb.enabled=false
funding_arb.events=[]
external_profile_executions=[]
```

Le signal funding et les opportunités triangulaires restent donc visibles,
mais seule l'opportunité cross-venue autorisée atteint le chemin paper.

## Sécurité

Le périmètre reste intégralement paper/read-only. Aucun ordre réel, aucune
signature, aucune clé privée et aucun appel d'écriture ne sont ajoutés.
