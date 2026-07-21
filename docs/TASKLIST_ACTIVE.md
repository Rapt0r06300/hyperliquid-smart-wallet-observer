# TASKLIST ACTIVE — HyperSmart Observer

> **Reconstruite le 2026-07-21** à partir du runtime MESURÉ, pas des anciens rapports.
> Version précédente (12/07) archivée telle quelle :
> `docs/archive/TASKLIST_ACTIVE_20260712_archivee.md` — elle reste valide sur le fond
> (elle a réfuté la prémisse « le PnL est négatif à cause de la latence »).
>
> Preuves ligne à ligne : `docs/TASKLIST_EVIDENCE_MATRIX.md`
> Vérité du runtime : `docs/research/PROJECT_GROUND_TRUTH_2026.md`
> Terminé et archivé : `docs/archive/TASKLIST_DONE_ARCHIVE.md`
>
> **Règle d'admission** : une tâche ne quitte cette liste que si elle est `DONE_VERIFIED` —
> codée, **branchée**, testée, et prouvée par une mesure. « Testé » ne suffit pas : sur les
> 954 modules du projet, **28,6 % sont testés-SEULEMENT et 8,1 % orphelins**.

Statuts : `DONE_VERIFIED` · `DONE_BUT_REGRESSED` · `DONE_DOC_ONLY` · `PARTIALLY_DONE` ·
`CODED_NOT_WIRED` · `WIRED_NOT_USED` · `WIRED_NOT_TESTED` · `EXPERIMENTAL` · `OBSOLETE` ·
`DUPLICATE` · `BLOCKED_DATA` · `BLOCKED_DEPENDENCY` · `TODO_ACTIVE`

---

## P0 — Intégrité et vérité du PnL

| # | Tâche | Statut | Preuve / blocage |
|---|---|---|---|
| P0-1 | **Séparer funding ENCAISSÉ / funding ESTIMÉ.** `accruer()` crédite un prorata linéaire ; Hyperliquid règle au **sommet de l'heure**. Une estimation ne doit jamais s'appeler « encaissé ». | `DONE_VERIFIED` | `paper_trading/funding_settlement.py` + tests ; branché dans `etat_carry` et l'endpoint `/v2/carry` |
| P0-2 | **Une seule couche faisant autorité** — dashboard, rapport, ledger, laboratoire. | `PARTIALLY_DONE` | le réalisé vient du ledger pour tous ✅ ; le dashboard recompose encore le MtM de base côté endpoint → à descendre dans une couche commune |
| P0-3 | **Invariant anti-contournement des portes replay** — les portes existent, rien n'interdit de les désactiver. | `TODO_ACTIVE` | aucun test n'échoue si `stress ×1,5` ou `≥ 30 trades/moitié` est retiré |
| P0-4 | **Tests PnL scénarisés** : carry neutre parfait, hedge insuffisant, funding ±, basis ±, fermeture partielle, frais 2 jambes, rééquilibrage, mapping UBTC/BTC, arbitrage 2 jambes, copy LONG/SHORT, fill dupliqué, snapshot répété, donnée absente. | `PARTIALLY_DONE` | 7 invariants économiques (L1-L7, ~700 cas générés) couvrent une partie ; 8 scénarios manquent |

## P1 — Protéger et prouver le Carry (seul moteur qui ouvre)

