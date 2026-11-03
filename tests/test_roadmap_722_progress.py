"""Contract tests for the Codex master-roadmap tracker (no network or runner use)."""
from __future__ import annotations

from tools.roadmap_722_progress import (
    DEFAULT_ROADMAP,
    format_progress,
    inspect_roadmap,
)


def _task(identifier: str, state: str = "TODO", *, checked: bool = False,
          receipt: str = "`PENDING`", reason: str = "") -> str:
    box = "x" if checked else " "
    extra = f" **Motif Codex :** {reason}" if reason else ""
    return (
        f"- [{box}] **[{identifier}] Vérification nommée** (P0).\n"
        f"  - **Suivi Codex :** `{state}` · **Priorité :** `P0` · "
        f"**Fichiers vérifiés HEAD :** `tools/check_document_authority.py`. "
        f"**Correctif attendu :** Tester. **Reçu de clôture :** {receipt}.{extra}\n"
    )


def _sample(**kwargs: object) -> str:
    return _task("ASF-001", **kwargs) + _task("ASF-002")


def test_live_master_roadmap_has_full_tracking_metadata() -> None:
    actual = inspect_roadmap(DEFAULT_ROADMAP.read_text(encoding="utf-8"))
    assert actual["total"] == actual["present"] == 800
    assert actual["errors"] == []


def test_progress_starts_at_zero_without_completed_receipts() -> None:
    result = inspect_roadmap(_sample(), expected={"ASF": 2})
    assert result["verified"] == 0
    assert result["handled"] == 0
    assert result["verified_pct"] == 0
    assert "0/2" in format_progress(result)
    assert result["errors"] == []


def test_checked_task_without_verified_receipt_is_invalid() -> None:
    result = inspect_roadmap(_sample(checked=True), expected={"ASF": 2})
    assert "CHECKED_WITHOUT_VERIFIED_DONE:ASF-001" in result["errors"]


def test_verified_task_needs_real_sha_and_test_reference() -> None:
    missing = inspect_roadmap(_sample(state="VERIFIED_DONE", checked=True),
                              expected={"ASF": 2})
    assert "INVALID_VERIFIED_RECEIPT:ASF-001" in missing["errors"]
    valid = inspect_roadmap(_sample(state="VERIFIED_DONE", checked=True,
                        receipt="commit a1b2c3d tests/test_example.py PASS exit 0"),
                        expected={"ASF": 2})
    assert valid["errors"] == []
    assert valid["verified"] == 1
    assert valid["handled"] == 1
    assert valid["verified_pct"] == 50


def test_blocked_requires_reason_and_does_not_count_as_verified() -> None:
    invalid = inspect_roadmap(_sample(state="BLOCKED"), expected={"ASF": 2})
    assert "NO_CLASSIFICATION_REASON:ASF-001" in invalid["errors"]
    good = inspect_roadmap(_sample(state="BLOCKED", reason="Données externes indisponibles"),
                           expected={"ASF": 2})
    assert good["errors"] == []
    assert good["handled"] == 1
    assert good["verified"] == 0


def test_duplicate_identity_detected() -> None:
    data = _sample() + _task("ASF-001")
    result = inspect_roadmap(data, expected={"ASF": 2})
    assert "DUPLICATE_ID:ASF-001" in result["errors"]
