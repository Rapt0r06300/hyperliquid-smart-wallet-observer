#!/usr/bin/env python3
"""Affichage TEMPS RÉEL de tout ce que les collecteurs écrivent — tableau de bord terminal.

Lit les tapes de `runtime/data/` au fil de l'eau (offset incrémental, gère la rotation),
affiche par flux le total + le débit (lignes/s) et les derniers FILLS observés. Lecture seule,
n'écrit rien, n'interfère pas avec les collecteurs. Ctrl+C pour quitter.
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]

# (label, glob, est_fill)
FLUX = [
    ("Fills WS (live)",    "vault_fills_live*.jsonl",        True),
    ("Fills poll (REST)",  "vault_fills_poll*.jsonl",        True),
    ("Fills noeud local",  "node_fills_tape*.jsonl",         True),
    ("Fills TWAP",         "copy_vault_twap*.jsonl",         True),
    ("Carnets L2",         "*l2*tape*.jsonl",                False),
    ("BBO (top of book)",  "copy_vault_bbo*.jsonl",          False),
    ("Trades marche",      "copy_vault_trades*.jsonl",       False),
    ("Bougies (candles)",  "copy_vault_candle*.jsonl",       False),
    ("Positions leaders",  "copy_vault_positions*.jsonl",    False),
    ("Explorer (activite)", "explorer_tx_tape*.jsonl",       False),
]


def _nb(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def formater_fill(obj: dict) -> str | None:
    """Rend une ligne lisible pour un fill, ou None si non pertinent."""
    coin = obj.get("coin")
    px = _nb(obj.get("px") or obj.get("price"))
    sz = _nb(obj.get("sz") or obj.get("size"))
    if not coin or px is None or sz is None:
        return None
    signe = obj.get("signe")
    side = str(obj.get("side") or "").strip().lower()
    ag = str(obj.get("aggressor_side") or "").strip().lower()
    dire = str(obj.get("dir") or "").strip().lower()
    if signe in (1, "1") or side in ("b", "buy", "bid") or ag.startswith("b") or dire.startswith(("open long", "close short")):
        sens = "ACHAT"
    elif signe in (-1, "-1") or side in ("a", "s", "sell", "ask") or ag.startswith("s") or dire.startswith(("open short", "close long")):
        sens = "VENTE"
    else:
        sens = "  -  "
    vault = str(obj.get("vault") or obj.get("user") or "")
    court = (vault[:6] + ".." + vault[-4:]) if len(vault) > 12 else vault
    ts = obj.get("ts_ms") or obj.get("exchange_ts_ms") or obj.get("observed_at_ms") or obj.get("time")
    heure = "  --:--  "
    if isinstance(ts, (int, float)) and ts > 1e12:
        try:
            heure = datetime.datetime.fromtimestamp(ts / 1000).strftime("%H:%M:%S")
        except (OSError, ValueError, OverflowError):
            pass
    valeur = px * sz
    return f"{heure}  {sens:<5} {str(coin):<7} px={px:<11.6g} sz={sz:<11.6g} ~{valeur:>9.0f}$  {court}"


def _fichiers(data_dir: Path, motif: str) -> list[Path]:
    return sorted(p for p in data_dir.glob(motif) if p.is_file())


def _cls():
    os.system("cls" if os.name == "nt" else "clear")


def boucle(data_dir: Path, *, intervalle: float = 2.0, n_derniers: int = 12) -> int:
    offsets: dict[str, int] = {}
    totaux: dict[str, int] = {label: 0 for label, _, _ in FLUX}
    precedents: dict[str, int] = dict(totaux)
    maj_ts: dict[str, float] = {}
    derniers_fills: list[str] = []
    debut = time.time()
    total_initial: int | None = None
    try:
        while True:
            for label, motif, est_fill in FLUX:
                for fich in _fichiers(data_dir, motif):
                    cle = str(fich)
                    try:
                        taille = fich.stat().st_size
                    except OSError:
                        continue
                    pos = offsets.get(cle, 0)
                    if taille < pos:        # fichier reecrit (fusion) -> repart de 0
                        pos = 0
                        offsets[cle] = 0
                    if taille <= pos:
                        continue
                    try:
                        with fich.open("r", encoding="utf-8", errors="replace") as fh:
                            fh.seek(pos)
                            nouveau = fh.read()
                            offsets[cle] = fh.tell()
                    except OSError:
                        continue
                    if nouveau.strip():
                        maj_ts[label] = time.time()
                    for ligne in nouveau.splitlines():
                        ligne = ligne.strip()
                        if not ligne:
                            continue
                        totaux[label] += 1
                        if est_fill:
                            try:
                                obj = json.loads(ligne)
                            except (ValueError, TypeError):
                                continue
                            if isinstance(obj, dict):
                                txt = formater_fill(obj)
                                if txt:
                                    derniers_fills.append(txt)
            derniers_fills[:] = derniers_fills[-n_derniers:]

            _cls()
            print("=" * 72)
            print("  COLLECTE HYPERLIQUID - TEMPS REEL   (Ctrl+C pour quitter)")
            print(f"  dossier : {data_dir}")
            print("=" * 72)
            grand_total = 0
            maintenant = time.time()
            for label, _, _ in FLUX:
                t = totaux[label]
                grand_total += t
                dps = (t - precedents[label]) / intervalle
                barre = "*" if dps > 0 else "."
                if label in maj_ts:
                    age = maintenant - maj_ts[label]
                    frais = "a l'instant" if age < intervalle * 1.5 else f"il y a {int(age):>4d}s"
                else:
                    frais = "   --   "
                print(f"  {barre} {label:<20} {t:>10d}  ({dps:>6.1f}/s)  MAJ {frais}")
                precedents[label] = t
            if total_initial is None:
                total_initial = grand_total
            print("-" * 72)
            session = grand_total - total_initial
            print(f"  TOTAL : {grand_total:>10d}   |   NOUVEAUX cette session : {session:>8d}   "
                  f"|   {time.strftime('%H:%M:%S')}")
            print("=" * 72)
            print(f"  Derniers fills ({len(derniers_fills)}) :")
            if derniers_fills:
                for f in derniers_fills:
                    print(f"    {f}")
            else:
                print("    (en attente de fills... lance les collecteurs / le noeud)")
            print("=" * 72, flush=True)
            time.sleep(intervalle)
    except KeyboardInterrupt:
        print("\nArret de l'affichage.")
        return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Affichage temps reel de la collecte (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--intervalle", type=float, default=2.0)
    args = p.parse_args(argv)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    data_dir = Path(args.root) / "runtime" / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return boucle(data_dir, intervalle=max(0.5, args.intervalle))


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
