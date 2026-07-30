# HYPERSMART — ONE-RUN PROGRESS (OPUS 4.8) — 2026-07-30

> Reprise. Baseline `654f243`. Aucun push (Flo pousse). 1 unité = 1 commit.

## PRIORITÉ 0 — corrections des faux DONE (continuation)
| Fix | SHA | Contenu |
|---|---|---|
| P5.1 direction | `07bab2a` | **bug corrigé** : direction = f(action, position_side) → CLOSE/REDUCE d'un SHORT = BUY. + dédup event_id/tid/oid, tolérance temporelle par horizon, N brut + N clusterisé, sélection DISCOVERY→FREEZE→OOS intacte |
| P3.4 subscriptions | `ff8b65a` | compte les **vraies** subscriptions (bbo/l2Book/trades par coin, userFills/userTwapSliceFills par user, +allMids), quotas réels 1000 subs / 10 users / 10 connexions, diff subscribe/unsubscribe dynamique |
| P9.3 unwind | `99cffd8` | l'unwind est **réellement simulé** contre carnet causal (prix VWAP sortie, slippage, frais, PnL net) ; agrégats scoreboard : failed_hedge_rate, residual_exposure, unwind_net_pnl |
| cross-venue frais | `bc441a2` | **source unique** `config/frais_venues` (env-surchargeable), P9.2/P9.3 branchés dessus, plus de hardcode concurrent |
| P3.2b Binance L2 | `5e86eca` | orchestration : buffer diffs WS avant snapshot → replay → **resync auto** sur DESYNC → publication canonique (exchange_ts/receive_ts/sequence/quality) |
| P1A câblage | `665e4f9` | **PaperEngine propage réellement** les marks liquidables (`mark_to_market_depuis_bbo`) → `authoritative_equity_usdc` mesurable au runtime, suit le liquidable (20 tests paper_engine verts) |

## Blocs du run précédent (rappel, au-dessus de 654f243)
P0 `a25b8ee` · P1A `ece68f4` · P1B `a38f28c` · P1C `4198358` · P1D `2d78854` · P2.1 `512596a` · P2.2 `336b231` ·
P3-clock `b781d54` · P2.3 `09a478e` · P3.2 `defee3c` · P3.4 `e4f3f0d` · P9.1 `ab73dda` · P5.1 `52fc384` ·
P9.2 `3863e71` · P9.3 `11808a0`.

## Reste Priorité 0 (câblage runtime profond — plus gros risque)
- **P1B latence** : remplacer la taxe scalaire `latency_cost_bps_per_sec` (exec_model) comme vérité finale par
  l'exécution causale différée (décision à T → premier carnet à T+delay). `market_truth/executable_replay.py`
  fait DÉJÀ l'exécution causale ; le câblage = router le moteur live dessus (édite exec_model, core).
- **scoreboard runtime-fed** : le feeder accepte déjà les mesures (`mesures_par_strategie`, P2.3) ; reste à
  produire ces mesures au runtime, stratégie par stratégie, et à consommer les métriques hedge (P9.3).

## Contraintes data live (factuel, pas de la paresse)
device_bash (pont PC) = **aucun accès réseau** ; le sandbox cloud ne peut pas appeler les exchanges (politique).
Donc les captures HL/Binance live doivent tourner dans TON bot (LANCER_HYPERSMART.cmd, Windows). La logique de
reconstruction/orchestration/anticipation est, elle, prouvée hors ligne sur données synthétiques.

## Vérité économique (inchangée)
Aucune stratégie nette-positive après coûts. Les portes + ces corrections garantissent qu'aucun faux PROMOTE,
aucune direction inversée, aucun coût sous-estimé ne peut fabriquer du vert.
