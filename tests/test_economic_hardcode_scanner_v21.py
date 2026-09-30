from __future__ import annotations

import json
from pathlib import Path

from hl_observer.economics.hardcode_scanner import (
    PROPOSAL_DISPOSITION,
    scan_economic_paths,
    scan_economic_source,
)


def test_scanner_propose_les_litteraux_economiques_sans_reecriture() -> None:
    source = """
ROUND_TRIP_FEE_BPS = 18.0
NOTIONAL_USD = 25.0
def eligible(edge_bps: float) -> bool:
    return edge_bps > 30.0
"""

    report = scan_economic_source(source, path="active_strategy.py")

    assert report["parse_error"] is None
    assert [row["literal"] for row in report["findings"]] == [18.0, 25.0, 30.0]
    assert all(
        row["disposition"] == PROPOSAL_DISPOSITION
        for row in report["findings"]
    )
    assert source.endswith("\n")


def test_scanner_distingue_conversions_versions_et_autorite_canonique() -> None:
    conversion = """
SCHEMA_VERSION = "economic.v2"
def fee_usd(notional_usd: float, fee_bps: float) -> float:
    return notional_usd * fee_bps / 10_000.0
"""
    authority = "DEFAULT_FEE_BPS = 4.5\n"
    identities = """
def reconcile(net_pnl: float, fee_usd: float) -> bool:
    rejected_fee_count += 1
    edge = 1024 * 1024
    fair_mid = 0.5 * (bid + ask)
    if net_pnl > 0.0:
        return abs(net_pnl - fee_usd) < 1e-4
    return False
"""
    explicit_zero = "SLIPPAGE_COST_USD = 0.0\n"

    conversion_report = scan_economic_source(conversion, path="strategy.py")
    authority_report = scan_economic_source(
        authority,
        path="src/hl_observer/economics/families.py",
    )
    identity_report = scan_economic_source(identities, path="strategy.py")
    zero_report = scan_economic_source(explicit_zero, path="strategy.py")

    assert conversion_report["findings"] == []
    assert conversion_report["suppressed"][0]["reason"] == "UNIT_CONVERSION_LITERAL"
    assert authority_report["findings"] == []
    assert authority_report["suppressed"][0]["reason"] == (
        "CANONICAL_ECONOMIC_AUTHORITY_DECLARATION"
    )
    assert identity_report["findings"] == []
    assert [row["literal"] for row in zero_report["findings"]] == [0.0]


def test_scan_de_chemins_est_deterministe_et_signale_les_erreurs(tmp_path: Path) -> None:
    source = tmp_path / "economic.py"
    source.write_text("MAX_LATENCY_MS = 750.0\n", encoding="utf-8")

    first = scan_economic_paths(tmp_path, [source, "missing.py"])
    second = scan_economic_paths(tmp_path, [source, "missing.py"])

    assert first == second
    assert first["disposition"] == PROPOSAL_DISPOSITION
    assert first["auto_rewrite"] is False
    assert first["summary"]["proposal_count"] == 1
    assert first["summary"]["parse_error_count"] == 1
    assert first["parse_errors"][0]["reason"] == "SOURCE_FILE_MISSING"
    json.dumps(first, sort_keys=True)


def test_scan_reel_des_chemins_actifs_reste_une_liste_de_propositions() -> None:
    root = Path(__file__).resolve().parents[1]

    report = scan_economic_paths(root)

    assert report["summary"]["files_scanned"] >= 8
    assert report["summary"]["parse_error_count"] == 0
    assert report["auto_rewrite"] is False
    assert all(
        row["disposition"] == PROPOSAL_DISPOSITION for row in report["findings"]
    )
