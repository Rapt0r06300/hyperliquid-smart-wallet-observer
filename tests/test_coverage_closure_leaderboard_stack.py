from __future__ import annotations

import asyncio
import csv
import json

import httpx
import pytest

from hl_observer.wallets import leaderboard_network_probe as probe
from hl_observer.wallets import leaderboard_parser as parser
from hl_observer.wallets.leaderboard_models import (
    LeaderboardResult,
    LeaderboardRowRecord,
    LeaderboardSourceStatus,
    row_to_candidate,
    score_leaderboard_row,
)
from hl_observer.wallets.leaderboard_validation import (
    LeaderboardAddressStatus,
    validate_leaderboard_wallet_address,
)


WALLET = "0x" + "a" * 40
TRUNCATED = "0x1234...abcd"


class _Response:
    def __init__(self, *, payload=None, text: str = "", status: int = 200, url: str = "https://unit.invalid") -> None:
        self._payload = {} if payload is None else payload
        self.text = text
        self.status_code = status
        self.url = url

    def json(self):
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                "bad status",
                request=httpx.Request("GET", self.url),
                response=httpx.Response(self.status_code),
            )


class _Client:
    def __init__(self, response: _Response | None = None, error: Exception | None = None) -> None:
        self.response = response or _Response()
        self.error = error
        self.get_calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def get(self, url, *, headers):
        self.get_calls.append((url, headers))
        if self.error is not None:
            raise self.error
        return self.response


def _client_factory(monkeypatch, clients):
    queue = list(clients)

    def factory(*args, **kwargs):
        assert queue, "unexpected AsyncClient construction"
        return queue.pop(0)

    monkeypatch.setattr(probe.httpx, "AsyncClient", factory)
    return queue


def _stats_payload(address: str = WALLET):
    return {
        "leaderboardRows": [
            {
                "ethAddress": address,
                "accountValue": "1000",
                "windowPerformances": {
                    "month": {"pnl": "25", "roi": "0.10", "vlm": "5000"},
                    "day": {"pnl": "2", "roi": "0.01", "volume": "50"},
                },
                "displayName": "whale",
            }
        ]
    }


def test_probe_dry_run_never_builds_http_client(monkeypatch) -> None:
    monkeypatch.setattr(probe.httpx, "AsyncClient", lambda *a, **k: (_ for _ in ()).throw(AssertionError("network forbidden")))
    result = asyncio.run(probe.probe_leaderboard_network(dry_run=True, period="7D"))
    assert result.period == "7D"
    assert result.status == LeaderboardSourceStatus.IMPORT_REQUIRED
    assert "dry_run_no_network" in result.notes


def test_probe_stats_success_and_import_required(monkeypatch) -> None:
    first = _Client(_Response(payload=_stats_payload()))
    queue = _client_factory(monkeypatch, [first])
    result = asyncio.run(probe.probe_leaderboard_network(dry_run=False, period="30D", target=10))
    assert result.status == LeaderboardSourceStatus.OK
    assert result.full_addresses_found == 1
    assert result.candidates_created == 1
    assert result.candidates[0].wallet_address == WALLET
    assert "stats_data_leaderboard_completed" in result.notes
    assert queue == []

    empty = _Client(_Response(payload={"leaderboardRows": []}))
    _client_factory(monkeypatch, [empty])
    result = asyncio.run(probe.probe_leaderboard_network(dry_run=False))
    assert result.status == LeaderboardSourceStatus.IMPORT_REQUIRED
    assert result.rows_seen == 0


