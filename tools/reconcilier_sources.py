#!/usr/bin/env python3
"""Réconciliation croisée des sources de fills — idée #73.

On capte les fills par plusieurs chemins (WS live, poll REST, nœud local, lanes GitHub) et
l'activité via l'explorer. Ce module **réconcilie** ces sources par identité de fill :
- combien de fills par source, combien en COMMUN, combien EXCLUSIFS à chaque source ;
- **trous de couverture** : fills présents dans une source mais absents d'une autre (ex. le
  nœud a un fill que la lane WS a raté → la lane a un trou) ;
- **couverture leaders** : leaders vus ACTIFS par l'explorer mais pour lesquels AUCUN fill n'a
  été capté (candidats à re-prioriser en WS/poll).

Pur, hors-ligne. Aucune écriture destructive : produit un rapport JSON. PAPER / lecture seule.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterable

RACINE = Path(__file__).resolve().parents[1]


def _vault(f: dict) -> str:
    return str(f.get("vault") or f.get("user") or "").strip().lower()


def _ts(f: dict) -> int | None:
    for k in ("ts_ms", "exchange_ts_ms", "time"):
        v = f.get(k)
        if isinstance(v, int) and v > 0:
            return v
    return None


def cle_identite(f: dict) -> tuple | None:
    """Identité robuste d'un fill, tolérante aux horodatages ~proches entre sources.

    Priorité au (tid|hash|oid) quand présent ; sinon repli sur (vault, coin, ts arrondi, px, sz).
    """
    vault = _vault(f)
    coin = f.get("coin")
    if not vault or not coin:
        return None
    ident = f.get("tid")
    if ident in (None, "", 0):
        ident = f.get("hash")
    if ident in (None, "", 0):
        ident = f.get("oid")
    if ident not in (None, "", 0):
        return (vault, str(coin), ("id", str(ident)))
    ts = _ts(f)
    if ts is None:
        return None
    px = f.get("px") or f.get("price")
    sz = f.get("sz") or f.get("size")
    return (vault, str(coin), ("ts", ts // 1000, str(px), str(sz)))  # bucket 1 s


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


def _cles(rows: Iterable[dict]) -> set[tuple]:
    out: set[tuple] = set()
    for r in rows:
        c = cle_identite(r)
        if c is not None:
            out.add(c)
    return out


def reconcilier(sources: dict[str, Iterable[dict]], *,
                users_actifs: set[str] | None = None) -> dict[str, Any]:
    """Réconcilie plusieurs sources de fills (nom -> itérable de fills)."""
    cles_par_source = {nom: _cles(rows) for nom, rows in sources.items()}
    union: set[tuple] = set()
    for s in cles_par_source.values():
        union |= s
    noms = sorted(cles_par_source)
    exclusifs: dict[str, int] = {}
    for nom in noms:
        autres: set[tuple] = set()
        for a in noms:
            if a != nom:
                autres |= cles_par_source[a]
        exclusifs[nom] = len(cles_par_source[nom] - autres)
    # trous : pour chaque paire (a,b), fills de a absents de b
    trous: dict[str, int] = {}
    for a in noms:
        for b in noms:
            if a != b:
                trous[f"{a}_absents_de_{b}"] = len(cles_par_source[a] - cles_par_source[b])
    vaults_avec_fill = {c[0] for c in union}
    rapport: dict[str, Any] = {
        "par_source": {nom: len(s) for nom, s in cles_par_source.items()},
        "union_unique": len(union),
        "exclusifs_par_source": exclusifs,
        "trous": trous,
        "vaults_avec_fill": len(vaults_avec_fill),
    }
    if users_actifs is not None:
        actifs = {u.strip().lower() for u in users_actifs if str(u).strip()}
        sans_fill = sorted(actifs - vaults_avec_fill)
        rapport["leaders_actifs_vus"] = len(actifs)
        rapport["leaders_actifs_sans_fill"] = len(sans_fill)
        rapport["echantillon_sans_fill"] = sans_fill[:20]
    return rapport


def _charger_users_explorer(path: Path) -> set[str]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    users = data.get("users") or data.get("users_actifs") or data.get("decouverts") or []
    if isinstance(users, dict):
        users = list(users.keys())
    return {str(u).strip().lower() for u in users if str(u).strip().lower().startswith("0x")}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Reconcilie les sources de fills (lecture seule, rapport JSON).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--source", action="append", default=[], metavar="NOM=CHEMIN",
                   help="source de fills, répétable (ex. ws=runtime/data/vault_fills_live.jsonl)")
    p.add_argument("--explorer-users", default="", help="JSON users découverts (couverture leaders)")
    p.add_argument("--out", default="")
    args = p.parse_args(argv)
    root = Path(args.root)
    sources: dict[str, list[dict]] = {}
    for spec in args.source:
        if "=" not in spec:
            continue
        nom, chemin = spec.split("=", 1)
        pp = Path(chemin)
        pp = pp if pp.is_absolute() else root / pp
        sources[nom.strip()] = _lire_jsonl(pp)
    if not sources:
        print("[reconcilier] aucune source (--source nom=chemin).", flush=True)
        return 0
    users = None
    if args.explorer_users:
        up = Path(args.explorer_users)
        up = up if up.is_absolute() else root / up
        users = _charger_users_explorer(up)
    rap = reconcilier(sources, users_actifs=users)
    txt = json.dumps(rap, ensure_ascii=False, indent=2)
    if args.out:
        op = Path(args.out)
        op = op if op.is_absolute() else root / op
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(txt, encoding="utf-8")
    print(txt, flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
