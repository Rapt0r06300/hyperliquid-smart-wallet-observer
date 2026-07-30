# HYPERSMART — ONE-RUN PROGRESS (OPUS 4.8) — 2026-07-30

> Reprise. Baseline `654f243`. Aucun push (Flo pousse). 1 unité = 1 commit.

## PRIORITÉ 1 — câblage économique runtime (fait cette session)
| Bloc | SHA | Contenu |
|---|---|---|
| P1A câblage | `665e4f9` | PaperEngine propage les marks liquidables (`mark_to_market_depuis_bbo`) → `authoritative_equity_usdc` mesurable au runtime |
| P1B latency_truth | `d298d32` | latence AUTORITAIRE par exécution causale différée (décision→1ᵉʳ carnet à T+délai, coût = déplacement mid réel) ; scalaire = STRESS_ONLY ; sélection déterministe (replay=forward) |
| P1B exec_model | `99131a2` | mode CAUSAL : la taxe scalaire n'est plus repliée dans le fill quand un carnet causal existe (double compte supprimé) ; défaut SCALAR_STRESS inchangé (29 tests exec verts) |
| runtime→scoreboard | `10af127` | agrégateur des mesures runtime par stratégie (coûts, capacity, fill_ratio, latence p50/p95/p99, hedge latency/residual/unwind PnL/failed rate via P9.3) → alimente `scoreboard_feeder` ; absent = UNMEASURABLE ; prouvé bout-en-bout → net_bps |

## PRIORITÉ 0 (corrections, sessions précédentes)
P5.1 direction `07bab2a` · P3.4 subscriptions `ff8b65a` · P9.3 unwind `99cffd8` · frais uniques `bc441a2` ·
P3.2b orchestration Binance `5e86eca` · P1A câblage `665e4f9`.

## Ce qui manque encore (le plus profond)
- **Routage live de apply_delta** vers l'exécution causale (`executable_replay`) pour CHAQUE décision, même
  chemin replay/forward de bout en bout — édite le cœur `apply_delta` (le plus invasif).
- **Producteur runtime** qui émet réellement `couts_par_fill`/latences/fill/capacity/hedge par stratégie et
  appelle l'agrégateur (`scoreboard_runtime_metrics`) → `scoreboard_feeder` sur le ledger LIVE.
- **P3 collecteur** : brancher BinanceDepthBook/orchestrateur + Universe Manager au WS runtime réel
  (BLOCKED_EXTERNAL ici : device_bash sans réseau ; captures live = ton bot Windows).
- **P4 Global Observer à l'échelle** (node_fills_by_block/archives, streaming/checkpoints, milliers de wallets).
- P5 alpha data-live · P6 TWAP · P8 microstructure · P10 maker · P11 lead-lag v2 · P12 wallet intelligence ·
  P13 replay=forward · P14 anti-overfit · P7 L4 (BLOCKED_EXTERNAL) · P16 matrice · P17 dette · P18 CI · P19 recette.

## Vérité économique (inchangée)
Aucune stratégie nette-positive après coûts. Les rails sont désormais honnêtes de bout en bout : equity
liquidable réelle, latence causale (scalaire = stress), coûts sans double compte, direction correcte,
scoreboard alimenté par des mesures réelles avec UNMEASURABLE strict. L'edge réel reste à trouver sur data HF réelle.