def test_probe_stats_error_falls_back_to_app_full_and_truncated(monkeypatch) -> None:
    bad_stats = _Client(_Response(payload={"unexpected": []}))
    app_full = _Client(_Response(text=f"leader {WALLET}", url="https://app.invalid/final"))
    _client_factory(monkeypatch, [bad_stats, app_full])
    result = asyncio.run(probe.probe_leaderboard_network(dry_run=False))
    assert result.status == LeaderboardSourceStatus.OK
    assert result.full_addresses_found == 1
    assert any(note.startswith("stats_data_error=") for note in result.notes)

    bad_stats = _Client(_Response(payload={"unexpected": []}))
    app_short = _Client(_Response(text=f"leader {TRUNCATED}"))
    _client_factory(monkeypatch, [bad_stats, app_short])
    result = asyncio.run(probe.probe_leaderboard_network(dry_run=False))
    assert result.status == LeaderboardSourceStatus.ONLY_TRUNCATED_ADDRESSES
    assert result.full_addresses_found == 0
    assert result.truncated_addresses_seen == 1


def test_probe_both_network_sources_fail_closed(monkeypatch) -> None:
    error1 = httpx.ConnectError("stats offline", request=httpx.Request("GET", "https://stats.invalid"))
    error2 = httpx.ConnectError("app offline", request=httpx.Request("GET", "https://app.invalid"))
    _client_factory(monkeypatch, [_Client(error=error1), _Client(error=error2)])
    result = asyncio.run(probe.probe_leaderboard_network(dry_run=False))
    assert result.status == LeaderboardSourceStatus.SOURCE_UNAVAILABLE
    assert "app offline" in str(result.error_message)
    assert any("stats offline" in note for note in result.notes)


def test_normalize_stats_payload_all_windows_and_edges() -> None:
    with pytest.raises(ValueError, match="leaderboardRows"):
        probe.normalize_stats_leaderboard_payload({})

    payload = {
        "leaderboardRows": [
            "bad",
            {
                "ethAddress": WALLET,
                "accountValue": "10",
                "windowPerformances": [["week", {"pnl": "3", "roi": "0.2", "volume": "4"}]],
                "displayName": "w",
            },
        ]
    }
    rows = probe.normalize_stats_leaderboard_payload(payload, period="7d", target=10)
    assert rows[0]["rank"] == 2
    assert rows[0]["roi"] == 20.0
    assert rows[0]["volume"] == "4"
    assert rows[0]["period_window"] == "week"
    assert probe.normalize_stats_leaderboard_payload(payload, target=0) == []
    assert probe.normalize_stats_leaderboard_payload(_stats_payload(), period="unknown")[0]["period_window"] == "month"

    assert probe._window_performance({"day": {"pnl": 1}}, "day") == {"pnl": 1}
    assert probe._window_performance({"day": "bad"}, "day") == {}
    assert probe._window_performance([["day"], "bad", ["day", {"pnl": 2}]], "day") == {"pnl": 2}
    assert probe._window_performance(None, "day") == {}
    assert probe._roi_ratio_to_percent(None) is None
    assert probe._roi_ratio_to_percent("") == ""
    assert probe._roi_ratio_to_percent("0.25") == 25.0
    assert probe._roi_ratio_to_percent("bad") == "bad"


def test_validation_all_source_methods_and_rejections() -> None:
    for method, expected in (
        ("network", LeaderboardAddressStatus.NETWORK_FULL_ADDRESS_OK),
        ("dom", LeaderboardAddressStatus.DOM_FULL_ADDRESS_OK),
        ("import", LeaderboardAddressStatus.IMPORTED_FULL_ADDRESS_OK),
        ("other", LeaderboardAddressStatus.FULL_ADDRESS_OK),
    ):
        result = validate_leaderboard_wallet_address(WALLET.upper(), source_method=method)
        assert result.is_full_address is True
        assert result.normalized_value == WALLET
        assert result.validation_status == expected

    empty = validate_leaderboard_wallet_address(None)
    assert empty.validation_status == LeaderboardAddressStatus.EMPTY_ADDRESS_REJECTED
    short = validate_leaderboard_wallet_address(TRUNCATED)
    assert short.is_truncated is True
    assert short.validation_status == LeaderboardAddressStatus.TRUNCATED_ADDRESS_REJECTED
    invalid = validate_leaderboard_wallet_address("hello")
    assert invalid.validation_status == LeaderboardAddressStatus.INVALID_ADDRESS_REJECTED


