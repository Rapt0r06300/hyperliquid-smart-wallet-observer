import json
from pathlib import Path

from hl_observer.research.process_memory import validate_process_record


def test_historical_seed_memory_is_valid_non_certifying_and_covers_all_families():
    path = Path("docs/quant/HISTORICAL_EXPERIMENT_MEMORY.jsonl")
    assert path.exists()
    records = [validate_process_record(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert {record["family"] for record in records} == {"copy_vault", "lead_lag", "cross_venue_dislocation_v2"}
    assert all(record["provenance"] == "historical" for record in records)
    assert all(record["certifying"] is False for record in records)
