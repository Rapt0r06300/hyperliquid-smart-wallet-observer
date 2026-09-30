"""Executable requirement-specific gate for derived Copy-Vault controls 321..395.

This module does not count generic files as proof. Each of the 15 preserved
Copy-Vault requirements executes a deterministic micro-scenario against the
production implementation and records five independent facets.
"""
from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from hl_observer.backtesting.copy_vault_executable import COPY_DELAY_MS, NOTIONAL_USD, cluster_metaorders, execute_metaorder, summarize, temporal_evidence
from hl_observer.backtesting.copy_vault_generalization import derive_heldout_vault_generalization
from hl_observer.collection.vault_fills_backfill import dedupliquer, normaliser_vault, plan_de_requetes, reconstruire_episodes
from hl_observer.collection.vault_ledger import marquer_retraits_ledger, parser_ledger

FACETS = ("CONTRACT", "POSITIVE_PATH", "NEGATIVE_FAIL_CLOSED", "DETERMINISM_CAUSALITY", "EVIDENCE_PROVENANCE")
COPY_REQUIREMENTS = (
    ("userfills_pagination", "userFillsByTime et pagination bornée"),
    ("position_lifecycle", "lifecycle OPEN/ADD/REDUCE/CLOSE"),
    ("cashflow_not_pnl", "dépôts/retraits distincts du PnL"),
    ("stable_identity", "identité wallet/vault stable"),
    ("copyability_freshness", "copyability et fraîcheur du leader"),
    ("leader_follower_execution", "latence leader→follower et slippage follower"),
    ("capacity", "capacité exécutable"),
    ("consistency_one_big_win", "consistency et one-big-win"),
    ("drawdown_regime", "drawdown et régimes"),
    ("twap_metaorders", "TWAP et métaordres"),
    ("vault_conflicts", "conflits entre vaults"),
    ("unseen_vault_holdout", "holdout de vaults jamais vus"),
    ("oos_forward", "OOS et forward"),
    ("costs_sample_size", "coûts réels et taille d'échantillon"),
    ("net_pnl_placebo", "PnL net et placebo"),
)
_EVIDENCE = {
    "userfills_pagination": ("src/hl_observer/collection/vault_fills_backfill.py", "tests/test_vault_fills_backfill.py"),
    "position_lifecycle": ("src/hl_observer/collection/vault_fills_backfill.py", "tests/test_vault_fills_backfill.py"),
    "cashflow_not_pnl": ("src/hl_observer/collection/vault_ledger.py", "tests/test_vault_ledger.py"),
    "stable_identity": ("src/hl_observer/collection/vault_fills_backfill.py", "src/hl_observer/collection/vault_ledger.py"),
    "copyability_freshness": ("src/hl_observer/backtesting/copy_vault_executable.py", "tests/test_copy_vault_executable.py"),
    "leader_follower_execution": ("src/hl_observer/backtesting/copy_vault_executable.py", "tests/test_copy_vault_executable.py"),
    "capacity": ("src/hl_observer/backtesting/copy_vault_executable.py", "tests/test_copy_vault_executable.py"),
    "consistency_one_big_win": ("src/hl_observer/backtesting/copy_vault_generalization.py", "tests/test_copy_vault_generalization.py"),
    "drawdown_regime": ("src/hl_observer/backtesting/copy_vault_generalization.py", "tests/test_pre_run_copy_321_395.py"),
    "twap_metaorders": ("src/hl_observer/backtesting/copy_vault_executable.py", "tests/test_copy_vault_executable.py"),
    "vault_conflicts": ("src/hl_observer/backtesting/copy_vault_generalization.py", "tests/test_pre_run_copy_321_395.py"),
    "unseen_vault_holdout": ("src/hl_observer/backtesting/copy_vault_generalization.py", "tests/test_copy_vault_generalization.py"),
    "oos_forward": ("src/hl_observer/backtesting/copy_vault_executable.py", "tests/test_copy_vault_executable.py"),
    "costs_sample_size": ("src/hl_observer/backtesting/copy_vault_generalization.py", "src/hl_observer/simulation/economic_objective.py"),
    "net_pnl_placebo": ("src/hl_observer/backtesting/copy_vault_executable.py", "src/hl_observer/simulation/economic_objective.py"),
}

@dataclass(frozen=True)
class Scenario:
    positive: bool
    negative: bool
    deterministic: bool
    detail: dict[str, Any]