def test_models_score_candidates_and_result_statuses() -> None:
    validation = validate_leaderboard_wallet_address(WALLET, source_method="network")
    rich = LeaderboardRowRecord(
        rank=1,
        address=WALLET,
        account_value_usdc=1_000_000,
        pnl_usdc=100_000,
        roi_pct=50,
        volume_usdc=10_000_000,
        validation=validation,
        source_confidence_score=100,
    )
    score = score_leaderboard_row(rich)
    assert 0 <= score <= 100
    candidate = row_to_candidate(rich)
    assert candidate is not None
    assert candidate.wallet_address == WALLET
    assert candidate.selected_for_backfill is True

    defaults = LeaderboardRowRecord(validation=validation)
    assert 0 <= score_leaderboard_row(defaults) <= 100
    assert row_to_candidate(LeaderboardRowRecord()) is None

    ok = LeaderboardResult.from_rows([rich])
    assert ok.status == LeaderboardSourceStatus.OK
    assert ok.full_addresses_found == 1
    assert ok.candidates_created == 1

    truncated_validation = validate_leaderboard_wallet_address(TRUNCATED)
    truncated = LeaderboardRowRecord(address_short=TRUNCATED, validation=truncated_validation)
    only_short = LeaderboardResult.from_rows([truncated])
    assert only_short.status == LeaderboardSourceStatus.ONLY_TRUNCATED_ADDRESSES
    assert only_short.rejected[0]["reason"] == LeaderboardAddressStatus.TRUNCATED_ADDRESS_REJECTED.value

    invalid = LeaderboardResult.from_rows([LeaderboardRowRecord(address="bad")])
    assert invalid.status == LeaderboardSourceStatus.IMPORT_REQUIRED
    assert invalid.rejected[0]["reason"] == "INVALID"


def test_leaderboard_parser_files_helpers_and_display_extract(tmp_path) -> None:
    record = {"ethAddress": WALLET, "Rank": "2", "Account Value": "$1,000", "PnL": "3", "ROI": "4%", "Volume": "$5,000"}
    row = parser.parse_leaderboard_records([record], source_method="network")[0]
    assert row.rank == 2
    assert row.account_value_usdc == 1000.0
    assert row.roi_pct == 4.0

    json_path = tmp_path / "rows.json"
    json_path.write_text(json.dumps({"leaderboard": [record]}), encoding="utf-8")
    assert len(parser.parse_leaderboard_file(json_path)) == 1
    json_path.write_text(json.dumps({"data": [record]}), encoding="utf-8")
    assert len(parser.parse_leaderboard_file(json_path)) == 1
    json_path.write_text(json.dumps({"rows": [record]}), encoding="utf-8")
    assert len(parser.parse_leaderboard_file(json_path)) == 1
    json_path.write_text(json.dumps("bad"), encoding="utf-8")
    with pytest.raises(ValueError):
        parser.parse_leaderboard_file(json_path)

    csv_path = tmp_path / "rows.csv"
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["address"])
        writer.writeheader()
        writer.writerow({"address": WALLET})
    assert len(parser.parse_leaderboard_file(csv_path)) == 1

    txt_path = tmp_path / "rows.txt"
    txt_path.write_text(WALLET + "\n" + TRUNCATED + "\n", encoding="utf-8")
    assert len(parser.parse_leaderboard_file(txt_path)) == 2
    with pytest.raises(FileNotFoundError):
        parser.parse_leaderboard_file(tmp_path / "missing.csv")

    assert parser.extract_display_addresses(f"x {WALLET} y {TRUNCATED}") == [WALLET, TRUNCATED]
    assert parser._first_present({"A": "", "b": 2}, "a", "B") == 2
    assert parser._safe_float("$1,234.5%") == 1234.5
    assert parser._safe_float("bad") is None
    assert parser._safe_float(None) is None
    assert parser._safe_int("1,234") == 1234
    assert parser._safe_int("bad") is None
    assert parser._safe_int(None) is None
    assert parser._coerce_record({"x": 1}) == {"x": 1}
    assert parser._coerce_record("abc") == {"address": "abc"}
