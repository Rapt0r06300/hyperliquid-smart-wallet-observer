# RÉCAPITULATIF COMPLET — HyperSmart Observer

_Généré le 22/07/2026 22:55 · 7/9 étapes vertes · durée totale 112.6 min._

## 🎯 PLAN D'ACTION POUR LE PnL (dérivé des mesures de CE run)

1. **carry** → LE CRIBLE A TOUT ÉLIMINÉ : sur les 4053 candidats, AUCUNE des ~600 combinaisons n'est même positive sur l'époque récente — ce module n'a pas de réglage, il a un verrou justifié. La voie passe par un autre mécanisme.
2. **copy** → LE CRIBLE A TOUT ÉLIMINÉ : sur les 522372 candidats, AUCUNE des ~600 combinaisons n'est même positive sur l'époque récente — ce module n'a pas de réglage, il a un verrou justifié. La voie passe par un autre mécanisme.
3. **arbitrage** → LE CRIBLE A TOUT ÉLIMINÉ : sur les 1164 candidats, AUCUNE des ~600 combinaisons n'est même positive sur l'époque récente — ce module n'a pas de réglage, il a un verrou justifié. La voie passe par un autre mécanisme.
4. **cross_venue** → RIEN À JUGER ce tour-ci.
5. **PnL 24 h** → le motif le plus coûteux est `ARB_STOP_ECART_AGGRAVE` (-1.9736 $) : c'est LUI qu'il faut comprendre avant d'ajouter quoi que ce soit.
6. **Cross-venue** → 79.5 h / 72 h → **le verdict est mûr, lance-le**

## 📈 Progression depuis le dernier passage

_Comparé au passage d'il y a 0.1 h._
- étapes vertes : 1 → **7** ▲
- PnL 24 h : -0.8759 → **-0.8759** =
- positions carry : 11 → **12** ▲
- tests : `2 failed, 800 passed` → `résumé introuvable`

## 💰 Où va l'argent (24 h)

- total : **-0.8759 $** sur 19 fermeture(s)
- par stratégie : `{'arbitrage': -0.8759}`
- par motif : `{'ARB_AGE_MAX_SANS_CONVERGENCE': 0.5726, 'ARB_CONVERGENCE_CAPTUREE': 0.525, 'ARB_STOP_ECART_AGGRAVE': -1.9736}`

## Étapes

| Étape | Statut | Durée | Détail |
|---|---|---|---|
| securite | ✅ OK | 7 s | no_real_execution_capable_package: ok |
| consolidation | ✅ OK | 13 s | } |
| tests | ✅ OK | 412 s | résumé introuvable |
| invariants | ✅ OK | 3 s | résumé introuvable |
| cablage | ✅ OK | 2 s | ------------------------------------------------------------------------------------------------ |
| donnees | ✅ OK | 5 s | rapport : runtime\replay\QUALITE_DONNEES.md |
| backtests | ⏱️ BUDGET | 900 s | BUDGET DEPASSE (900 s) |
| recherche | ⏱️ BUDGET | 5402 s | BUDGET DEPASSE (5400 s) |
| rapport_jour | ✅ OK | 10 s | **Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.** |

## 📦 Données disponibles (ce que le replay peut manger)

| source | lignes | Mo | étendue |
|---|---:|---:|---:|
| copy · candidats replay | 566566 | 275.52 | ? |
| copy · marks replay | 485711 | 28.51 | ? |
| carry · journal de scans | 7960 | 6.89 | 31.1 h |
| carry · ledger positions | 156 | 0.04 | 102.7 h |
| arbitrage · cross-venue | 135262 | 31.96 | 79.5 h |
| arbitrage · carnet bid/ask | 3188 | 1.02 | ? |
| copy · fills de leaders | 25111 | 3.52 | 37.7 h |
| copy · fills markout | 22130 | 4.71 | 37.3 h |
| liquidations · grappes | 610 | 0.09 | 62.6 h |

## Santé live (lecture seule)