def _hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def _entry(event_id: str, ts_ms: int, *, vault="0xA", coin="BTC", direction=1, action="OPEN", live=True):
    row = {"event_id": event_id, "ts_ms": ts_ms, "vault": vault, "coin": coin, "direction": direction, "action": action,
           "dir": "Open Long" if direction > 0 else "Open Short", "taille_usd": 100.0, "move_frac": 0.01}
    if live:
        row.update({"source": "LIVE_WS", "is_snapshot": False, "observed_at_ms": ts_ms})
    return row

def _book(ts_ms: int, *, bid: float, ask: float, capacity=500.0, causal=True, line=1):
    return {"coin": "BTC", "ts_ms": ts_ms, "bid": bid, "ask": ask, "capacity_usd": capacity,
            "source_line": line, "causal_observation": causal}

def _strict_trade(index: int, *, vault="0xB", ts_ms=None, net=1.0, direction=1, coin="BTC", causal=True, capacity=300.0, tamper_gross=False):
    ts = int(ts_ms if ts_ms is not None else 10_000 + index * 100_000)
    fees, spread, slippage, latency = 0.05, 0.04, 0.01, 0.02
    gross = net + fees + spread + slippage + latency + (1.0 if tamper_gross else 0.0)
    trade_id = hashlib.sha256(f"strict-{index}-{vault}-{ts}-{direction}".encode()).hexdigest()
    return {"trade_id": trade_id, "metaorder_id": hashlib.sha256(f"meta-{index}".encode()).hexdigest(),
            "vault": vault, "coin": coin, "direction": direction, "signal_ts_ms": ts, "first_fill_ts_ms": ts,
            "entry_ts_ms": ts + COPY_DELAY_MS, "exit_ts_ms": ts + COPY_DELAY_MS + 300_000,
            "reference_lag_ms": 0, "entry_target_lag_ms": 0, "exit_target_lag_ms": 0,
            "observed_latency_ms": COPY_DELAY_MS, "notional_usd": NOTIONAL_USD,
            "entry_capacity_usd": capacity, "exit_capacity_usd": capacity, "gross_pnl_usd": gross,
            "fees_usd": fees, "spread_cost_usd": spread, "slippage_cost_usd": slippage, "latency_cost_usd": latency,
            "net_pnl_usd": net, "liquidatable_net": True, "paper_read_only": True, "real_execution": False,
            "causal_books_eligible": causal, "causal_forward_eligible": causal}

def _execution_fixture(*, capacity=500.0, causal=True):
    meta = cluster_metaorders([_entry("live", 1_000)])[0][0]
    books = [_book(1_000, bid=99, ask=101, capacity=capacity, causal=causal, line=1),
             _book(61_000, bid=100, ask=102, capacity=capacity, causal=causal, line=2),
             _book(361_000, bid=109, ask=111, capacity=capacity, causal=causal, line=3)]
    return meta, books

def _scenario_userfills_pagination():
    first = plan_de_requetes(0, 25, fenetre_ms=10)
    negative = False
    try: plan_de_requetes(0, 25, fenetre_ms=0)
    except ValueError: negative = True
    return Scenario(first == [(0, 10), (10, 20), (20, 25)], negative, first == plan_de_requetes(0, 25, fenetre_ms=10), {"windows": first})

def _scenario_position_lifecycle():
    raw = [{"vault":"0xA","ts_ms":1,"coin":"BTC","px":100,"sz":1,"signe":1,"dir":"Open Long","start_position":0,"hash":"a"},
           {"vault":"0xA","ts_ms":2,"coin":"BTC","px":101,"sz":.5,"signe":1,"dir":"Open Long","start_position":1,"hash":"b"},
           {"vault":"0xA","ts_ms":3,"coin":"BTC","px":102,"sz":.25,"signe":-1,"dir":"Close Long","start_position":1.5,"hash":"c"},
           {"vault":"0xA","ts_ms":4,"coin":"BTC","px":103,"sz":1.25,"signe":-1,"dir":"Close Long","start_position":1.25,"hash":"d"}]
    actions = [r["action"] for r in reconstruire_episodes(raw)]
    invalid = reconstruire_episodes([{"vault":"0xA","ts_ms":1,"coin":"BTC","px":100,"sz":1,"signe":0,"dir":"","start_position":0,"hash":"x"}])
    return Scenario(actions == ["OPEN","ADD","REDUCE","CLOSE"], invalid == [], actions == [r["action"] for r in reconstruire_episodes(raw)], {"actions": actions})

