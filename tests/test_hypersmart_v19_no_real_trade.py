from __future__ import annotations

from pathlib import Path


def test_v19_new_modules_do_not_create_external_execution_paths():
    files = [
        Path("src/hl_observer/analysis/negative_pnl_auditor.py"),
        Path("src/hl_observer/risk/risk_engine_v3.py"),
        Path("src/hl_observer/analysis/v19_repo_matrix.py"),
    ]
    joined = "\n".join(path.read_text(encoding="utf-8").lower() for path in files)
    forbidden_runtime_tokens = [
        "requests.post(\"/exchange",
        "requests.post('/exchange",
        "private_key =",
        "wallet_connect",
        "send_order(",
        "place_order(",
    ]
    for token in forbidden_runtime_tokens:
        assert token not in joined

    assert "paper_only" in joined or "paper_simulation_only" in joined
    assert "real_execution" in joined