| # | Tâche | Statut | Preuve / blocage |
|---|---|---|---|
| P1-1 | **Économie complète par position** : hedge ratio, delta résiduel USD, frais spot/perp séparés, spread et slippage par jambe, basis entrée/sortie, coût de rééquilibrage, durée, marge, rendement par $ de marge et par jour. | `TODO_ACTIVE` | `BLOCKED_DATA` partiel : le schéma de position ne stocke ni frais par jambe ni hedge ratio → enrichir le schéma d'abord |
| P1-2 | **Le carry est-il RÉELLEMENT delta-neutre ?** dérive du hedge ratio, exposition directionnelle résiduelle | `TODO_ACTIVE` | dépend de P1-1 |
| P1-3 | **Scorecard par coin** (`CARRY_PROVEN_POSITIVE` … `NEGATIVE_NET`) | `TODO_ACTIVE` | dépend de P1-1 |
| P1-4 | **Mapping Unit depuis les métadonnées officielles** au lieu du préfixe de nom | `TODO_ACTIVE` | défaut prouvé : refus `base aberrante ×141` (BERA), `×3511` (TRUMP) |
| P1-5 | Allocation du capital ∝ rendement net³ | `DONE_VERIFIED` | corrélation marge↔rendement passée de **−0,596** à positive ; **+23,9 %** sur les positions réelles ; 34 tests |
| P1-6 | Renfort de position sans churn (R1-R6, dont porte de risque identique à une ouverture) | `DONE_VERIFIED` | 27 tests dont bout-en-bout sur le chemin de production |
| P1-7 | Garde du plancher sur le z-score de funding | `DONE_VERIFIED` | `facteur_zscore(z, funding)` + branché dans le feeder |
| P1-8 | **Le seuil de prise de profit +0,05 $ est-il au-dessus du bruit comptable ?** | `TODO_ACTIVE` | jamais mesuré ; le bruit d'accrual vaut ~0,0147 $/h à notre notionnel |
| P1-9 | Backtest carry paramétrique sur scans enregistrés | `DONE_VERIFIED` | `carry_backtest.py`, 24 tests, **refuse** tout gain venant d'une baisse de sécurité |
| P1-10 | Journal de scans (~2 900 lignes/jour, refus compris) | `DONE_VERIFIED` | `carry_scan_recorder`, 25 tests, tourne en live |
| P1-11 | **Les 7-8 viables le restent-ils sur plusieurs périodes ?** | `BLOCKED_DATA` | 7 passes enregistrées ; il en faut ≥ 12 (seuil du backtest) |

## P2 — Clarifier les métriques affichées

