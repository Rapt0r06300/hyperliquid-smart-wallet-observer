# Legacy Isolation Plan

## Runtime Split
| Area | Status | Reason | Replacement / Bridge | Tests |
|---|---|---|---|---|
| `src/hl_observer` | ACTIVE | Launcher and package scripts target this runtime. | Keep as primary. | Phase 0 tests, existing `tests/test_*`. |
| `hyper_smart_observer` | COMPATIBILITY | Historical CLI/safety commands still use it. | Keep bridge; do not expand new runtime logic there. | `--safety-check`, `--audit-safety`. |
| `hyper_smart_observer/dydx_v4` | LEGACY_DORMANT | User moved runtime to Hyperliquid. | Keep mockable/dormant only. | Existing dYdX tests may remain. |
| External GitHub clones/profiles | RESEARCH_OR_ADAPTER | Mixed domains and licenses; cannot become uncontrolled runtime engines. | Port behavior through documented adapters and paper ledger. | GitHub mapping docs + no-real-trade tests. |
| Old Markdown roadmaps | HISTORICAL | Useful context but not runtime truth. | Keep archived/linked; Phase 0/V12/V14 docs define current direction. | Docs existence tests. |

## Migration Rules
- Do not delete legacy folders without a separate migration PR/session.
- New code goes under `src/hl_observer`.
- Old modules may be wrapped by adapters, but cannot bypass RiskEngine or PaperLedger.
- Dashboard PnL must converge on ledger/accounting truth.

## What Replaces Legacy PnL Counters
The new `src/hl_observer/simulation/paper_ledger.py` is the Phase 0 accounting base. It tracks cash, position state, fees, funding, realized/unrealized PnL, equity, drawdown, and reconciliation warnings.

## Next Migration
Wire `PaperEngine.apply_delta` and UI status payloads to append/consume ledger events while keeping the existing session memory.

---

## Correction 2026-07-02 (STEP 2, architecte senior) — statut réel de `dydx_v4`

**Constat vérifié** : `dydx_v4` n'est PAS dormant. Chaîne d'appel prouvée :
`python -m hl_observer ui` → `src/hl_observer/ui/dydx_routes.py` (`from hyper_smart_observer.dydx_v4.engine import get_engine`) → `hyper_smart_observer/dydx_v4/engine.py` (`from hyper_smart_observer.dydx_v4.live_observer import DydxLiveObserver`). C'est ce moteur qui produit le PnL paper affiché.

**Décision d'architecture (reclassement)** :
| Zone | Ancien statut | Nouveau statut | Justification |
|---|---|---|---|
| `hyper_smart_observer/dydx_v4/engine.py` + `live_observer.py` | LEGACY_DORMANT | **ACTIVE_BRIDGE (moteur PnL runtime)** | Consommé par l'UI active ; source du PnL réel. On le renforce, on ne le casse pas. |
| `hyper_smart_observer/dydx_v4/*` (autres) | LEGACY_DORMANT | **ACTIVE_BRIDGE (support du moteur)** | Dépendances directes du moteur (scoring, selection, signals dydx). |
| `hyper_smart_observer/` hors `dydx_v4` | COMPATIBILITY | **LEGACY_ISOLATED** | CLI/safety historiques ; ne pas étendre. |
| `src/hl_observer/paper_trading` + `ledger` | base comptable | **SOURCE DE VÉRITÉ COMPTABLE** | L'audit y réconcilie déjà ; le moteur runtime doit y converger. |

**Règle de convergence (garde-fou)** : le moteur `dydx_v4` peut rester le producteur runtime du PnL, mais tout PnL affiché/audité doit se réconcilier avec le PaperLedger événementiel de `src/hl_observer`. La migration cible = déplacer progressivement la comptabilité de `live_observer` vers le ledger, sans interruption de service (aucune suppression brutale).

**Nommage** : ne PAS créer `monitor/` ni `decision/`. Mapper vers l'existant (`hyperliquid/`+`realtime/`+`collection/` ; `signals/`+`risk/`+`edge/`). Voir `docs/release/STEP_0_RECONNAISSANCE.md`.

---

## RECTIFICATION 2026-07-02 (bis) — venue = HYPERLIQUID, pas dYdX

**Correction d'une erreur d'analyse précédente.** Vérifié :
- `hyper_smart_observer/dydx_v4/config.py` pointe sur `indexer.dydx.trade` / `indexer.v4testnet.dydx.exchange` → c'est du **vrai dYdX**, PAS Hyperliquid.
- La **simulation Hyperliquid réelle** (celle que lance `LANCER_HYPERSMART.cmd`) vit dans **`src/hl_observer`** : collecte `hyperliquid/` + `collection/` (endpoints Hyperliquid `/info`+WS), moteur d'edge `src/hl_observer/edge/edge_calculator.py` (`compute_net_edge`, min_edge défaut 30 bps), PnL `paper_trading/` marqué `FAST_STATUS_MARK_TO_MARKET_HYPERLIQUID`, exits `paper_trading/sltp_runtime.py`.
- `src/hl_observer/ui/dydx_routes.py` (blueprint `/api/dydx/…`) importe le moteur dYdX = **panneau secondaire dYdX**, séparé du dashboard de simulation Hyperliquid.

**Statut corrigé** :
| Zone | Statut corrigé |
|---|---|
| `src/hl_observer` (edge/paper_trading/hyperliquid/collection) | **RUNTIME HYPERLIQUID ACTIF — cible de tout nouveau travail** |
| `hyper_smart_observer/dydx_v4/*` | **LEGACY dYdX réel (endpoints dydx.trade)** — hors simulation Hyperliquid ; ne pas y porter d'idées destinées à la simu |
| `hyper_smart_observer/` hors dydx_v4 | LEGACY_ISOLATED |

**Le plancher profit-USD existe déjà côté Hyperliquid** (`HYPERSMART_SIMULATION_MIN_EXPECTED_EDGE_USDT`, reason `EXPECTED_NET_EDGE_TOO_SMALL_AFTER_COSTS`, `src/hl_observer/ui/routes.py`). Le port fait dans `dydx_v4/edge_calculator.py` est donc **redondant/mal ciblé** : conservé (inoffensif, défaut off, testé) mais **toute intégration d'idées GitHub visera désormais `src/hl_observer/edge/` + `paper_trading/`**.
