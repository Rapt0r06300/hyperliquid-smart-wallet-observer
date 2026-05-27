from hl_observer.wallets.leaderboard_models import LeaderboardResult
from hl_observer.wallets.leaderboard_network_probe import normalize_stats_leaderboard_payload
from hl_observer.wallets.leaderboard_parser import parse_leaderboard_records


VALID = "0x" + "b" * 40


def test_truncated_address_never_creates_candidate():
    rows = parse_leaderboard_records([{"rank": 1, "address": "0x393d...2109", "PnL": "100"}])
    result = LeaderboardResult.from_rows(rows)

    assert result.truncated_addresses_seen == 1
    assert result.candidates_created == 0


def test_leaderboard_candidates_require_full_address():
    rows = parse_leaderboard_records([{"rank": 1, "address": VALID, "PnL": "100", "ROI": "5"}])
    result = LeaderboardResult.from_rows(rows)

    assert result.full_addresses_found == 1
    assert result.candidates[0].wallet_address == VALID


def test_no_random_wallet_generated_to_replace_truncated():
    rows = parse_leaderboard_records([{"address": "0x488d...fe08"}])
    result = LeaderboardResult.from_rows(rows)

    assert all("..." in rejected["raw_value"] for rejected in result.rejected)
    assert not result.candidates


def test_stats_leaderboard_eth_address_creates_full_candidate():
    payload = {
        "leaderboardRows": [
            {
                "ethAddress": VALID,
                "accountValue": "10000",
                "windowPerformances": [["month", {"pnl": "2500", "roi": "0.25", "vlm": "500000"}]],
            }
        ]
    }

    normalized = normalize_stats_leaderboard_payload(payload, period="30D", target=500)
    rows = parse_leaderboard_records(
        normalized,
        period="30D",
        source_method="stats_data",
        extraction_method="network",
    )
    result = LeaderboardResult.from_rows(rows)

    assert result.full_addresses_found == 1
    assert result.candidates[0].wallet_address == VALID
    assert result.candidates[0].pnl_usdc == 2500.0
    assert result.candidates[0].roi_pct == 25.0
