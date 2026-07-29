# Audit du runtime lead-lag evenementiel - 2026-07-29

## Verdict

Le chemin paper lead-lag n'est plus cadence par un worker periodique. Chaque
trade Binance reel recu par `tools/collecter_bbo.py` est transmis
synchronement au runtime local, avec le dernier BBO Hyperliquid deja observe.

Le runtime reste fail-closed :

- preuve gelee strictement `PROMOTED` obligatoire ;
- demi-vie P95 explicite et mesuree obligatoire ;
- `alpha_half_life_p95_ms > end_to_end_latency_p95_ms + safety_margin_ms` ;
- BBO Hyperliquid causal, frais, non croise et avec tailles positives ;
- deduplication par `event_id` ;
- PaperEngine canonique uniquement ;
- `real_execution=false`.

## Preuve sur les donnees actuelles

L'artefact local courant est `REJECTED`. L'instanciation runtime retourne :

```text
enabled=false
real_execution=false
config_error=EVIDENCE_NOT_PROMOTED
positions=0
```

Le logiciel ne transforme donc pas une absence de preuve sub-seconde en faux
trade paper.

## Preuve par tests

Commande :

```powershell
$env:PYTHONPATH='src'
.\portable_runtime\python\python.exe -m pytest -q `
  tests/test_lead_lag_event_runtime_v2.py `
  tests/test_lead_lag_shadow.py `
  tests/test_lot14_corrections_integration.py `
  tests/test_causal_timestamp_contract_v2.py `
  tests/test_runtime_no_limbo.py
```

Resultat : `57 passed`.

Les tests prouvent le dispatch inline, l'absence de worker 60 secondes, le
budget demi-vie/latence, le refus d'une preuve rejetee, le refus d'un evenement
retarde, la deduplication et l'ecriture dans le ledger paper canonique.

## Commit

Code : `8024534` (`fix(lead-lag): execute paper decisions event-driven`).