- moteur : dernière décision il y a **93 s** · session `S20260722-164438-422d18`
- collecteurs (âge du dernier battement) : `{'carry-feeder': 100, 'marks-collector': 10, 'liq-collector': 145, 'venues-collector': 41, 'copy-whitelist': 451, 'rapport-quotidien': 498}`
- carry : **12 position(s)** ['AVAX', 'AZTEC', 'BTC', 'ETH', 'HYPE', 'MON', 'PURR', 'SOL', 'STABLE', 'VIRTUAL', 'XPL', 'ZEC'] · réalisé session -1.400914 $ · total historique -6.789962 $
- cross-venue : **79.5 h / 72 h**

## Sorties détaillées

<details><summary>securite — OK</summary>

```
no_secret_patterns: ok
env_not_committed: ok
no_forbidden_mainnet_order_method: ok
no_exchange_endpoint_in_runtime_source: ok
live_executor_disabled_exists: ok
mainnet_disabled_in_env_example: ok
security_tests_present: ok
no_real_execution_capable_package: ok
```
</details>

<details><summary>consolidation — OK</summary>

```
{
  "out": "runtime\\replay\\_merged",
  "counts": {
    "candidates.jsonl": 560384,
    "marks.jsonl": 474410
  },
  "depuis_la_derniere_fois": {
    "candidates.jsonl": 506,
    "marks.jsonl": 1036
  }
}
```
</details>

<details><summary>tests — OK</summary>

```
........................................ [ 11%]
........................................................................ [ 12%]
........................................................................ [ 13%]
........................................................................ [ 14%]
........................................................................ [ 15%]
........................................................................ [ 17%]
........................................................................ [ 18%]
........................................................................ [ 19%]
........................................................................ [ 20%]
................................................................
[COUVERTURE] joignables=529  couverts=526  NON TESTES=3  (99.4 %)  baseline=3
........ [ 22%]
........................................................................ [ 23%]
........................................................................ [ 24%]
........................................................................ [ 25%]
........................................................................ [ 27%]
........................................................................ [ 28%]
........................................................................ [ 29%]
........................................................................ [ 30%]
........................................................................ [ 31%]
........................................................................ [ 33%]
........................................................................ [ 34%]
........................................................................ [ 35%]
........................................................................ [ 36%]
........................................................................ [ 38%]
........................................................................ [ 39%]
........................................................................ [ 40%]
........................................................................ [ 41%]
........................................................................ [ 42%]
........................................................................ [ 44%]
........................................................................ [ 45%]
........................................................................ [ 46%]
........................................................................ [ 47%]
........................................................................ [ 49%]
........................................................................ [ 50%]
........................................................................ [ 51%]
........................................................................ [ 52%]
........................................................................ [ 54%]
........................................................................ [ 55%]
........................................................................ [ 56%]
........................................................................ [ 57%]
........................................................................ [ 58%]
........................................................................ [ 60%]
........................................................................ [ 61%]
........................................................................ [ 62%]
........................................................................ [ 63%]
........................................................................ [ 65%]
........................................................................ [ 66%]
........................................................................ [ 67%]
........................................................................ [ 68%]
........................................................................ [ 69%]
........................................................................ [ 71%]
........................................................................ [ 72%]
........................................................................ [ 73%]
........................................................................ [ 74%]
........................................................................ [ 76%]
........................................................................ [ 77%]
........................................................................ [ 78%]
........................................................................ [ 79%]
........................................................................ [ 81%]
........................................................................ [ 82%]
........................................................................ [ 83%]
........................................................................ [ 84%]
........................................................................ [ 85%]
........................................................................ [ 87%]
........................................................................ [ 88%]
........................................................................ [ 89%]
........................................................................ [ 90%]
........................................................................ [ 92%]
........................................................................ [ 93%]
........................................................................ [ 94%]
........................................................................ [ 95%]
........................................................................ [ 96%]
........................................................................ [ 98%]
........................................................................ [ 99%]
..................................                                       [100%]
5866 passed in 407.74s (0:06:47)
```
</details>

<details><summary>invariants — OK</summary>

