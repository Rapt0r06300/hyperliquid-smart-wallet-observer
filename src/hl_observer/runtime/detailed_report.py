"""Rapport ultra-détaillé UNIFIÉ — voir ABSOLUMENT tout ce que fait le bot.

Agrège en une seule vue (sans rien dupliquer) :
  * les flux détaillés bornés (detailed_logger) : trades, décisions, refus, erreurs,
    scan, système ;
  * le ledger PnL existant (simulation_pnl_ledger_latest.jsonl) ;
  * la courbe d'equity persistée (equity_history.jsonl) ;
  * l'état de l'enregistrement REPLAY (candidates.jsonl / marks.jsonl : lignes + taille).

But : d'un coup d'œil, savoir ce qu'il gagne/perd, ses positions, chaque décision et
CHAQUE erreur même minuscule — et confirmer que le replay a bien de la donnée.

Usage : ``python -m hl_observer.runtime.detailed_report [--errors N] [--json]``
Lecture seule, best-effort, ne lève jamais.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


def _state_dir() -> Path:
    env = os.getenv("HYPERSMART_UI_STATE_DIR", "").strip()
    return Path(env) if env else Path("runtime/data")


def _read_jsonl(p: Path, *, max_lines: int | None = None) -> list[dict]:
    try:
        if not p.exists():
            return []
        lines = p.read_text(encoding="utf-8").splitlines()
        if max_lines:
            lines = lines[-int(max_lines):]
        out = []
        for ln in lines:
            try:
                out.append(json.loads(ln))
            except Exception:
                continue
        return out
    except Exception:
        return []


def _find_ledger() -> Path | None:
    for c in ("logs", "runtime/data/logs", "runtime/logs", "logs/logs à envoyer",
              "runtime/data"):
        p = Path(c) / "simulation_pnl_ledger_latest.jsonl"
        if p.exists():
            return p
    return None


def _replay_status() -> dict:
    base = Path(os.getenv("HYPERSMART_V26_RECORD_PATH", "") or "runtime/replay")
    out: dict[str, Any] = {"dir": str(base), "enabled": os.getenv(
        "HYPERSMART_V26_RECORD_CANDIDATES", "0").strip().lower() in {"1", "true", "yes", "on"}}
    for name in ("candidates.jsonl", "marks.jsonl"):
        n, sz = 0, 0
        try:
            from hl_observer.runtime.replay_recorder import iter_replay_files
            for p in iter_replay_files(base, name):  # agrege les fichiers par-process
                try:
                    n += sum(1 for _ in p.open(encoding="utf-8"))
                    sz += p.stat().st_size
                except Exception:
                    continue
        except Exception:
            n, sz = 0, 0
        out[name] = {"lines": n, "bytes": sz, "mb": round(sz / 1e6, 2)}
    return out


def gather(*, errors: int = 40, runtime_data_dir: str | Path | None = None) -> dict:
    from hl_observer.runtime import detailed_logger as dl
    rt = str(runtime_data_dir) if runtime_data_dir else str(_state_dir())
    ledger = _find_ledger()
    ledger_rows = _read_jsonl(ledger, max_lines=400) if ledger else []
    try:
        from hl_observer.runtime.equity_history_store import read_equity_points
        eq = read_equity_points(max=600, runtime_data_dir=rt)
    except Exception:
        eq = []
    last_eq = eq[-1] if eq else None
    return {
        "summary": dl.summary(runtime_data_dir=rt),
        "errors": dl.read("error", max=errors, runtime_data_dir=rt),
        "trades": dl.read("trade", max=30, runtime_data_dir=rt),
        "decisions": dl.read("decision", max=20, runtime_data_dir=rt),
        "refusals": dl.read("refusal", max=20, runtime_data_dir=rt),
        "system": dl.read("system", max=10, runtime_data_dir=rt),
        "equity_last": last_eq,
        "equity_points": len(eq),
        "pnl_ledger_file": str(ledger) if ledger else None,
        "pnl_ledger_rows": len(ledger_rows),
        "pnl_ledger_tail": ledger_rows[-5:],
        "replay": _replay_status(),
    }


def render_text(rep: dict) -> str:
    L: list[str] = []
    L.append("=" * 68)
    L.append("  HYPERSMART — RAPPORT ULTRA-DÉTAILLÉ (read-only)")
    L.append("=" * 68)
    s = rep.get("summary", {})
    L.append("Flux bornés (compte / dernière entrée) :")
    for cat in ("trade", "decision", "refusal", "position", "error", "scan", "system"):
        info = s.get(cat, {}) or {}
        L.append(f"  {cat:9s} : {info.get('count', 0):>7} lignes")
    eq = rep.get("equity_last")
    if eq:
        _e = eq.get("equity", eq.get("equity_usdt"))
        _p = eq.get("pnl", eq.get("pnl_usdc"))
        L.append("")
        L.append(f"Equity : {_e} USDT | PnL {_p} USDC "
                 f"({rep.get('equity_points')} points persistés)")
    rp = rep.get("replay", {})
    L.append("")
    L.append(f"REPLAY (recording={'ON' if rp.get('enabled') else 'OFF'}) dir={rp.get('dir')}")
    for k in ("candidates.jsonl", "marks.jsonl"):
        v = rp.get(k, {})
        L.append(f"  {k:16s} : {v.get('lines', 0):>7} lignes ({v.get('mb', 0)} Mo)")
    if not rp.get("enabled"):
        L.append("  ⚠  recording OFF → le run ne produira PAS de donnée replay.")
    lg = rep.get("pnl_ledger_file")
    L.append("")
    L.append(f"Ledger PnL : {lg or 'introuvable'} ({rep.get('pnl_ledger_rows', 0)} lignes)")
    errs = rep.get("errors", [])
    L.append("")
    L.append(f"ERREURS récentes ({len(errs)}) — chaque erreur même minuscule :")
    if not errs:
        L.append("  (aucune)")
    for e in errs[-15:]:
        L.append(f"  [{e.get('sev','?')}] {e.get('where','?')} : "
                 f"{str(e.get('error', e.get('msg','')))[:90]}")
    tr = rep.get("trades", [])
    if tr:
        L.append("")
        L.append(f"TRADES récents ({len(tr)}) :")
        for t in tr[-10:]:
            L.append(f"  {t.get('action','?'):6s} {str(t.get('coin','?')):6s} "
                     f"{str(t.get('side','')):5s} pnl={t.get('net_pnl_usdc')} "
                     f"{t.get('reason','') or ''}")
    L.append("=" * 68)
    return "\n".join(L)


def main(argv: list[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="Rapport ultra-détaillé HyperSmart (read-only).")
    ap.add_argument("--errors", type=int, default=40)
    ap.add_argument("--json", action="store_true")
    ns = ap.parse_args(argv)
    rep = gather(errors=ns.errors)
    print(json.dumps(rep, ensure_ascii=False, indent=2) if ns.json else render_text(rep))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
