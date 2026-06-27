from __future__ import annotations

from hyper_smart_observer.scale.dataset_profiler import profile_dataset


def test_dataset_profile_counts_local_jsonl(tmp_path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text(
        '{"wallet":"0x111","coin":"BTC","closed_pnl":1}\n'
        '{"wallet":"0x222","coin":"ETH","closed_pnl":-1}\n',
        encoding="utf-8",
    )

    profile = profile_dataset(path)

    assert profile.exists is True
    assert profile.files == 1
    assert profile.sampled_rows == 2
    assert {"wallet", "coin", "closed_pnl"}.issubset(set(profile.detected_columns))
    assert profile.network_used is False


def test_dataset_profile_missing_path_is_safe(tmp_path) -> None:
    profile = profile_dataset(tmp_path / "missing.jsonl")

    assert profile.exists is False
    assert profile.stopped_reason == "PATH_NOT_FOUND"
    assert profile.network_used is False
