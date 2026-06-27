from __future__ import annotations

import csv
import json
from pathlib import Path

from sqlalchemy.orm import Session

from hl_observer.storage.models import Top500Export, TopWallet
from hl_observer.utils.time import now_ms


def export_top_wallets(session: Session, *, export_dir: Path = Path("exports/top_wallets")) -> dict[str, Path]:
    export_dir.mkdir(parents=True, exist_ok=True)
    rows = session.query(TopWallet).order_by(TopWallet.score.desc()).all()
    payload = [
        {
            "wallet_address": row.wallet_address,
            "rank": row.rank,
            "source": row.source,
            "score": row.score,
            "status": row.status,
        }
        for row in rows
    ]
    json_path = export_dir / "top500_latest.json"
    csv_path = export_dir / "top500_latest.csv"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["wallet_address", "rank", "source", "score", "status"])
        writer.writeheader()
        writer.writerows(payload)
    session.add(Top500Export(path=str(json_path), format="json", rows_exported=len(payload), created_at_ms=now_ms()))
    session.add(Top500Export(path=str(csv_path), format="csv", rows_exported=len(payload), created_at_ms=now_ms()))
    return {"json": json_path, "csv": csv_path}
