# Alina SmartFlow — HyperSmart Research Engine

**Read-only Hyperliquid smart-wallet observer with paper trading simulation & measurable research.**

A local-only observation engine for Hyperliquid mainnet. **No real execution ever.** Discovers interesting wallets, scores them by edge, and runs paper-only strategies to test profitability assumptions before they reach real money.

---

## 🚀 Quick Start

### For Windows (Portable)

```bash
# 1. Clone or extract
cd <project-folder>

# 2. Launch the bot
LANCER_HYPERSMART.cmd
```

The bot starts with 1000 USDT simulated capital and begins collecting read-only data from Hyperliquid. Dashboard runs at:

```
http://127.0.0.1:8794/v2
```

### To Run Backtests & Scenario Search

```bash
ANALYSER_BACKTESTS_REPLAYS.cmd quick
# or: full, deep, maximum
```

Results go to `runtime/replay/`.

---

## 🎯 Active Economic Scope

The canonical economic scope contains exactly three active paper-only families:

- **Copy-Vault** — wallet/vault-copy research and paper simulation.
- **Lead-Lag** — causal short-horizon lead-lag research.
- **Cross-Venue Dislocation** — executable cross-venue dislocation research.

**Carry is `DISABLED_BY_SCOPE`**. Historical carry/funding modules and measurements may remain for audit/backward compatibility, but Carry is not an active economic family and must never be promoted by the active scope.

## 🎯 What It Does

| Feature | Status | Notes |
|---------|--------|-------|
| **Wallet Discovery** | ✅ Live | Finds top Hyperliquid wallets by PnL & consistency |
| **Copy-Trading Simulation** | 🔒 Locked | Measures profitability, now **−7.97 bps** out-of-sample |
| **Funding Arbitrage** | 🟡 Standby | Historical/compatibility surface; Carry remains `DISABLED_BY_SCOPE` |
| **Cross-Venue Funding** | 🕐 Measuring | Historical measurement surface; active family is Cross-Venue Dislocation |
| **Liquidation Tracking** | ⏸️ Suspended | Collects clusters, awaits decision logic |
| **Paper Settlements** | ✅ Fixed | Funding accrual now matches **hourly reality** (not linear interpolation) |

---

## 📊 Current Measurements (July 22, 2026)

- **Carry Funding**: historical measurement only; Carry is `DISABLED_BY_SCOPE`  
- **Arbitrage**: Mid-price +0.54% → execution price −2.7% (illusion detected)  
- **Liquidations**: 231 clusters tracked over 31.6h; signal logic pending

→ See [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md) for up-to-date verdicts.

---

## 🛡️ Security — The One Line Red

**GOLDEN RULE: Read-only always. Paper only. No real execution.**

### Forbidden ❌
- Mainnet order execution  
- Private keys, seeds, signatures  
- Real deposit/withdrawal  
- Testnet executor (active)  
- LLM in hot decision path  
- Fake PnL presented as real

### Allowed ✅
- Public scraping (proxy rotation OK)  
- Hyperliquid `/info` REST read-only  
- Hyperliquid WebSocket read-only  
- CSV/JSON/TXT imports  
- SQLite local storage  
- Paper simulation & backtesting  
- Local dashboard (read-only)  
- Detailed logs to `logs/logs a envoyer/`

Run security checks anytime:

```powershell
python -m pytest -q tests/test_hypersmart_*.py
```

---

## 🏗️ Architecture

```
src/hl_observer/                    # Active runtime: CLI, UI, collection, edge, paper, backtests
├── strategies/
│   └── active_scope.py              # ← Economic authority (Scope V2-20260729)
├── paper_trading/
│   ├── core_decision.py
│   └── funding_settlement.py        # ← Hourly accrual (fixed 21/07)
├── collection/
│   └── hyperliquid_client.py        # ← Read-only API layer
└── backtesting/
    └── scenario_search.py           # ← Lab: anti-overfit research engine

hyper_smart_observer/               # Legacy (dYdX v4): do not extend
```

**Key modules:**

1. **Job A — Discovery**: Collect public wallets, score on PnL/consistency/drawdown, build shortlist.
2. **Job B — Simulation**: Read leader moves, compute edge, emit paper trades (never real).
3. **Job C — Dashboard**: Display PnL, positions, decisions, logs, health status.

---

## 🔄 Two Launchers, Two Jobs

### 1. Runtime (Daily Use)

```cmd
LANCER_HYPERSMART.cmd
```

- Starts CORE profile only (low resource)  
- Persistent poller + read-only leader collection  
- Reuses existing collectors  
- Default: `http://127.0.0.1:8794/v2`  
- Paper capital resets to 1000 USDT on launch

### 2. Research (Massive Backtests)

```cmd
ANALYSER_BACKTESTS_REPLAYS.cmd
```

- Local-only, resource-capped  
- Searches ~600 parameter combinations  
- Produces consolidated report: `RESULTATS_RECHERCHE.md`  
- Never auto-starts with the bot  
- Ctrl-C = **pause without loss** (all judgments saved, resume automatic)

Full docs: [`docs/LANCEURS_HYPERSMART.md`](docs/LANCEURS_HYPERSMART.md)

---

## 📋 Doctrine

