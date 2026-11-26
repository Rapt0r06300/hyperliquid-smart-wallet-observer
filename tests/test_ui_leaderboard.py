from pathlib import Path

from fastapi.testclient import TestClient

from hl_observer.config.loader import load_settings
from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import LeaderboardWalletCandidate
from hl_observer.ui.app import create_ui_app
from hl_observer.ui.state import UiState


def _client(tmp_path: Path) -> TestClient:
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'ui_v6.sqlite3'}"
    init_db(settings.database_url)
    return TestClient(create_ui_app(settings, UiState()))


def test_ui_mentions_leaderboard(tmp_path: Path):
    html = _client(tmp_path).get("/").text.lower()

    assert "leaderboard" in html


def test_ui_truncated_addresses_explained(tmp_path: Path):
    html = _client(tmp_path).get("/").text.lower()

    assert "tronque" in html
    assert "aucun wallet n'est invente" in html


def test_leaderboard_status_endpoint_exists(tmp_path: Path):
    response = _client(tmp_path).get("/api/leaderboard/status")

    assert response.status_code == 200
    assert "full_addresses_found" in response.json()


def test_candidate_endpoint_recalculates_old_persisted_scores(tmp_path: Path):
    settings = load_settings()
    settings.database_url = f"sqlite:///{tmp_path / 'ui_leaderboard_candidates.sqlite3'}"
    init_db(settings.database_url)
    factory = create_session_factory(create_sqlite_engine(settings.database_url))
    stale_high = "0x" + "5" * 40
    evidence_high = "0x" + "6" * 40
    with factory() as session:
        session.add_all([
            LeaderboardWalletCandidate(
                wallet_address=stale_high, rank=1, period="30D",
                account_value_usdc=0, pnl_usdc=-100_000, roi_pct=-50,
                volume_usdc=0, source_confidence=0, leaderboard_score=100,
            ),
            LeaderboardWalletCandidate(
                wallet_address=evidence_high, rank=500, period="30D",
                account_value_usdc=1_000_000, pnl_usdc=100_000, roi_pct=50,
                volume_usdc=10_000_000, source_confidence=95, leaderboard_score=0,
            ),
        ])
        session.commit()
    client = TestClient(create_ui_app(settings, UiState()))

    response = client.get("/api/leaderboard/candidates?limit=10")

    assert response.status_code == 200
    rows = response.json()
    assert rows[0]["wallet_address"] == evidence_high
    assert rows[0]["leaderboard_score"] > rows[1]["leaderboard_score"]
    assert rows[0]["score_kind"] == "PUBLIC_DISCOVERY_TRIAGE_ONLY"