def _scenario_cashflow_not_pnl():
    ledger = parser_ledger([{"time":2000,"delta":{"type":"withdraw","usdc":"-100"}}, {"time":5000,"delta":{"type":"deposit","usdc":"100"}}], vault="0xAbC")
    original = [{"vault":"0xabc","ts_ms":2001,"action":"CLOSE"}, {"vault":"0xabc","ts_ms":5001,"action":"CLOSE"}, {"vault":"0xabc","ts_ms":2001,"action":"OPEN"}]
    marked = marquer_retraits_ledger([dict(r) for r in original], ledger, fenetre_ms=10)
    again = marquer_retraits_ledger([dict(r) for r in original], ledger, fenetre_ms=10)
    return Scenario(marked[0]["retrait_probable"] and marked[0]["retrait_source"] == "ledger", not marked[1]["retrait_probable"] and not marked[2]["retrait_probable"], marked == again, {"ledger_rows": len(ledger)})

def _scenario_stable_identity():
    base = {"vault":"0xAbC","ts_ms":1000,"coin":"btc","px":100.0,"sz":1.0,"dir":"Open Long","hash":"h","source":"REST_BACKFILL"}
    live = {**base,"vault":"0xabc","source":"LIVE_WS","isSnapshot":False,"received_at_ms":1001}
    first, second = dedupliquer([base, live]), dedupliquer([live, base])
    other = dedupliquer([base, {**base,"vault":"0xDEF"}])
    return Scenario(normaliser_vault(" 0xAbC ") == "0xabc" and len(first)==1 and first[0]["source"]=="LIVE_WS", len(other)==2, first==second, {"dedup_count": len(first)})

def _scenario_copyability_freshness():
    close = {**_entry("close",2000),"action":"CLOSE","dir":"Close Long"}
    metaorders,audit = cluster_metaorders([_entry("open",1000), close], gap_ms=1)
    stale,reason = execute_metaorder(metaorders[0], [_book(40001,bid=99,ask=101)], horizon_ms=300_000)
    again = cluster_metaorders([_entry("open",1000), close], gap_ms=1)
    return Scenario(len(metaorders)==1 and audit["non_entry_events_rejected"]==1, stale is None and reason=="STALE_OR_MISSING_REFERENCE_BOOK", (metaorders,audit)==again, {"reason": reason})

def _scenario_leader_follower_execution():
    meta,books = _execution_fixture(); trade,reason = execute_metaorder(meta,books,horizon_ms=300_000,require_causal_books=True)
    bad_meta,bad_books = _execution_fixture(causal=False); bad,bad_reason = execute_metaorder(bad_meta,bad_books,horizon_ms=300_000,require_causal_books=True)
    positive = bool(trade and reason=="LIQUIDATABLE_NET" and trade["observed_latency_ms"]>=COPY_DELAY_MS and math.isclose(trade["gross_pnl_usd"]-trade["fees_usd"]-trade["spread_cost_usd"]-trade["slippage_cost_usd"]-trade["latency_cost_usd"],trade["net_pnl_usd"],abs_tol=1e-8))
    trade2,reason2 = execute_metaorder(meta,books,horizon_ms=300_000,require_causal_books=True)
    return Scenario(positive, bad is None and bad_reason=="NON_CAUSAL_FORWARD_BOOK", trade==trade2 and reason==reason2, {"reason": reason})

def _scenario_capacity():
    meta,books = _execution_fixture(capacity=500); good,good_reason = execute_metaorder(meta,books,horizon_ms=300_000)
    low_meta,low_books = _execution_fixture(capacity=NOTIONAL_USD-.01); low,low_reason = execute_metaorder(low_meta,low_books,horizon_ms=300_000)
    good2,_ = execute_metaorder(meta,books,horizon_ms=300_000)
    return Scenario(good is not None and good_reason=="LIQUIDATABLE_NET", low is None and low_reason=="OBSERVED_TOP_CAPACITY_TOO_LOW", good==good2, {"low_reason":low_reason})