```
..............                                                           [100%]
14 passed in 1.58s
```
</details>

<details><summary>cablage — OK</summary>

```
================================================================================================
  QUI EST BRANCHE SUR LA SIMULATION ? (AST — pas une impression)
  *Un module qui existe n'est pas un module qui garde. Un test n'est pas un branchement.*
================================================================================================

  🔒 LES GARDE-FOUS — ils doivent etre DANS LA PORTE (`noyau_unique.decider`)

    ✅ DANS LA PORTE    fees.hyperliquid_fees                          #543 — la source unique des frais
    ✅ DANS LA PORTE    risk.side_lock                                 #566 — 19/21 SHORT
    ✅ DANS LA PORTE    market.flow_toxicity                           #521 — le VPIN
    ✅ DANS LA PORTE    market.execution_constraints                   #576 — l'ordre est-il possible ?
    ✅ DANS LA PORTE    risk.session_gate                              #292b — les 11 gates V19
    ⚠️  runtime (1)    freshness.horloges                             #318 — la fraîcheur n'est plus une tautologie

  🔬 LES OUTILS DE MESURE — hors runtime, et **c'est LEGITIME**

    (outil)            backtesting.lead_lag                           #549 — mesure (0/66)
    (outil)            market.hlp_vault                               #544 — benchmark
    (outil)            market.hip3_markets                            #517 — mesure
    (outil)            market.oracle_lag                              #556 — mesure
    (outil)            backtesting.liquidation_cascade                #530 — mesure
    (outil)            collection.archive_s3                          #462 — collecte (payant : REFUSE)
    (outil)            funding.funding_cross_venue                    #542 — mesure
    (outil)            funding.snapshot_capture                       #531 — mesure
    (outil)            runtime.replay_shadow                          #302 — outil de vérité
    runtime(1)         runtime.session_and_bus                        #286 — outil de vérité
    (outil)            realtime.ws_resilience                         #314 — à brancher au collecteur
    (outil)            realtime.raw_spool                             #501 — à brancher au collecteur
    (outil)            backtesting.honest_metrics                     #571 — rapport
    (outil)            backtesting.intrabar                           #572 — backtest
    (outil)            backtesting.backtest_live_parity               #583 — backtest
    runtime(1)         testing.lookahead_detector                     #562 — outil
    (outil)            arbitrage.triangular_measure                   #296 — mesure
    runtime(1)         collection.funding_backfill                    #606 — collecte

------------------------------------------------------------------------------------------------
  ✅ Tous les garde-fous sont importes par le runtime.
     ⚠️ Les OUTILS restent hors runtime -- **et je le dis au lieu de le maquiller.**
------------------------------------------------------------------------------------------------
```
</details>

<details><summary>donnees — OK</summary>

```
{
 "n_candidats": 400000,
 "n_marks": 400000,
 "source": "runtime\\replay\\_merged",
 "defauts": [],
 "ts": 1784747442.7288105,
 "etiquetage_pct": 100.0,
 "label_brut_pct": 11.27,
 "ambigus_pct": 0.0,
 "horodatage_pct": 100.0,
 "couverture_pct": 91.04,
 "resolution_min": {
  "HYPE": 0.54,
  "BTC": 0.43,
  "SOL": 0.45,
  "ETH": 0.43,
  "ZEC": 0.57,
  "XPL": 0.63,
  "PURR": 0.6,
  "NEAR": 1.0,
  "BNB": 1.0,
  "PUMP": 0.95
 },
 "sauts_prix_absurdes": 0,
 "sauts_exemples": [],
 "doublons_pct": 0.0,
 "verdict": "PRÊT POUR LE REPLAY"
}

rapport : runtime\replay\QUALITE_DONNEES.md
```
</details>

<details><summary>backtests — BUDGET</summary>

```
BUDGET DEPASSE (900 s)
```
</details>

<details><summary>recherche — BUDGET</summary>

