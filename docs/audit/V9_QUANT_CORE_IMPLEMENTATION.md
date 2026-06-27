# V9 — Implémentation du cœur quant (S0/S4–S7 + S5)

> Référence : `HYPERSMART_FUSION_ROADMAP_V9.md` (Hyperliquid uniquement, paper-only).
> Date : 2026-06-20. Venue : Hyperliquid. Mode : **simulation paper, read-only**.
> Ancrage : moteur exécutable `src/hl_observer/` (CLI `hl-observer`).

## 1. Périmètre livré

Ce lot implémente le **cerveau de décision quant** de la V9 : des modules
**purs, déterministes, testables hors-ligne**, tous **additifs** (aucun fichier
existant modifié, `cli.py`/`routes.py` jamais touchés). Objectif quant V9 :
*moins de trades, plus propres* — filtrer les mauvais signaux, ne garder que
les signaux frais, liquides, à **edge net positif** après coûts.

Règle dure respectée partout : **données réelles ou état vide honnête**.
Donnée absente/incertaine → `None` + `data_quality` basse, jamais fabriquée
(`NO_TRADE` par défaut). Un signal n'est jamais un ordre.

## 2. Modules créés

### S4 — Features marché (`src/hl_observer/features/`)
| Fichier | Rôle |
|---|---|
| `microstructure.py` | CVD (cumulative volume delta), RVOL, anchored-VWAP, impulse (bps), basis perp/index (bps), pression de liquidations |
| `volatility.py` | Sigma **fast / slow / blend** (log-returns), bucket LOW/NORMAL/HIGH/EXTREME |
| `orderbook_imbalance.py` | OBI autonome : imbalance de profondeur, top-of-book, pondéré par distance → biais LONG/SHORT/NEUTRAL |
| `quality_mode.py` | Qualité par flux **OK / DEGRADED / BAD** + agrégation *worst-of* (deny-by-default) |

### S6 — Edge net, fair value, fraîcheur, gates
| Fichier | Rôle |
|---|---|
| `edge/fair_value.py` | Fair value EMA (modes fast/smooth), edge en bps, détection **spike/dip** vs sigma |
| `edge/edge_calculator.py` | **Edge NET = brut − (frais + spread + slippage + latence + dégradation copie + funding) + rebate maker** ; décision ACCEPT/REJECT |
| `freshness/freshness_policy.py` | Refus signal trop vieux + **anti-jump** (n'applique qu'une révision strictement plus récente et non périmée) |
| `risk/exec_gates.py` | Gates V9 : `STALE=5 s`, `MIN_DEPTH=200`, `MAX_SPREAD_BPS=500`, `COOLDOWN=30 s` |

### S7 — Risque & sizing (`src/hl_observer/risk/`)
| Fichier | Rôle |
|---|---|
| `loss_halts.py` | Halts multi-couches : daily 5 % (60 min), monthly 15 % (30 j), drawdown 25 % depuis pic (7 j), trailing give-back |
| `adaptive_sizing.py` | Base 2 %, −20 %/perte consécutive, +10 %/gain consécutif, cap 5 %, plancher 0,5 %, pondéré par la confiance |
| `trade_floor.py` | Trade minimum $1.50 + edge requis pour couvrir frais aller-retour et coût fixe |
| `trade_circuit_breaker.py` | Halt après N gros trades dans une fenêtre glissante + **depth guard** |
| `var_cvar.py` | VaR/CVaR historiques (nearest-rank), régime de volatilité, fraction de **Kelly** plafonnée |

### S7 — Calibration (`src/hl_observer/calibration/`)
| Fichier | Rôle |
|---|---|
| `brier.py` | Score de Brier + **cumulative advantage** vs baseline (marché ou constante) |
| `confidence_buckets.py` | Win-rate réel par tranche de confiance + erreur de calibration pondérée |
| `model_market.py` | Différence modèle − marché + distribution par buckets + flag actionnable |
| `shadow_promote.py` | Promotion **shadow→primary** si `ready_for_promotion` ; **le shadow n'agit jamais** (invariant `shadow_acts=False`) |

### S5 — Scoring smart-money & fidélité de copie
| Fichier | Rôle |
|---|---|
| `scoring/smart_money_filter.py` | Seuils exacts : win-rate ≥ 60 %, PnL ≥ $500, profit-factor ≥ 1.5, consistency ≥ 70 %, one-big-win ≤ 30 % (deny-by-default) |
| `scoring/wallet_labels.py` | Labels **fondés sur l'évidence** : sans `evidence_count` suffisant → `UNVERIFIED` |
| `copy_fidelity/tracking_error.py` | Écart de copie par trade (bps), lag (ms), ratio de taille + RMS agrégé |
| `copy_fidelity/exec_quality.py` | Slippage réalisé vs attendu, fill ratio, note GOOD/ACCEPTABLE/POOR |

## 3. Tests

`tests/test_v9_quant_core.py` — **40 tests**, 100 % verts (Python 3.10/3.11).
Couvre : features + no-fabrication, edge net (accept / edge faible / edge négatif /
frais non doublés), fair value spike/dip, fraîcheur (stale refusé, no-timestamp
refusé, anti-jump), exec gates (stale/spread/depth/cooldown), loss halts,
adaptive sizing, trade floor, circuit breaker + depth guard, VaR/CVaR/Kelly,
Brier, buckets, model-market, shadow (non-acting), smart-money, labels (évidence
requise), tracking error long/short, exec quality, et **sécurité** (scan des
sources : 0 token d'exécution réelle).

Mapping aux tests obligatoires V9 : stale signal refusé ✔, edge trop faible
refusé ✔, liquidité trop faible refusée ✔, spread trop large refusé ✔, fees non
doublés ✔, PnL long/short (signe via tracking error & copy degradation) ✔,
config/deny-by-default ✔, dashboard read-only (modules sans I/O) ✔.

## 4. Sécurité — confirmation

- **0 ordre réel** : aucun module ne construit/n'envoie d'ordre ; grep des tokens
  interdits (`place_order`, `send_order`, `signTypedData`, `eth_sendTransaction`,
  `private_key`, `mnemonic`, …) = **0 occurrence**.
- **0 argent réel, 0 clé privée, 0 signature, 0 dépôt/retrait, 0 wallet-connect.**
- Tous les modules sont des transformations pures (entrée → décision/feature),
  sans I/O réseau ni état global.

## 5. Limites & prochaines étapes

- Sandbox = Python 3.10 ; ~31 modules de tests *préexistants* utilisent
  `datetime.UTC` (3.11+) et ne se collectent pas ici. **Sans rapport avec ce lot**
  (mes modules n'utilisent pas `datetime.UTC`). À valider sur la machine 3.11.
- Ces modules sont la **bibliothèque de décision** ; le câblage dans le pipeline
  runtime (`copy_mode`/`signals`/dashboard) reste à faire (lot suivant), en
  petits modules importés, sans toucher `cli.py`/`routes.py`.
- Slices data (S2/S3/S2bis : REST/WS/proxy pool) **déjà présentes** dans
  `src/hl_observer/collection/` — non retouchées.
