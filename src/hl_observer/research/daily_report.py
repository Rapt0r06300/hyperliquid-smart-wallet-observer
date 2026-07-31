"""ALPHA P61 — RAPPORT quotidien compact depuis le registre : tableaux, pas de prose.

Compte new trials / KILL / MORE_DATA / OOS candidates / forward candidates, liste les candidats vivants et
les data gaps (BLOCKED_EXTERNAL). Sortie markdown minimale. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import collections
from collections.abc import Mapping, Sequence
from typing import Any


def synthese(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Comptes par verdict + listes candidats/blocked."""
    c = collections.Counter(str(r.get("verdict", "?")) for r in rows)
    candidats = [r for r in rows if str(r.get("verdict", "")).startswith(("CANDIDAT", "OOS_POSITIF", "ANTICIPATEUR", "PROMOTE"))]
    blocked = [r for r in rows if str(r.get("verdict")) == "BLOCKED_EXTERNAL"]
    return {"n_trials": len(rows), "par_verdict": dict(c),
            "n_candidats": len(candidats), "candidats": candidats, "n_blocked": len(blocked), "blocked": blocked}


def rapport_markdown(rows: Sequence[Mapping[str, Any]]) -> str:
    s = synthese(rows)
    lignes = ["# ALPHA — rapport", "", f"trials={s['n_trials']}  candidats={s['n_candidats']}  blocked={s['n_blocked']}", "",
              "| verdict | n |", "|---|---|"]
    for v, n in sorted(s["par_verdict"].items(), key=lambda kv: -kv[1]):
        lignes.append(f"| {v} | {n} |")
    if s["candidats"]:
        lignes += ["", "## Candidats vivants", "| idea | net | lcb | verdict |", "|---|---|---|---|"]
        for r in s["candidats"]:
            lignes.append(f"| {r.get('idea','?')} | {r.get('net_bps','?')} | {r.get('lcb_net_bps','?')} | {r.get('verdict')} |")
    return "\n".join(lignes)


__all__ = ["synthese", "rapport_markdown"]