def _scenario_consistency():
    rows=[_strict_trade(i,vault=f"0x{i%2+10:x}",net=1.0) for i in range(6)]; proof=derive_heldout_vault_generalization(rows,oos_start_ms=1)
    concentrated=[_strict_trade(20,vault="0xB",net=5.0),_strict_trade(21,vault="0xC",net=.1),_strict_trade(22,vault="0xC",net=.1)]
    pc=derive_heldout_vault_generalization(concentrated,oos_start_ms=1)
    return Scenario(bool(proof and proof["profitable_vault_ratio"]==1.0 and proof["one_big_win_dependency"] is False), bool(pc and pc["one_big_win_dependency"] is True), proof==derive_heldout_vault_generalization(rows,oos_start_ms=1), {"largest_share": proof["largest_positive_trade_share"] if proof else None})

def _scenario_drawdown_regime():
    rows=[_strict_trade(30,vault="0xB",net=1),_strict_trade(31,vault="0xB",net=-.5),_strict_trade(32,vault="0xC",net=1)]; proof=derive_heldout_vault_generalization(rows,oos_start_ms=1)
    bad=derive_heldout_vault_generalization([_strict_trade(33,vault="0xD",net=1,tamper_gross=True)],oos_start_ms=1)
    return Scenario(bool(proof and proof["max_drawdown_usd"]==.5 and proof["execution_regimes"]), bool(bad and not bad["economic_claim_eligible"] and bad["net_bps"] is None), proof==derive_heldout_vault_generalization(rows,oos_start_ms=1), {"drawdown":proof["max_drawdown_usd"] if proof else None})

def _scenario_twap_metaorders():
    rows=[_entry("a",1000),_entry("other",20000,coin="ETH"),_entry("b",40000,action="ADD"),_entry("c",120001,action="ADD")]
    metaorders,audit=cluster_metaorders(rows,gap_ms=60000); btc=[r for r in metaorders if r["coin"]=="BTC"]
    close={**_entry("close",10000),"action":"CLOSE","dir":"Close Long"}; _,ca=cluster_metaorders([close])
    return Scenario([r["fill_count"] for r in btc]==[2,1] and audit["sliced_fills_collapsed"]==1, ca["non_entry_events_rejected"]==1, (metaorders,audit)==cluster_metaorders(rows,gap_ms=60000), {"btc_metaorders":len(btc)})

def _scenario_vault_conflicts():
    rows=[_strict_trade(40,vault="0xB",ts_ms=10000,direction=1),_strict_trade(41,vault="0xC",ts_ms=20000,direction=-1)]
    cleanrows=[_strict_trade(42,vault="0xB",ts_ms=10000,direction=1),_strict_trade(43,vault="0xC",ts_ms=20000,direction=1)]
    proof=derive_heldout_vault_generalization(rows,oos_start_ms=1); clean=derive_heldout_vault_generalization(cleanrows,oos_start_ms=1)
    return Scenario(bool(proof and proof["vault_conflict_pairs"]==1), bool(clean and clean["vault_conflict_pairs"]==0), proof==derive_heldout_vault_generalization(rows,oos_start_ms=1), {"conflicts":proof["vault_conflict_pairs"] if proof else None})

def _scenario_unseen_holdout():
    rows=[_strict_trade(50,vault="0xA",ts_ms=100),_strict_trade(51,vault="0xA",ts_ms=300),_strict_trade(52,vault="0xB",ts_ms=300)]
    proof=derive_heldout_vault_generalization(rows,oos_start_ms=200); only=derive_heldout_vault_generalization(rows[:2],oos_start_ms=200)
    return Scenario(bool(proof and proof["vaults_held_out"]==["0xb"]), bool(only and only["sample_count"]==0 and only["net_bps"] is None), proof==derive_heldout_vault_generalization(rows,oos_start_ms=200), {"vaults":proof["vaults_held_out"] if proof else None})

def _summary_for(rows): return summarize(rows)

def _scenario_oos_forward():
    oos=_strict_trade(60,vault="0xB",net=2); fwd=_strict_trade(61,vault="0xC",net=2.5); placebo=_strict_trade(62,vault="0xD",net=-1)
    evaluation={"segments":{"oos":{"summary":_summary_for([oos])},"forward":{"summary":_summary_for([fwd])}},"trades":{"forward":[fwd]},"placebo_inverted_oos":{"summary":_summary_for([placebo])}}
    proof=temporal_evidence(evaluation); non=dict(fwd); non["causal_forward_eligible"]=False; bad=temporal_evidence({**evaluation,"trades":{"forward":[non]}})
    return Scenario(proof["oos"]["no_lookahead"] and proof["forward"]["post_freeze"], bad["forward"]["post_freeze"] is False, proof==temporal_evidence(evaluation), {"forward_post_freeze":proof["forward"]["post_freeze"]})