| # | Tâche | Statut | Preuve |
|---|---|---|---|
| P2-1 | README « quatre modules » ≠ cinq lignes du tableau | `DONE_VERIFIED` | formulation dérivée du ledger : 1 moteur en production, 1 en guet, 1 verrouillé, 1 mesure, 1 suspendu |
| P2-2 | README seuil arbitrage 35 bps / coûts 22 bps | `DONE_VERIFIED` | corrigé en **15 / 8 bps**, conforme au code (`CONTRADICTED` avant) |
| P2-3 | README « funding couru (l'encaissé, stable) » | `DONE_VERIFIED` | les deux quantités sont nommées séparément |
| P2-4 | README Liquidations « 0 événement » | `DONE_VERIFIED` | **231 grappes** enregistrées : la collecte marche, c'est l'exploitation qui manque |
| P2-5 | Dashboard : `funding_settled` vs `funding_accrual_estimate` distincts | `DONE_VERIFIED` | endpoint + panneau |

## P3 — Terminer honnêtement le Cross-venue funding

| # | Tâche | Statut | Preuve / blocage |
|---|---|---|---|
| P3-1 | Figer les critères **avant** l'échéance | `DONE_VERIFIED` | `docs/research/CROSS_VENUE_FUNDING_72H_VERDICT.md` en état d'attente |
| P3-2 | Verdict à 72 h | `BLOCKED_DATA` | **48,5 h / 72 h — échéance dans ~23,5 h.** Aucune conclusion avant. |

## P4 — Arbitrage de dislocation

| # | Tâche | Statut | Preuve / blocage |
|---|---|---|---|
| P4-1 | **Prix EXÉCUTABLES au lieu de deux mids** (best_bid/ask, tailles, âge de quote, santé de source) | `TODO_ACTIVE` | défaut confirmé : `ecart_prix_bps = (mid_HL − mid_BIN)/mid_BIN` |
| P4-2 | Décomposer le coût all-in (frais ×2, spread ×2, slippage ×2, latence, funding, risque de jambe, incertitude) | `PARTIALLY_DONE` | `COUT_AR_BPS = 8` est un forfait 2 jambes ; la décomposition n'existe pas |
| P4-3 | Seuil **dynamique** `coût_estimé + marge` au lieu d'une constante | `TODO_ACTIVE` | dépend de P4-2 |
| P4-4 | Étude de **convergence avant** tout réglage de seuil | `DONE_VERIFIED` | −2,26 bps à 30 min sur 912 écarts, 64,9 % de réductions → verdict `LIMITE` |
| P4-5 | Cadence ×5 (300 s → 60 s) | `DONE_VERIFIED` | launchers + défaut du script |
| P4-6 | Passer le seuil de 15 à ~8 bps **si les données le confirment** | `BLOCKED_DATA` | 19 entrées seulement ; attendre ≥ 5 000 écarts |

## P5 — Réhabilitation individuelle du Copy

| # | Tâche | Statut | Preuve / blocage |
|---|---|---|---|
| P5-1 | Collecte C12 des fills de leaders | `DONE_VERIFIED` | 3 947 fills bruts sur 6,8 h |
| P5-2 | Markout forward par leader | `PARTIALLY_DONE` | 173 fills marqués, 12 leaders évalués, **aucun n'atteint 30 fills** |
| P5-3 | Scorecard complet par leader (edge brut/net, horizons, stabilité, copyability, LONG/SHORT, dépendance à un gros gain, taux de signaux incomplets) | `BLOCKED_DATA` | dépend de P5-2 |
| P5-4 | Première réhabilitation en **shadow paper**, jamais dans le moteur principal | `TODO_ACTIVE` | le mode shadow n'existe pas |

## P6 — Décision produit Liquidations

| # | Tâche | Statut | Preuve / blocage |
|---|---|---|---|
| P6-1 | Trancher : arrêter / changer d'univers de wallets / détecter depuis le marché | `TODO_ACTIVE` | 231 grappes existent ; ce qui manque est un **mécanisme de décision**, pas la donnée |

## P7 — Clarifier Grinder / Sniper

| # | Tâche | Statut | Preuve |
|---|---|---|---|
| P7-1 | Statut réel, prouvé par recherche exhaustive | `DONE_VERIFIED` | **Sniper** = outil de mesure (`backtesting/sniper_horizon_curve.py`), ne trade pas. **Grinder** = concept mort avec le market-making (0/29). SCALP / MOMENTUM / MEAN_REVERSION / MICROSTRUCTURE / WALLET_CLUSTER / FAST_SIGNAL / COPY_SIGNAL : **0 occurrence**. |
| P7-2 | Ne plus les présenter comme moteurs actifs | `DONE_VERIFIED` | aucune doc active ne le fait après cette passe |

## P8 — Fraîcheur et fiabilité des données

| # | Tâche | Statut | Preuve / blocage |
|---|---|---|---|
| P8-1 | `isSnapshot=true` distingué de `false` ; snapshot non rejoué comme événements | `TODO_ACTIVE` | non vérifié dans cette passe |
| P8-2 | Métriques p50/p95/p99 par source, trous, reconnexions, doublons, hors-ordre | `TODO_ACTIVE` | `data/reports/source_freshness_metrics.json` non produit |
| P8-3 | Superviseur qui relance les collecteurs morts | `DONE_VERIFIED` | `ops/superviseur_collecteurs.py`, compteurs au rapport |
| P8-4 | Anti-orphelins (les collecteurs meurent avec le moteur) | `DONE_VERIFIED` | `collecteur_doit_vivre.py` |
| P8-5 | Prioriser la fraîcheur **là où elle a une valeur économique** (arbitrage, fills copy, rééquilibrage carry) — pas partout | `PARTIALLY_DONE` | cadence arbitrage ×5 faite ; le reste non priorisé |

## P9 — Rapports et dashboard

| # | Tâche | Statut | Preuve |
|---|---|---|---|
| P9-1 | `TOUT-TESTER.cmd` : un seul lancement, récap complet | `DONE_VERIFIED` | 8 étapes + inventaire des données chiffré |
| P9-2 | Rapport du jour toutes les 6 h, écriture atomique | `DONE_VERIFIED` | 12 sections, jamais tronqué |
| P9-3 | Section « où va le capital » + positions sous-financées | `DONE_VERIFIED` | |
| P9-4 | Section « ce qui est déjà tranché » (13 lois mesurées) | `DONE_VERIFIED` | branchée aussi dans le chercheur de pépites |
| P9-5 | Ne jamais présenter une estimation comme un encaissement | `DONE_VERIFIED` | suit P0-1 |

## P10 — Nouvelles expériences

| # | Tâche | Statut | Blocage |
|---|---|---|---|
| P10-1 | Rien de neuf tant que P0 et P1 ne sont pas soldés | `BLOCKED_DEPENDENCY` | prouver l'existant avant d'ajouter |

---

## Rappels de discipline

- **Une loi mesurée ne se rouvre qu'avec une DONNÉE neuve**, jamais avec un argument neuf
  (`docs/LOIS_MESUREES.md`, 13 lois).
- **Le piège** : presque toute façon d'augmenter le PnL affiché revient à prendre plus de
  risque sans le mesurer. Un gain venant d'une baisse de sécurité est **refusé par construction**
  dans `carry_backtest.verdict()`.
- **Ne jamais promettre un PnL positif.**

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
