# HYPERSMART — ONE-RUN PROGRESS (OPUS 4.8) — 2026-07-30

> Fichier de reprise. Baseline du run : `654f243`. Aucun push (Flo pousse). 1 unité = 1 commit.
> Statuts : `DONE` (code+testé+prouvé+commit) · `IN_PROGRESS` · `SHADOW` · `BLOCKED_EXTERNAL` · `TODO`.

## Commits de ce run (au-dessus de 654f243)
| Bloc | SHA | Tests | Contenu |
|---|---|---|---|
| P0 | `a25b8ee` | doc | tasklist ACTIVE régénérée depuis active_scope, carry DISABLED_BY_SCOPE, archive + progress |
| P1A | `ece68f4` | 11 | builder marks liquidables (LONG@bid/SHORT@ask) → equity autoritaire mesurable, sinon UNMEASURABLE (prouvé sur le vrai PaperLedger) |
| P1B | `a38f28c` | 12 | contrat coûts/latence : guard anti-double-compte + taxonomie latence MEASURED/ASSUMED/UNMEASURABLE |
| P1C | `4198358` | 10 | identité économique (bundle refs, clés non ambiguës, episode_id déterministe, hash-chain intacte) |
| P1D | `2d78854` | +2 | scoreboard feed honore episode_id + publie la couverture d'identité |
| P2.1 | `512596a` | 19 | porte économique de promotion deny-by-default (17 portes §4.1) composée avec la porte de déploiement |
| P2.2 | `336b231` | 8 | ventilation N indépendant (metaorder/burst/wallet-coin-jour + LCB) réutilise scoring_robuste |

Baseline du run (déjà prouvé avant) : scoreboard_metrics `4c1ef42`, scoreboard_feeder `6404ae3`,
cost_components `654f243`.

## État par bloc
- **P0 DONE** (`a25b8ee`). active_scope faisait déjà foi ; docs réalignées.
- **P1 DONE** (A `ece68f4` / B `a38f28c` / C `4198358` / D `2d78854`).
  - Restant (câblage runtime, non bloquant) : passer `liquidatable_marks` depuis PaperEngine (le
    builder + la mécanique ledger sont prouvés) ; router la latence live via executable_replay
    plutôt que la taxe scalaire (le chemin causal existe déjà : `market_truth/executable_replay.py`).
- **P2 DONE** (2.1 `512596a` / 2.2 `336b231`). Restant P2.3 : brancher ces portes sur le ledger LIVE
  (produire réellement gross/costs/net/fill/capacity/latence par stratégie au runtime).
- P3 Data haute résolution — TODO. Live HL/Binance = **BLOCKED_EXTERNAL** (pas de réseau exchange en
  sandbox) ; faisable en pur : clock contract + universe manager + qualité/replay.
- P4 Global Observer à l'échelle — TODO (réutiliser G1-G3/H1-H2).
- P5 Wallet×Binance anticipation — TODO (le cœur reste BLOCKED_EXTERNAL sur data live ; logique pure OK).
- P6 TWAP residual — SHADOW/TODO. P8 microstructure — TODO. P9 cross-venue 2 jambes — TODO (bug capacité directionnelle à corriger).
- P10 maker — TODO. P11 lead-lag v2 — TODO. P12 wallet intelligence — TODO. P13 replay=forward — TODO (étend bloc 17).
- P14 statistiques/placebo — TODO (réutiliser robustesse_selection). P7 L4 — BLOCKED_EXTERNAL probable.
- P15 providers — BLOCKED_EXTERNAL (interfaces). P16 wiring — TODO. P17 dette — TODO (rejouer auditer_cablage).
- P18 CI/Windows — TODO (CI verte = après push Flo). P19 recette éco finale — TODO.

## Vérité économique (inchangée, à ne pas maquiller)
Aucune stratégie nette-positive à ce jour : raw_probe ≈ −5,9 bps ; markout brut ~2,6 bps < ~9 bps de
coûts. Contrainte dominante : alpha brut < coûts + résolution data. Les portes ci-dessus garantissent
qu'aucun faux PROMOTE ne passe ; l'edge réel reste à trouver (P3/P5/P6).