```
0, 'stress': 0.0}
  essai 1247 : {'sl': 50.0, 'tp': 200.0, 'horizon_min': 240.0, 'filtre': 'tous', 'filtres': {}} -> REJETE {'moitie_1': -177.9555, 'moitie_2': -310.227, 'stress': -727.3424}
  essai 1248 : {'sl': 50.0, 'tp': 200.0, 'horizon_min': 240.0, 'filtre': 'frais', 'filtres': {'age_max_ms': 10000}} -> REJETE {'moitie_1': 0.0, 'moitie_2': 0.0, 'stress': 0.0}
  essai 1249 : {'sl': 50.0, 'tp': 200.0, 'horizon_min': 240.0, 'filtre': 'consensus', 'filtres': {'min_consensus': 3}} -> REJETE {'moitie_1': 0.0, 'moitie_2': 0.0, 'stress': 0.0}
  essai 1250 : {'sl': 50.0, 'tp': 200.0, 'horizon_min': 240.0, 'filtre': 'frais_liquide', 'filtres': {'age_max_ms': 10000, 'min_liquidity': 0.55}} -> REJETE {'moitie_1': 0.0, 'moitie_2': 0.0, 'stress': 0.0}
  essai 1251 : {'sl': 50.0, 'tp': 300.0, 'horizon_min': 240.0, 'filtre': 'tous', 'filtres': {}} -> REJETE {'moitie_1': -177.9555, 'moitie_2': -305.1035, 'stress': -722.2189}
  essai 1252 : {'sl': 50.0, 'tp': 300.0, 'horizon_min': 240.0, 'filtre': 'frais', 'filtres': {'age_max_ms': 10000}} -> REJETE {'moitie_1': 0.0, 'moitie_2': 0.0, 'stress': 0.0}
  essai 1253 : {'sl': 50.0, 'tp': 300.0, 'horizon_min': 240.0, 'filtre': 'consensus', 'filtres': {'min_consensus': 3}} -> REJETE {'moitie_1': 0.0, 'moitie_2': 0.0, 'stress': 0.0}
  essai 1254 : {'sl': 50.0, 'tp': 300.0, 'horizon_min': 240.0, 'filtre': 'frais_liquide', 'filtres': {'age_max_ms': 10000, 'min_liquidity': 0.55}} -> REJETE {'moitie_1': 0.0, 'moitie_2': 0.0, 'stress': 0.0}
  essai 1255 : {'sl': 75.0, 'tp': 100.0, 'horizon_min': 240.0, 'filtre': 'tous', 'filtres': {}} -> REJETE {'moitie_1': 41.9263, 'moitie_2': -308.5514, 'stress': -505.7851}
  essai 1256 : {'sl': 75.0, 'tp': 100.0, 'horizon_min': 240.0, 'filtre': 'frais', 'filtres': {'age_max_ms': 10000}} -> REJETE {'moitie_1': 0.0, 'moitie_2': 0.0, 'stress': 0.0}
  essai 1257 : {'sl': 75.0, 'tp': 100.0, 'horizon_min': 240.0, 'filtre': 'consensus', 'filtres': {'min_consensus': 3}} -> REJETE {'moitie_1': 0.0, 'moitie_2': 0.0, 'stress': 0.0}
  essai 1258 : {'sl': 75.0, 'tp': 100.0, 'horizon_min': 240.0, 'filtre': 'frais_liquide', 'filtres': {'age_max_ms': 10000, 'min_liquidity': 0.55}} -> REJETE {'moitie_1': 0.0, 'moitie_2': 0.0, 'stress': 0.0}
  essai 1259 : {'sl': 75.0, 'tp': 150.0, 'horizon_min': 240.0, 'filtre': 'tous', 'filtres': {}} -> REJETE {'moitie_1': -163.5803, 'moitie_2': -299.198, 'stress': -701.9383}
  essai 1260 : {'sl': 75.0, 'tp': 150.0, 'horizon_min': 240.0, 'filtre': 'frais', 'filtres': {'age_max_ms': 10000}} -> REJETE {'moitie_1': 0.0, 'moitie_2': 0.0, 'stress': 0.0}
  essai 1261 : {'sl': 75.0, 'tp': 150.0, 'horizon_min': 240.0, 'filtre': 'consensus', 'filtres': {'min_consensus': 3}} -> REJETE {'moitie_1': 0.0, 'moitie_2': 0.0, 'stress': 0.0}
  essai 1262 : {'sl': 75.0, 'tp': 150.0, 'horizon_min': 240.0, 'filtre': 'frais_liquide', 'filtres': {'age_max_ms': 10000, 'min_liquidity': 0.55}} -> REJETE {'moitie_1': 0.0, 'moitie_2': 0.0, 'stress': 0.0}
  essai 1263 : {'sl': 75.0, 'tp': 200.0, 'horizon_min': 240.0, 'filtre': 'tous', 'filtres': {}} -> REJETE {'moitie_1': -165.4966, 'moitie_2': -302.0866, 'stress': -706.7432}
  … avancement 140/1200 configs
  essai 1264 : {'sl': 75.0, 'tp': 200.0, 'horizon_min': 240.0, 'filtre': 'frais', 'filtres': {'age_max_ms': 10000}} -> REJETE {'moitie_1': 0.0, 'moitie_2': 0.0, 'stress': 0.0}
  essai 1265 : {'sl': 75.0, 'tp': 200.0, 'horizon_min': 240.0, 'filtre': 'consensus', 'filtres': {'min_consensus': 3}} -> REJETE {'moitie_1': 0.0, 'moitie_2': 0.0, 'stress': 0.0}
  essai 1266 : {'sl': 75.0, 'tp': 200.0, 'horizon_min': 240.0, 'filtre': 'frais_liquide', 'filtres': {'age_max_ms': 10000, 'min_liquidity': 0.55}} -> REJETE {'moitie_1': 0.0, 'moitie_2': 0.0, 'stress': 0.0}
  essai 1267 : {'sl': 75.0, 'tp': 300.0, 'horizon_min': 240.0, 'filtre': 'tous', 'filtres': {}} -> REJETE {'moitie_1': -165.4966, 'moitie_2': -297.2112, 'stress': -701.8678}
  essai 1268 : {'sl': 75.0, 'tp': 300.0, 'horizon_min': 240.0, 'filtre': 'frais', 'filtres': {'age_max_ms': 10000}} -> REJETE {'moitie_1': 0.0, 'moitie_2': 0.0, 'stress': 0.0}
  essai 1269 : {'sl': 75.0, 'tp': 300.0, 'horizon_min': 240.0, 'filtre': 'consensus', 'filtres': {'min_consensus': 3}} -> REJETE {'moitie_1': 0.0, 'moitie_2': 0.0, 'stress': 0.0}
  essai 1270 : {'sl': 75.0, 'tp': 300.0, 'horizon_min': 240.0, 'filtre': 'frais_liquide', 'filtres': {'age_max_ms': 10000, 'min_liquidity': 0.55}} -> REJETE {'moitie_1': 0.0, 'moitie_2': 0.0, 'stress': 0.0}
  -- raffinage : 24 configs autour de 3 graine(s) --
=== module copy (2/4) ===
  crible multi-fidelite : 1200 configs sur les 12000 candidats les plus recents...
    crible 25/1200 (0 retenues)
    crible 50/1200 (0 retenues)
    crible 75/1200 (0 retenues)
    crible 100/1200 (0 retenues)
    crible 125/1200 (0 retenues)
    crible 150/1200 (0 retenues)
    crible 175/1200 (0 retenues)
    crible 200/1200 (0 retenues)
    crible 225/1200 (0 retenues)
    crible 250/1200 (0 retenues)
    crible 275/1200 (0 retenues)
    crible 300/1200 (0 retenues)
    crible 325/1200 (0 retenues)
    crible 350/1200 (0 retenues)
    crible 375/1200 (0 retenues)
    crible 400/1200 (0 retenues)
    crible 425/1200 (0 retenues)
    crible 450/1200 (0 retenues)
    crible 475/1200 (0 retenues)
    crible 500/1200 (0 retenues)
    crible 525/1200 (0 retenues)
    crible 550/1200 (0 retenues)
    crible 575/1200 (0 retenues)
    crible 600/1200 (0 retenues)
    crible 625/1200 (0 retenues)
    crible 650/1200 (0 retenues)
    crible 675/1200 (0 retenues)
    crible 700/1200 (0 retenues)
    crible 725/1200 (0 retenues)
    crible 750/1200 (0 retenues)
    crible 775/1200 (0 retenues)
    crible 800/1200 (0 retenues)
    crible 825/1200 (0 retenues)
    crible 850/1200 (0 retenues)
    crible 875/1200 (0 retenues)
    crible 900/1200 (0 retenues)
    crible 925/1200 (0 retenues)
    crible 950/1200 (0 retenues)
    crible 975/1200 (0 retenues)
    crible 1000/1200 (0 retenues)
    crible 1025/1200 (0 retenues)

BUDGET DEPASSE (5400 s)
```
</details>