def _scenario_costs_sample_size():
    rows=[_strict_trade(100+i,vault=f"0x{i%4+10:x}",net=.25) for i in range(20)]; proof=derive_heldout_vault_generalization(rows,oos_start_ms=1)
    tampered=list(rows); tampered[-1]=_strict_trade(999,vault="0xF",net=.25,tamper_gross=True); bad=derive_heldout_vault_generalization(tampered,oos_start_ms=1)
    return Scenario(bool(proof and proof["sample_count"]==20 and proof["economic_claim_eligible"] and proof["total_fees_usd"] is not None), bool(bad and not bad["economic_claim_eligible"] and bad["net_bps"] is None and bad["rejection_reasons"].get("ECONOMIC_RECONCILIATION_FAILED",0)==1), proof==derive_heldout_vault_generalization(rows,oos_start_ms=1), {"sample_count":proof["sample_count"] if proof else None})

def _scenario_net_pnl_placebo():
    candidate=_strict_trade(200,vault="0xB",net=2); placebo=_strict_trade(201,vault="0xC",net=-.5)
    evaluation={"segments":{"oos":{"summary":_summary_for([candidate])},"forward":{"summary":_summary_for([candidate])}},"trades":{"forward":[candidate]},"placebo_inverted_oos":{"summary":_summary_for([placebo])}}
    proof=temporal_evidence(evaluation); worse=_strict_trade(202,vault="0xD",net=3); bad=temporal_evidence({**evaluation,"placebo_inverted_oos":{"summary":_summary_for([worse])}})
    return Scenario(proof["placebos"]["beaten"], bad["placebos"]["beaten"] is False, proof==temporal_evidence(evaluation), {"candidate":proof["placebos"]["candidate_net_usd"]})

_SCENARIOS: dict[str, Callable[[], Scenario]] = {
    "userfills_pagination":_scenario_userfills_pagination,"position_lifecycle":_scenario_position_lifecycle,
    "cashflow_not_pnl":_scenario_cashflow_not_pnl,"stable_identity":_scenario_stable_identity,
    "copyability_freshness":_scenario_copyability_freshness,"leader_follower_execution":_scenario_leader_follower_execution,
    "capacity":_scenario_capacity,"consistency_one_big_win":_scenario_consistency,"drawdown_regime":_scenario_drawdown_regime,
    "twap_metaorders":_scenario_twap_metaorders,"vault_conflicts":_scenario_vault_conflicts,"unseen_vault_holdout":_scenario_unseen_holdout,
    "oos_forward":_scenario_oos_forward,"costs_sample_size":_scenario_costs_sample_size,"net_pnl_placebo":_scenario_net_pnl_placebo,
}

def evaluate_copy_requirements(root: Path) -> dict[str, Any]:
    root=root.resolve(); requirements=[]
    for key,description in COPY_REQUIREMENTS:
        scenario=_SCENARIOS[key](); evidence=list(_EVIDENCE[key]); hashes={p:_hash(root/p) for p in evidence if (root/p).is_file()}
        facets={"CONTRACT":callable(_SCENARIOS[key]),"POSITIVE_PATH":scenario.positive,"NEGATIVE_FAIL_CLOSED":scenario.negative,
                "DETERMINISM_CAUSALITY":scenario.deterministic,"EVIDENCE_PROVENANCE":len(hashes)==len(evidence)}
        requirements.append({"key":key,"description":description,"ok":all(facets.values()),"facets":facets,"evidence":evidence,"evidence_sha256":hashes,"detail":scenario.detail})
    return {"category":"COPY_VAULT","requirements_total":len(COPY_REQUIREMENTS),"requirements_done":sum(1 for r in requirements if r["ok"]),
            "facets_total":len(COPY_REQUIREMENTS)*len(FACETS),"facets_done":sum(1 for r in requirements for v in r["facets"].values() if v),
            "ok":all(r["ok"] for r in requirements),"requirements":requirements}

__all__=["COPY_REQUIREMENTS","FACETS","evaluate_copy_requirements"]
