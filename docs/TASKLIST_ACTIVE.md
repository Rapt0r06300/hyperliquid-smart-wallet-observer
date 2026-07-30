# TASKLIST ACTIVE — HyperSmart Observer

> **Régénérée le 2026-07-30** depuis `src/hl_observer/strategies/active_scope.py` au HEAD réel
> (`654f243`), et alignée sur `HYPERSMART_ONE_RUN_MEGA_ROADMAP_OPUS48_2026-07-30.md`.
> Version précédente (carry-centrique, 21/07) archivée telle quelle :
> `docs/archive/TASKLIST_ACTIVE_20260730_archivee.md`.
>
> Suivi du run en cours : `docs/audit/HYPERSMART_OPUS48_ONE_RUN_PROGRESS_20260730.md`.
> Journal des commits : `docs/audit/HYPERSMART_COMMIT_LEDGER_20260729.md`.

**Règle d'admission (non négociable).** Une tâche n'est `DONE` que si elle est **codée +
branchée + testée + prouvée (runtime/replay) + commitée**. « Testé » seul ne suffit pas. Un
rapport sans code n'est admis que pour une étape d'analyse.

---

## 1. AUTORITÉ DE SCOPE — `active_scope.py` fait foi

`src/hl_observer/strategies/active_scope.py` est **l'unique** autorité ; aucune allowlist
concurrente. État au HEAD (vérifié) :

| Famille | Statut | Matérialise du PnL paper ? |
|---|---|---|
| `cross_venue_dislocation` | **ACTIVE** | oui |
| `lead_lag` | **ACTIVE** | oui |
| `copy_vault` | **ACTIVE** | oui |
| `twap_metaorder` | SHADOW | non |
| `ofi_microprice` | SHADOW | non |
| `entity_consensus` | SHADOW | non |
| `funding_carry` | **DISABLED_BY_SCOPE** | non |
| `triangular_arbitrage` | RESEARCH_ONLY | non |
| `market_making` | RESEARCH_ONLY | non |
| `external_github_profiles` | DISABLED | non |

**Carry/funding est définitivement hors scope actif.** Il peut rester pour l'historique et
l'audit ; il ne doit JAMAIS redevenir un signal, une position, une allocation, un PnL actif,
ni une ligne de scoreboard, ni une tâche qui bloque la recherche active. Aucune doc ne le
présente comme un moteur à optimiser.

---

## 2. VÉRITÉ ÉCONOMIQUE MESURÉE (à ne pas maquiller)

État réel au démarrage du run (source : commit ledger, blocs 18/19/E-G-H, edge-decay) :

- **Aucune stratégie n'est nette-positive après coûts.** Le `raw_probe` canonique mesure
  ~ **−5,9 bps/trade**, PF 0,66. Le markout brut wallet est **positif mais plafonne ~2,6 bps**
  et ne survit pas à ~9 bps de coûts (`AUCUN_HORIZON_NET_POSITIF`).
- **Contrainte dominante identifiée : alpha brut < coûts**, aggravée par une **résolution de
  données trop grossière** (cadence médiane du tape ~16 s → horizons courts non mesurables).
- Le PnL ULTRA positif visé ne peut venir que d'un edge **réellement plus grand que son coût
  total**. Les chantiers ci-dessous attaquent précisément alpha brut, coûts, latence, fill,
  capacité et data — dans cet esprit, jamais en fabriquant du vert.

---

## 3. WORKLIST ACTIVE — blocs P0→P19 (ordre d'exécution du run)

Statuts : `TODO` · `IN_PROGRESS` · `DONE` (= code+branché+testé+prouvé+commit) ·
`SHADOW` (recherche, non promouvable) · `BLOCKED_EXTERNAL` (data/infra hors sandbox).

| Bloc | Objet | Statut cible | Note |
|---|---|---|---|
| P0 | Vérité unique scope/docs | DONE | active_scope déjà conforme ; cette tasklist régénérée |
| P1 | Comptabilité/PnL/latence : une seule vérité (equity liquidable, coûts sans double compte, identité bout-en-bout) | TODO | bloc prioritaire avant tout alpha |
| P2 | Scoreboard qui ne peut pas mentir (PROMOTE deny-by-default, N indépendant réel, câblage runtime) | TODO | s'appuie sur scoreboard_metrics/feeder/cost_components |
| P3 | Data haute résolution simultanée HL+Binance (depth, clock contract, universe manager, dataset replayable) | TODO / live BLOCKED_EXTERNAL | logique pure + schémas testables ; collecte live hors sandbox |
| P4 | Global Wallet Observer à l'échelle (ingestion massive, DESYNC, discovery→frozen→OOS→forward) | TODO | réutiliser G1-G3/H1-H2 déjà livrés |
| P5 | Alpha Wallet×Binance anticipation (move_after−move_before, freeze→OOS→forward) | TODO | priorité recherche n°1 |
| P6 | TWAP/metaorder residual alpha (SHADOW) | SHADOW | réutiliser metaorder_shadow/twapId |
| P8 | Microstructure state-first (STATE→FLOW→SIGNAL, ablations) | TODO | |
| P9 | Cross-venue simulation 2 jambes (capacité directionnelle, round-trip, unwind) | TODO | corrige la capacité BBO actuelle |
| P10 | Maker queue-aware (jamais price touched=filled) | TODO | |
| P11 | Lead-lag event-driven v2 (choc enrichi) | TODO | |
| P12 | Wallet intelligence/copyability (entity clustering) | TODO | |
| P13 | Replay = forward (même code métier) | TODO | prolonge le bloc 17 (parité causale) |
| P14 | Statistiques / anti-overfit (placebo/DSR/PBO, registre d'essais) | TODO | réutiliser robustesse_selection |
| P7 | L4 / Order Intent observer | TODO / BLOCKED_EXTERNAL | interface provider ; node L4 hors sandbox |
| P15 | Providers / données externes optionnels | BLOCKED_EXTERNAL | interfaces seulement |
| P16 | Runtime producteur→consommateur (matrice, aucun flag ON sans producteur) | TODO | |
| P17 | Dette de câblage (rejouer auditer_cablage, HS-070→100) | TODO | |
| P18 | CI/Windows/robustesse (shards, fault injection) | TODO / CI verte BLOCKED_EXTERNAL | push = Flo |
| P19 | Mesure économique finale (scoreboard complet, scénarios, verdicts) | TODO | ne rien truquer ; KILL les morts |

---

## 4. RÈGLES D'INGÉNIERIE (rappel)

- 1 unité logique = 1 commit local ; code + tests indissociables ; **jamais** `git add -A` ;
  aucun `reset/clean/rebase` destructif ; **aucun push** (Flo pousse).
- PAPER / READ-ONLY : 0 ordre réel, 0 `/exchange`, 0 clé, 0 signature, 0 dépôt/retrait.
- Donnée absente/vieille/contradictoire → `UNMEASURABLE`/`NO_TRADE`, jamais 0 ni valeur inventée.
- Ne pas dupliquer : renforcer l'existant, pas de 3ᵉ architecture.
