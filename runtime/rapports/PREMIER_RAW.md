# Premier RAW_PROBE — OPEN/CLOSE réel (paper, NON_VALIDÉE)

## OUVERTURE — paire 0x07fd993f0fa3a185f7207adccd29f7a87404689d|ONDO (ONDO)
- vault : 0x07fd993f0fa3a185f7207adccd29f7a87404689d
- sens : SHORT · notional 5.0 $
- prix d'entrée (L2) : 0.40438 · source L2 : on_demand
- edge estimé : None (RAW = NON_VALIDÉE, aucun edge requis)
- latences monotones (ms) : WS→déc 7.9 · déc→L2 1402.4 · L2→open 2.7 · WS→open 1412.9
- âge événement à la décision (skew HL possible) : 317 ms
- **âge RÉEL à l'exécution paper (total fill→open)** : None ms
- cycle_id : None · open_run_id : run-2f7a72fa293f · statut : NON_VALIDEE
- trigger_version : None · **config_hash : …** · commit : 

## CLÔTURE — HORIZON_ATTEINT
- cycle_id : None · open_run_id → close_run_id : None → None (le cycle traverse les redémarrages)
- config_hash (recopié de l'OPEN) : … ✓ identique à l'OPEN
- prix de sortie : 0.40154 · trigger_version (stockée à l'OPEN) : None
- MFE / MAE (bps) : 80.246 / 0.0
- PnL réalisé : 0.027997 $ · ROI : 0.56 %
- PLACEBO même coin/instant : ret_coin None bps · ret_marché(BTC) None bps · placebo None bps · **alpha vs marché None bps**

_Sécurité : paper only · real_execution=false · 0 ordre réel · 0 clé · 0 signature._