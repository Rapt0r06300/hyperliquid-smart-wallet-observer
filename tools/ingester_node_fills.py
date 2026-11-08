#!/usr/bin/env python3
"""Lecteur/convertisseur des fills d'un NŒUD Hyperliquid LOCAL — idées #5, #11, #31.

Un nœud Hyperliquid (logiciel libre, gratuit) écrit en continu ``node_fills_by_block``
= TOUS les fills de TOUS les users, par bloc, au format API. Ce lecteur scanne le
dossier de données du nœud, normalise chaque fill au schéma du coffre, et écrit une
tape ``runtime/data/node_fills_tape.jsonl`` (dédup par identité). Aucun cap, aucun coût
(on lit les fichiers que NOTRE nœud écrit). PAPER / LECTURE SEULE.

Le format exact varie selon la version du nœud : on gère de façon DÉFENSIVE les formes
courantes (``{events:[[user, fill|[fills]], ...], block_time, block_number}`` ou
``{fills:[{user, ...}]}`` ou une liste brute). Marqué ``source="NODE_FILLS"`` :
source de MESURE (densifie les jours), pas détourné en signal « live » causal.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Iterator

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

OUT_DEFAUT = Path("runtime") / "data" / "node_fills_tape.jsonl"
SOURCE_ID = "hyperliquid_node_fills"


def _nb(v):
    try:
        import math
        f = float(v)
        return f if math.isfinite(f) else None
    except (TypeError, ValueError):
        return None


def _int(v):
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().isdecimal():
        return int(v.strip())
    return None


_SIDE_ACHAT = {"b", "buy", "bid"}
_SIDE_VENTE = {"a", "s", "sell", "ask"}


def _signe(f: dict) -> int | None:
    s = f.get("signe")
    if s in (-1, 1):
        return s
    side = str(f.get("side") or "").strip().lower()
    if side in _SIDE_ACHAT:
        return 1
    if side in _SIDE_VENTE:
        return -1
    d = str(f.get("dir") or "").lower()
    if d.startswith(("open long", "close short", "buy")):
        return 1
    if d.startswith(("open short", "close long", "sell")):
        return -1
    return None


def extraire_fills(obj: Any) -> list[tuple[str, dict, int | None, Any]]:
    """Rend une liste de (user, fill, block_time_ms|None, block) depuis une ligne node."""
    out: list[tuple[str, dict, int | None, Any]] = []
    if isinstance(obj, dict):
        bt = _int(obj.get("block_time") or obj.get("blockTime") or obj.get("time"))
        block = obj.get("block_number") or obj.get("block") or obj.get("height")
        for ev in obj.get("events") or []:
            if isinstance(ev, (list, tuple)) and len(ev) >= 2:
                user = str(ev[0] or "")
                payload = ev[1]
                fills = payload if isinstance(payload, list) else [payload]
                for f in fills:
                    if isinstance(f, dict):
                        out.append((user, f, bt, block))
        for f in obj.get("fills") or []:
            if isinstance(f, dict):
                out.append((str(f.get("user") or ""), f, bt, block))
    elif isinstance(obj, list):
        for item in obj:
            if isinstance(item, (list, tuple)) and len(item) >= 2 and isinstance(item[1], dict):
                out.append((str(item[0] or ""), item[1], None, None))
            elif isinstance(item, dict) and item.get("user"):
                out.append((str(item.get("user")), item, None, None))
    return out


def parser_fill_node(user: str, f: dict, block_time_ms: int | None, block: Any,
                     *, now_ms: int) -> dict[str, Any] | None:
    """Normalise un fill node -> schéma coffre (vault/coin/px/sz/signe/ts_ms/source)."""
    user = str(user or "").strip().lower()
    coin = f.get("coin")
    px, sz = _nb(f.get("px")), _nb(f.get("sz"))
    ts = _int(f.get("time")) or _int(f.get("ts_ms"))
    if not user.startswith("0x") or not coin or px is None or px <= 0 or sz is None or sz <= 0 or not ts:
        return None
    if ts > now_ms + 5_000:
        return None
    signe = _signe(f)
    if signe not in (-1, 1):
        return None
    observed = block_time_ms if (block_time_ms and block_time_ms >= ts) else ts
    return {
        "vault": user, "coin": str(coin), "px": px, "sz": sz, "signe": signe,
        "ts_ms": ts, "observed_at_ms": observed, "isSnapshot": False, "is_snapshot": False,
        "dir": f.get("dir"), "hash": f.get("hash"), "tid": f.get("tid"), "oid": f.get("oid"),
        "block": block, "source": "NODE_FILLS", "source_id": SOURCE_ID,
    }


def _iter_lignes(path: Path) -> Iterator[str]:
    import gzip
    ouvre = gzip.open if path.suffix == ".gz" else open
    try:
        with ouvre(path, "rt", encoding="utf-8", errors="replace") as h:  # type: ignore[operator]
            for ligne in h:
                yield ligne
    except OSError:
        return


def _fichiers_node(node_dir: Path) -> list[Path]:
    trouves: list[Path] = []
    for dossier, _sous, fichiers in os.walk(node_dir):
        for nom in fichiers:
            p = Path(dossier) / nom
            if "node_fills" in nom or "node_trades" in nom or nom.endswith((".jsonl", ".jsonl.gz")):
                if p.is_file() and not p.is_symlink():
                    trouves.append(p)
    return sorted(trouves)


def ingerer(node_dir: Path, out_path: Path, *, leaders: set[str] | None = None,
            now_ms: int | None = None) -> dict[str, Any]:
    now_ms = int(now_ms if now_ms is not None else time.time() * 1000)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    vus: set[tuple] = set()
    ecrits = 0
    lignes_lues = 0
    fichiers = _fichiers_node(node_dir)
    with out_path.open("w", encoding="utf-8") as sortie:
        for path in fichiers:
            for brut in _iter_lignes(path):
                brut = brut.strip()
                if not brut:
                    continue
                lignes_lues += 1
                try:
                    obj = json.loads(brut)
                except (ValueError, TypeError):
                    continue
                for user, f, bt, block in extraire_fills(obj):
                    row = parser_fill_node(user, f, bt, block, now_ms=now_ms)
                    if row is None:
                        continue
                    if leaders is not None and row["vault"] not in leaders:
                        continue
                    cle = (row["vault"], row["coin"], row["ts_ms"], row.get("tid"),
                           row.get("hash"), row.get("oid"), row["px"], row["sz"], row["signe"])
                    if cle in vus:
                        continue
                    vus.add(cle)
                    sortie.write(json.dumps(row, ensure_ascii=False) + "\n")
                    ecrits += 1
    return {"fichiers": len(fichiers), "lignes_lues": lignes_lues, "fills_ecrits": ecrits,
            "out": str(out_path)}


def _charger_leaders(root: Path, chemin: str | None) -> set[str] | None:
    if not chemin:
        return None
    try:
        data = json.loads((root / chemin).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    vaults = data.get("vaults") if isinstance(data, dict) else data
    if not isinstance(vaults, list):
        return None
    return {str(v).strip().lower() for v in vaults if str(v).strip().lower().startswith("0x")}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Ingester les fills d'un noeud Hyperliquid local (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--node-dir", required=True, help="dossier de donnees du noeud (node_fills_by_block)")
    p.add_argument("--leaders-file", default="", help="filtre optionnel sur ces leaders")
    p.add_argument("--out", default="")
    args = p.parse_args(argv)
    root = Path(args.root)
    node_dir = Path(args.node_dir)
    if not node_dir.is_dir():
        print(f"[node] dossier noeud introuvable : {node_dir} (lance d'abord un noeud HL local).", flush=True)
        return 0
    out = Path(args.out) if args.out else (root / OUT_DEFAUT)
    leaders = _charger_leaders(root, args.leaders_file) if args.leaders_file else None
    rap = ingerer(node_dir, out, leaders=leaders)
    print(f"[node] {rap['fills_ecrits']} fills ecrits depuis {rap['fichiers']} fichier(s) "
          f"({rap['lignes_lues']} lignes) -> {rap['out']}", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
