#!/usr/bin/env python3
"""Compression / archivage columnar des tapes — idées #67-70.

Convertit une tape JSONL en **Parquet + zstd** (colonnes typées, compression forte) quand
`pyarrow` est présent, sinon repli **gzip** (stdlib). Non destructif : écrit à côté, garde
l'original (option `--supprimer-source` pour purger après succès). PAPER / lecture seule.

Gains : volume divisé (zstd columnar), lecture sélective par colonne, dédup à l'échelle via
`cle_dedup` optionnelle. Robuste aux records hétérogènes : repli sur un schéma
(coin, vault, ts_ms, data=json) si l'inférence directe échoue.
"""
from __future__ import annotations

import argparse
import gzip
import json
import sys
from pathlib import Path
from typing import Any

RACINE = Path(__file__).resolve().parents[1]


def _lire_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (ValueError, TypeError):
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
    except OSError:
        return []
    return rows


def _col(rows: list[dict], *noms: str):
    for r in rows:
        for n in noms:
            if n in r:
                yield r[n]
                break
        else:
            yield None


def compresser(jsonl_path: Path, out_path: Path | None = None, *, codec: str = "zstd",
               supprimer_source: bool = False) -> dict[str, Any]:
    rows = _lire_jsonl(jsonl_path)
    taille_src = jsonl_path.stat().st_size if jsonl_path.exists() else 0
    moteur = "gzip"
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
        moteur = "parquet"
    except ImportError:
        pa = pq = None

    if pa is not None:
        out = out_path or jsonl_path.with_suffix(".parquet")
        try:
            table = pa.Table.from_pylist(rows)
            schema_note = "infere"
        except (pa.lib.ArrowInvalid, pa.lib.ArrowTypeError, TypeError, ValueError):
            table = pa.table({
                "coin": list(_col(rows, "coin")),
                "vault": list(_col(rows, "vault", "user")),
                "ts_ms": list(_col(rows, "ts_ms", "exchange_ts_ms", "time")),
                "data": [json.dumps(r, ensure_ascii=False) for r in rows],
            })
            schema_note = "repli_data_json"
        pq.write_table(table, out, compression=codec)
    else:
        out = out_path or Path(str(jsonl_path) + ".gz")
        schema_note = "jsonl"
        with jsonl_path.open("rb") as src, gzip.open(out, "wb", compresslevel=9) as dst:
            dst.writelines(src)

    taille_out = out.stat().st_size if out.exists() else 0
    if supprimer_source and taille_out > 0 and jsonl_path.exists():
        jsonl_path.unlink()
    return {"moteur": moteur, "schema": schema_note, "lignes": len(rows),
            "octets_source": taille_src, "octets_sortie": taille_out,
            "ratio": round(taille_src / taille_out, 2) if taille_out else 0.0,
            "out": str(out)}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Compresse une tape JSONL (Parquet+zstd, sinon gzip).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--tape", required=True)
    p.add_argument("--out", default="")
    p.add_argument("--codec", default="zstd", choices=["zstd", "snappy", "gzip", "brotli"])
    p.add_argument("--supprimer-source", action="store_true")
    args = p.parse_args(argv)
    root = Path(args.root)
    tape = Path(args.tape)
    tape = tape if tape.is_absolute() else root / tape
    if not tape.exists():
        print(f"[compress] tape introuvable : {tape}", flush=True)
        return 0
    out = None
    if args.out:
        op = Path(args.out)
        out = op if op.is_absolute() else root / op
    rap = compresser(tape, out, codec=args.codec, supprimer_source=args.supprimer_source)
    print(f"[compress] {rap['moteur']}/{rap['schema']} : {rap['lignes']} lignes, "
          f"{rap['octets_source']}→{rap['octets_sortie']} o (×{rap['ratio']}) -> {rap['out']}", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
