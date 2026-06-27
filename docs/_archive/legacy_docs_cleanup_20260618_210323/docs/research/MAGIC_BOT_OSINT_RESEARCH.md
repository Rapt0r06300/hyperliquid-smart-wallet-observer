# Magic Bot OSINT Research

Date: 2026-06-02

Status: research notes for a read-only Hyperliquid observer. This document does
not describe a real-money trading system and does not claim that any copy bot can
produce guaranteed profit.

## Executive Summary

The public "magic bot" story is technically credible only when reduced to a
boring but useful pipeline:

1. discover active wallets;
2. qualify leaders with historical and behavioral filters;
3. watch a small shortlist in near real time;
4. validate every event against freshness, liquidity, spread, slippage, fees and
   delay;
5. size a local simulation with strict caps;
6. log both accepted simulations and rejected no-trades.

The claims that such a bot "cannot lose", "exits just before losses", or
"guarantees profit" are marketing and must stay outside HyperSmart.

## Sources Found

| Source | Type | Reliability | What It Claims | Verifiable Part | Marketing / Unverifiable | HyperSmart Use |
|---|---|---:|---|---|---|---|
| Hyperliquid `/info` docs | Official docs | High | Read-only user state, fills, orders, mids | Payload types and rate policy | None | Source of REST data only |
| Hyperliquid WebSocket docs | Official docs | High | Public and user-specific streams | Subscription names and limits | None | Hot scanner shortlist only |
| Hyperliquid rate limit docs | Official docs | High | REST and WS limits | 1200 REST weight/min/IP, WS limits | None | Scan budget guardrails |
| LearnWithMeAI Claude Hyperliquid story | Article / tutorial | Medium | 3 jobs, top wallets, paper portfolio | 3-job architecture | Results and virality claims | Product architecture inspiration |
| Remote OpenClaw Claude + Polymarket article | Article | Medium | Claude should plan, not be conviction source | Architecture split | Trading profitability | LLM outside hot path |
| Polysyncer Polymarket bot article | Commercial article | Medium-low | Detect, validate, size, execute | Risk controls pattern | Performance and execution speed claims | Detect/validate/size/report only |
| Roswelly Polymarket copy bot page | Public project page | Medium-low | Poll target wallets rapidly | Polling architecture | Any profit implication | Polling inspiration, no execution |
| HyperTracker | Commercial analytics | Medium | Large Hyperliquid wallet coverage | Existence of wallet analytics market | Internal coverage numbers | Shows need for indexing/caching |
| HyData | Commercial API | Medium | Hyperliquid wallet analytics API | API category exists | Accuracy claims | Optional future data source, not dependency |
| GitHub Hyperliquid copy bot repos | Open source | Mixed | Real-time copy and sizing | Common implementation patterns | Safety and quality vary | Ideas only, no private-key code |
| Reddit Polymarket discussions | Community | Low | Delay kills copy edge; bots may be risky | Repeated concern about lag and malware | Anecdotal PnL claims | Risk warnings and test ideas |

## Claims Matrix Summary

| Claim | Verdict | Reason |
|---|---|---|
| Scan thousands of wallets | Partly reproducible | Public trades can discover many wallets, but user-specific streams are limited. |
| Track every good wallet in real time | Not reproducible safely | Hyperliquid user-specific WS limits make this impossible without a shortlist. |
| Copy within seconds | Reproducible only as simulation | Read-only WS can detect fresh fills; execution is forbidden in HyperSmart. |
| Exit before losses | Unverifiable / marketing | Future price movement is unknown. HyperSmart can only follow observed closes or local risk exits. |
| Guaranteed profit | False / forbidden | Historical PnL is not future profit. |
| Detect one-big-win wallets | Reproducible | Requires closedPnl history and concentration metrics. |
| Refuse stale signals | Reproducible | Compare event time, receipt time and current mid. |
| Measure edge after costs | Reproducible | `edge_remaining_bps` must subtract fees, spread, slippage, delay and liquidity penalties. |
| Multi-wallet consensus | Reproducible with caution | Same coin + same side + short window can strengthen confidence, but can also mean crowding. |
| No-trade report | Reproducible | Every refusal can be stored and shown in dashboard. |

## Reproducible Hyperliquid Features

- public trade scan for cold/warm wallet discovery;
- top-wallet shortlist with address validation;
- read-only `/info` snapshot collection;
- userFills WebSocket for a bounded shortlist;
- position delta reconstruction;
- consensus cluster detection;
- mandatory edge remaining calculation;
- local 1000 USDT simulation with position and exposure caps;
- missed opportunity logging;
- dashboard read-only reporting.

## Forbidden or Dangerous Features

- live order execution;
- `/exchange`;
- signatures;
- private keys;
- mainnet and active testnet executor;
- "copy this wallet" UI language;
- hiding negative PnL;
- simulating fake wins;
- scraping aggressively or bypassing site protections.

## Functions to Create or Strengthen

- scanner priority queue;
- scan budget guard;
- missed opportunity logger;
- wallet behavior profile;
- copyability score;
- no-trade report;
- source health and API health visibility;
- dashboard scan speed section;
- tests proving edge/refusal behavior.

## Test Ideas

- stale signal becomes missed opportunity;
- wallet skipped by budget is logged;
- consensus under four seconds increases confidence but does not bypass costs;
- one-big-win wallet is not auto-shortlisted;
- scanner refuses to exceed 10 user-specific WS wallets;
- paper simulation starts at 1000 USDT;
- no `/exchange`, signature or private key appears in runtime source.
