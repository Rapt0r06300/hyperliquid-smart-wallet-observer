r"""Recoupement des données Ironflow avec NOS données (cache de recherche issu du coffre), période commune.

Une source externe n'est jamais crue sur parole : on compare, heure par heure et coin par coin, le
close des bougies 1 h et le taux de funding réglé. Écarts en bps (bougies) et en taux absolu (funding).
Lecture seule. Écrit `runtime/history/ironflow/RECOUPEMENT.json`.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow.parquet as pq

RACINE = Path(__file__).resolve().parents[1]
CACHE = RACINE / "runtime" / "research_lab" / "data" / "goal2_cache"
IRON = RACINE / "runtime" / "history" / "ironflow"


def _iron(jeu: str, colonnes: list[str]) -> pd.DataFrame:
    morceaux = []
    for f in sorted((IRON / jeu / "data").glob("2026-*.parquet")):
        t = pq.read_table(f, columns=colonnes).to_pandas()
        morceaux.append(t[t["dex"].fillna("") == ""] if "dex" in t else t)
    d = pd.concat(morceaux, ignore_index=True)
    d["t_ms"] = (d["timestamp"].astype("int64") // 1000).astype(np.int64)   # us -> ms
    return d


def recouper_bougies() -> dict:
    nous = pd.read_parquet(CACHE / "candles_1h.parquet")
    ir = _iron("candles-1h", ["timestamp", "coin", "dex", "close"])
    if str(pq.read_schema(next((IRON / "candles-1h" / "data").glob("2026-*.parquet"))).field("timestamp").type).startswith("timestamp[ms"):
        ir["t_ms"] = ir["timestamp"].astype("int64")
    m = nous.merge(ir[["coin", "t_ms", "close"]].rename(columns={"close": "close_ir"}), on=["coin", "t_ms"], how="inner")
    col = "c" if "c" in m else "close"
    e = (1e4 * (m["close_ir"] / m[col].astype(float) - 1.0)).abs()
    return {"paires": int(len(m)), "coins": int(m["coin"].nunique()), "ecart_median_bps": round(float(e.median()), 3),
            "ecart_p99_bps": round(float(e.quantile(0.99)), 3), "part_au_dela_de_10_bps": round(float((e > 10).mean()), 5),
            "nos_heures": int(len(nous)), "heures_ironflow_sans_equivalent": int(len(ir) - len(m))}


def recouper_funding() -> dict:
    nous = pd.read_parquet(CACHE / "funding_1h.parquet")
    ir = _iron("funding", ["timestamp", "coin", "dex", "funding_rate"])
    ir["heure"] = ir["t_ms"] // 3_600_000
    tcol = "ts_ms" if "ts_ms" in nous else "t_ms"
    nous["heure"] = nous[tcol] // 3_600_000
    rcol = next(c for c in ("funding", "fundingRate", "funding_rate", "taux", "rate") if c in nous)
    m = nous.merge(ir[["coin", "heure", "funding_rate"]], on=["coin", "heure"], how="inner")
    e = (m[rcol].astype(float) - m["funding_rate"]).abs()
    return {"paires": int(len(m)), "coins": int(m["coin"].nunique()), "ecart_median": float(e.median()),
            "ecart_max": float(e.max()), "part_identique_1e-9": round(float((e < 1e-9).mean()), 5)}


def main() -> int:
    for flux in (sys.stdout, sys.stderr):
        try:  # noqa: SIM105
            flux.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    r = {}
    for nom, f in (("bougies_1h", recouper_bougies), ("funding", recouper_funding)):
        try:
            r[nom] = f()
        except (OSError, KeyError, StopIteration, ValueError) as exc:
            r[nom] = {"statut": "UNMEASURABLE", "motif": f"{type(exc).__name__}: {exc}"}
        print(f"  {nom:<11} {r[nom]}")
    (IRON / "RECOUPEMENT.json").write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