<details><summary>rapport_jour — OK</summary>

```
0.0523$ | 0.1031$ | 0.3767$ | dans ~126 h |
| XPL | 77$ | 77$ | 0.125 | 0.0230$ | 0.0426$ | 0.0993$ | dans ~59 h |
| ZEC | 79$ | 79$ | 0.125 | 0.0238$ | 0.0272$ | 0.0605$ | dans ~33 h |

**Total : 0.8429 $/jour au taux courant · marge engagée 1334 $** (déploiement à comparer au capital — la réserve de 20 % est voulue).

## 9. Scan carry — univers, viables, et presque-viables (avec leur verrou)

_20 coin(s) perp∩spot, 6 VIABLE(S) (top-6 retenus par carry net)._

**Viables (6)** : BTC (+0.125b, liq 460k) · PURR (+0.125b, liq 21k) · XPL (+0.125b, liq 54k) · ZEC (+0.125b, liq 164k) · ETH (+0.079b, liq 393k) · SOL (+0.056b, liq 131k)

**Bloqués — et par QUOI (le verrou est une info, pas une fatalité) :**

- `PUMP` (+0.205b, liq 33k) → refuse jusqu'au levier le plus bas (1.0x) : LE_PIRE_MOUVEMENT_OBSERVE_AURAIT_LIQUIDE_LA_JAMBE_PERP [levier max venue 10x -> marge de maintenance 5.0 % ; pire hausse stressee 123 %]
- `AZTEC` (+0.125b, liq 3k) → break-even trop lent (292 h > 235 h) : le funding ne rembourse pas le cout d'entree assez vite -> on ATTEND (aucune saignee de couts)
- `BERA` (+0.125b, liq 0k) → base aberrante: perp 0.1879$ vs spot @117 0.001335$ (x141 -> pas de vrai spot jumelable)
- `ENA` (+0.125b, liq 1k) → spot HL trop mince : 1344 $ < 2500 $ (notionnel cible 500 x securite 5.0)
- `ETHFI` (+0.125b, liq 393k) → refuse jusqu'au levier le plus bas (1.0x) : LA_BASE_COUTE_PLUS_QUE_LE_FUNDING_NE_RAPPORTE
- `FARTCOIN` (+0.125b, liq 43k) → refuse jusqu'au levier le plus bas (1.0x) : LE_PIRE_MOUVEMENT_OBSERVE_AURAIT_LIQUIDE_LA_JAMBE_PERP [levier max venue 10x -> marge de maintenance 5.0 % ; pire hausse stressee 97 %]
- `HYPE` (+0.125b, liq 107k) → break-even trop lent (313 h > 235 h) : le funding ne rembourse pas le cout d'entree assez vite -> on ATTEND (aucune saignee de couts)
- `MEGA` (+0.125b, liq 0k) → spot HL trop mince : 0 $ < 2500 $ (notionnel cible 500 x securite 5.0)
- `MON` (+0.125b, liq 4k) → break-even trop lent (298 h > 235 h) : le funding ne rembourse pas le cout d'entree assez vite -> on ATTEND (aucune saignee de couts)
- `STABLE` (+0.125b, liq 25k) → break-even trop lent (538 h > 235 h) : le funding ne rembourse pas le cout d'entree assez vite -> on ATTEND (aucune saignee de couts)
- `TRUMP` (+0.125b, liq 0k) → base aberrante: perp 1.619$ vs spot @9 0.0004553$ (x3555 -> pas de vrai spot jumelable)
- `WLD` (+0.125b, liq 0k) → spot HL trop mince : 0 $ < 2500 $ (notionnel cible 500 x securite 5.0)

## 10. Où va le capital (allocation)

- règle : `marge ∝ gain_net_24h_bps ** 3, plafond 40 % par coin, plancher 25 $`
- capital alloué : **800.01 $** sur 6 coin(s) financé(s)
- rendement pondéré : **1.9226 bps/j** (part égale : 1.7355 bps/j -> **10.78 %** de mieux)
- meilleur coin : **BTC**

| coin | rendement net (bps/j) | marge cible ($) |
|---|---:|---:|
| BTC | 2.266 | 265.72 |
| PURR | 1.933 | 164.95 |
| ETH | 1.912 | 159.63 |
| SOL | 1.639 | 100.55 |
| ZEC | 1.417 | 64.98 |
| XPL | 1.246 | 44.18 |

**Positions sous-financées** (le renfort les comblera, une par jour et par position, sans jamais fermer) :

- PURR : 109.24 $ -> 164.95 $ (**+55.71 $**)

## 11. Qui sort du plancher de funding

- part globale du temps passé **au-dessus** du plancher : **0.0 %** (sur 15 coin(s) exploitables)
- meilleur coin : **AVAX**

| coin | temps hors plancher |
|---|---:|
| AVAX | 0.0 % |
| AZTEC | 0.0 % |
| BTC | 0.0 % |
| ETH | 0.0 % |
| ETHFI | 0.0 % |
| FARTCOIN | 0.0 % |
| HYPE | 0.0 % |
| MON | 0.0 % |
| PUMP | 0.0 % |
| PURR | 0.0 % |

_statistique DESCRIPTIVE d'un passé — jamais une probabilité de sortir demain._

## 12. Ce qui est déjà tranché (lois mesurées)

_16 loi(s) : 13 réfutée(s), 2 limite(s), 1 confirmée(s). Détail complet : `docs/LOIS_MESUREES.md`. Une loi se rouvre avec une DONNÉE neuve, pas un argument neuf._

- 🟢 **Carry delta-neutre (long spot + short perp) sur Hyperliquid** — le SEUL chiffre positif du projet : ~2 % APR mesuré sur HYPE (13/07) ; +0,35 $/j sur 11 positions au 21/07, coûts payés
- 🟠 **Le coût all-in d'un aller-retour d'arbitrage vaut 16 bps, pas 8** — le forfait `COUT_AR_BPS = 8` ne comptait que 2 exécutions sur 4 et oubliait les frais de la 2ᵉ venue. Coût all-in réel : **16,0 bps** (13 de frais + 2 de spread + 1 d'adverse selection). C'est un FAIT de coût — le moteur price désormais juste. Ce que ce coût implique pour la RENTABILITÉ est une autre question, tranchée trade par trade par les portes (cf. `arbitrage_cross_venue`)
- 🟠 **Arbitrer une dislocation de prix Hyperliquid ↔ Binance** — **réalisé PAPER : +0,54 $ sur 15 trades, 13 gagnants / 2 perdants** (les 2 perdants = MKR figé, désormais bloqué par la porte de vivacité). La population moyenne des signaux est négative (coût all-in 16 bps > convergence ~3,4 bps), MAIS le moteur ne trade que le sous-ensemble filtré (vivacité + convergence capturée) et ce sous-ensemble est positif. Échantillon petit — à confirmer

🔴 Réfutées (ne pas ré-ouvrir sans donnée neuve) : `arb_ecart_fige`, `carry_plancher_domine`, `copy_global`, `copy_leader_contrarien`, `latence`, `market_making_spread`, `spread_prix_du_risque`, `funding_perp_perp`, `couverture_meme_actif`, `lead_lag`, `rendement_negatif_domine`, `hlp_benchmark`, `zscore_au_plancher`

## 13. À FAIRE — ce que les données d'aujourd'hui désignent

- **Cross-venue : 72 h atteintes (79 h)** → lancer `python tools/mesurer_dispersion_venues.py` pour LE verdict (#178).
- Relances de collecteurs au compteur : {'carry-feeder': 1, 'marks-collector': 1, 'liq-collector': 1, 'venues-collector': 2, 'rapport-quotidien': 1} — si un compteur grimpe SEUL demain, c'est lui le malade (doc R5).
- Copy-whitelist : 3 leader(s) prouvé(s) → copy peut suivre CES leaders uniquement.
- Markout copy : 89.0% des fills mesures (22130/24860) — le pipeline nourrit la whitelist.
- Replay : 566566 candidats consolidés → `RECHERCHE-SCENARIO-REPLAY.cmd` a de quoi travailler (porte deux-moitiés + plateau).

---
**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
```
</details>

