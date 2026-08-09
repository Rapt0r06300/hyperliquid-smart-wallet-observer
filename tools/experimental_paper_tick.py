"""Tick EXPERIMENTAL_PAPER (--une-fois, pour boucle_collecteur). Lit les données LIVE, ouvre/gère/sort
les positions paper des 3 moteurs (cross-venue, lead-lag, copy-vaults). Gaté par le flag
HYPERSMART_EXPERIMENTAL_PAPER=1. PAPER-only : aucun ordre réel, aucune signature."""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path

from hl_observer.experimental.runner import tick


def _ecrire_heartbeat(root: str, *, status: str, state: dict | None = None, error: str | None = None) -> None:
    path = Path(root) / "runtime" / "research_lab" / "heartbeats" / "experimental-paper.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pid": os.getpid(),
        "heartbeat_ms": int(time.time() * 1000),
        "status": status,
        "positions": int(((state or {}).get("resume") or {}).get("positions_ouvertes") or 0),
        "real_execution": False,
    }
    if error:
        payload["error"] = error[:240]
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Tick EXPERIMENTAL_PAPER (paper-only).")
    p.add_argument("--root", default=".")
    p.add_argument("--une-fois", action="store_true")
    a = p.parse_args(argv)
    if os.environ.get("HYPERSMART_EXPERIMENTAL_PAPER", "0") != "1":
        print("[experimental] DESACTIVE (HYPERSMART_EXPERIMENTAL_PAPER != 1)", flush=True)
        return 0
    _ecrire_heartbeat(a.root, status="STARTING")
    try:
        st = tick(a.root)
    except Exception as exc:
        _ecrire_heartbeat(a.root, status="ERROR", error=str(exc))
        raise
    _ecrire_heartbeat(a.root, status="OK", state=st)
    print("[experimental] ouvertures=%d fermetures=%d positions=%d realise=%.4f$ refus=%d" % (
        len(st["ouvertures"]), len(st["fermetures"]), st["resume"]["positions_ouvertes"],
        st["resume"]["realise_total_usd"], st["n_refus_ce_tick"]), flush=True)
    if st.get("premier_signal"):
        print("[experimental] 1er signal admis:", json.dumps(st["premier_signal"], ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
