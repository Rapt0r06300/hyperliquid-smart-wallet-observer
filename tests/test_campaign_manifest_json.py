from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_every_campaign_manifest_is_one_valid_json_object() -> None:
    campaign_dir = ROOT / "catalog" / "campaigns"
    failures: list[str] = []
    for path in sorted(campaign_dir.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            failures.append(f"{path.name}: {exc}")
            continue
        if not isinstance(payload, dict):
            failures.append(f"{path.name}: manifest is not an object")
    assert not failures, "\n".join(failures)
