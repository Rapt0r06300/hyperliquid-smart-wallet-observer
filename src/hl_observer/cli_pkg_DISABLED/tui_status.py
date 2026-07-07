"""TUI status (V12, repo 08): plain-text read-only status block for terminals.

Renders a snapshot into text. NO external action, NO order surface — display only.
"""

from __future__ import annotations


def render_status(snapshot: dict) -> str:
    lines = [
        "HYPERSMART OBSERVER — PAPER SIMULATION (read-only)",
        f"  mode            : {snapshot.get('mode', 'LIVE')}",
        f"  ws              : {'ON' if snapshot.get('ws_connected') else 'OFF'}",
        f"  open positions  : {int(snapshot.get('open_positions', 0))}",
        f"  paper pnl (usdc): {float(snapshot.get('paper_pnl_usdc', 0.0)):+.2f}",
        f"  no_trade (last) : {snapshot.get('last_no_trade', '-')}",
        "  real orders     : 0  (simulation only)",
    ]
    return "\n".join(lines)


__all__ = ["render_status"]