```
OBSERVE FIRST
SCORE SECOND
SIMULATE LOCALLY THIRD

READ ONLY
PAPER ONLY
SIMULATION ONLY

DENY BY DEFAULT
SCORE IS NOT SIGNAL
PAPER TRADE IS NOT ORDER

HISTORICAL PnL IS NOT FUTURE PROFIT
NO GUARANTEED PROFIT
```

Every decision is logged and explainable. Every refusal is logged and explainable. No chart is synthetic. No promise is made.

---

## 📁 Portable Mode (Windows 10/11 x64)

The **entire folder** is portable. Move to a new PC without reinstalling Python:

1. Stop cleanly: `LANCER_HYPERSMART.cmd stop`
2. Copy the full folder (including hidden files)
3. Paste on new PC to short path (e.g., `C:\HyperSmart`)
4. Double-click `LANCER_HYPERSMART.cmd`

Embedded runtimes (`tools/python`, `tools/git`) follow the folder. All paths are relative. On first launch post-move, only machine identity and expired locks regenerate.

**Maintenance:**

```bash
LANCER_HYPERSMART.cmd portable-check
LANCER_HYPERSMART.cmd portable-install
LANCER_HYPERSMART.cmd portable-build
```

---

## 📈 Measurement & Reporting

### Morning Report

Auto-generated every 6h: `rapports/RAPPORT_DU_JOUR.md`

- PnL 24h by strategy  
- Position economics ($/day, amortization)  
- Collector health  
- Ledger lessons  
- Weekly refusal PnL  
- Today's TODO list

### The Lab (Scenario Search)

[`RECHERCHE-SCENARIO-REPLAY.cmd`] runs **4 phases**:

1. **Gather**: 438k+ candidates, 355k marks  
2. **Audit**: Data quality gates  
3. **Search**: ~600 combinations × 4 sub-populations (multi-fidelity, CPCV folds)  
4. **Report**: Per-module recommendation in French + JSON block

Anti-lie gates (never relaxed):
- Two disjoint time halves with embargo  
- Costs stressed ×1.5  
- Neighbor plateau  
- ≥30 trades per half  

**Classifications:**
- **OR** = net > 0 on ≥3/4 epochs → promoted  
- **ARGENT** = 1–2 epochs positive  

Output: `runtime/replay/RESULTATS_RECHERCHE.md`, `PEPITES.md`, `QUALITE_DONNEES.md`

---

## 🧪 Testing

### Quick Smoke Test

```powershell
python -m pytest -q tests/test_hypersmart_*.py
```

### Full Suite

```powershell
python -m pytest -q
```

Covers:
- No dYdX import in Hyperliquid runtime (isolation)  
- No real execution anywhere  
- Paper capital tracking  
- Edge calculation accuracy  
- Data freshness gates  

---

## 📚 Key Documents

| File | Purpose |
|------|---------|
| [`OBJECTIF.md`](OBJECTIF.md) | Condensed mandate (1 page) |
| [`CLAUDE.md`](CLAUDE.md) | Agent rules & code standards |
| [`AGENTS.md`](AGENTS.md) | Tools, guardrails, decision instruments |
| [`SECURITY.md`](SECURITY.md) | No-real-trade proofs |
| [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md) | **↑ Source of truth for current status** |
| [`docs/LANCEURS_HYPERSMART.md`](docs/LANCEURS_HYPERSMART.md) | Launcher guide |
| [`outils de test/README.md`](outils%20de%20test/README.md) | Test tools index (92 closed inquiries) |

---

## 🌟 The Why

One true north: **measurable edge without lying**.

- ✅ Measure everything on real data  
- ✅ Refuse what you can't prove  
- ✅ Explain every refusal  
- ✅ No synthetic charts  
- ✅ No promised gains  
- ✅ No real money at risk  

A positive PnL is not guaranteed. Losses are possible. The engine exists to **reduce bad decisions**, filter signals better, and explain losses—never to deceive.

---

## 💬 Logs to Send

Share diagnostic logs here:

```
logs/logs a envoyer/
```

Should explain:

- What opportunity was observed  
- Why the bot refused/accepted in paper  
- What data was missing or stale  
- What edge and costs were calculated  
- How paper PnL evolved  

These improve the engine without inventing gains.

---

## 🏠 Project Name Evolution

**HyperSmart** → **Alina SmartFlow — HyperSmart Research Engine**

The name shift preserves technical identity while reflecting evolution:
- **Alina** = software name  
- **SmartFlow** = flow analysis (signals, data, streams at core)

Historic names (`HYPERSMART_*`, scripts, modules) stay for backward compatibility.

---

## ⚡ Common Commands

```powershell
# Start the bot
LANCER_HYPERSMART.cmd

# Run research lab
ANALYSER_BACKTESTS_REPLAYS.cmd quick

# CLI help
python -m hl_observer --help

# Start UI only
python -m hl_observer ui

# Verify safety
python -m pytest -q tests/test_hypersmart_*.py
```

---

## 📝 License & Support

Questions? Check [`docs/CURRENT_STATE.md`](docs/CURRENT_STATE.md) first—it's the single source of truth for live status.

Contributions should follow [`CLAUDE.md`](CLAUDE.md) (rules) and [`AGENTS.md`](AGENTS.md) (tools/gates).