## Les autres rapports produits par ce lancement

- `runtime/replay/RESULTATS_RECHERCHE.md` — pépites + **recommandation par module**
- `runtime/replay/QUALITE_DONNEES.md` — santé des données du replay
- `rapports/RAPPORT_DU_JOUR.md` — PnL 24 h, économie des positions, à-faire du jour
- `resultat-audit.md` — audit de câblage détaillé (si l'étape a tourné)

---

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**


---

## 🤖 BOT-READY — 99/100 (A) · autonomie sûre : N2_TESTNET_VERROUILLE

_Plafond codé en dur : **N2 testnet verrouillé**. Le trading RÉEL est hors échelle — ce score ne peut jamais l'autoriser._

- maillon faible : **donnees_fraiches**
- no-real-trade intact : **oui**

| dimension | points | /max |
|---|---:|---:|
| securite_no_real_trade | 18.0 | 18 |
| pnl_reconcilie | 16.0 | 16 |
| donnees_fraiches | 14.6 | 16 |
| tests_verts | 14.0 | 14 |
| portes_cout_actives | 12.0 | 12 |
| kill_switch_cable | 10.0 | 10 |
| cablage_sain | 8.0 | 8 |
| journal_present | 6.0 | 6 |

## 🧠 COMPRENDRE LE PnL & TROUVER L'EDGE

### Où va l'argent
- PnL 24 h : **-0.8759 $** sur 19 fermeture(s).
- meilleure stratégie : **arbitrage** (-0.8759 $) · pire : **arbitrage** (-0.8759 $).
- motif le plus COÛTEUX : **ARB_STOP_ECART_AGGRAVE** (-1.9736 $) — c'est LUI à comprendre avant d'ajouter quoi que ce soit.

### L'edge existe-t-il ? (chaque ligne = une mesure réelle)
- **carry** : le funding BAT HLP 0.32% du temps (max 1.325 bps/h) sur 206 coins : le carry a une FENÊTRE — cibler ces coins/moments
- **arbitrage** (prix exécutable, modèle) : au prix EXECUTABLE (modele conservateur, cout 19.5 bps), la population NE survit PAS (253/592, net -11.8177 $) : le +0,54 $ mesure au MID etait probablement une illusion d'execution. Prochaine brique : capturer bid/ask+taille
- **liquidations** : 610 photographie(s) brute(s) de grappes ; après dédup il reste très peu d'événements DISTINCTS (~3 mesurés, cible 50) — verdict à l'accumulation de vraies purges (ciblage fort levier désormais actif)

**PROCHAINE ACTION : l'arbitrage ne survit pas au mid -> capturer le carnet réel (bid/ask + taille) avant d'y croire ; ne pas câbler l'arb en attendant.**

_Aucune promesse de PnL : ces lignes remontent aux mesures, y compris quand elles sont négatives. C'est le prix de la vérité._
