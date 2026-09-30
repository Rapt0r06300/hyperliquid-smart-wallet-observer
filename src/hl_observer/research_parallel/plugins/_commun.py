"""Helpers PARTAGÉS des plugins de la vague 1. Lecture SEULE : les plugins lisent le bbo_tape du main
(runtime/data, jamais écrit) et la data isolée du labo (runtime/research_lab/data). Format de signal commun.

Tout est PUR/déterministe pour être testable. Aucun réseau, aucun /exchange.
"""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.research_parallel import isolation as ISO


def signal(ts_ms, coin, sens, variante, **extra) -> dict:
    """Ligne de signal SHADOW (jamais un ordre). sens +1 = biais long, −1 = biais short."""
    return {"kind": "SIGNAL_SHADOW", "ts_ms": int(ts_ms), "coin": str(coin), "sens": int(sens),
            "variante": variante, "real_execution": False, **extra}


def charger_lab_jsonl(root: Path, flux: str, *, limite: int | None = 20000) -> list[dict]:
    """Lit research_lab/data/<flux>.jsonl (data isolée du labo). Vide si absent (deny-by-default)."""
    p = ISO.lab_root(root) / "data" / ("%s.jsonl" % flux)
    out = []
    try:
        lignes = p.read_text(encoding="utf-8").splitlines()
        if limite:
            lignes = lignes[-limite:]
        for l in lignes:
            if not l.strip():
                continue
            try:
                out.append(json.loads(l))
            except ValueError:
                continue
    except OSError:
        return []
    return out


def series_par_coin(recs: list[dict], champ: str, *, ts_champ: str = "ts_wall_ms") -> dict:
    """{coin: [(ts, valeur)] trié} pour un champ d'une liste de lignes ctx. Ignore les None."""
    out: dict[str, list] = {}
    for r in recs:
        c = r.get("coin"); v = r.get(champ); t = r.get(ts_champ)
        if c is None or v is None or t is None:
            continue
        try:
            out.setdefault(str(c), []).append((float(t), float(v)))
        except (TypeError, ValueError):
            continue
    for c in out:
        out[c].sort()
    return out


def prix_bbo_hl(root: Path, coins, *, ds_ms: float = 5000.0, limite_lignes: int = 400000) -> dict:
    """{coin: [(ts_wall_ms, bid, ask)] trié} depuis le bbo_tape HL du main (LECTURE SEULE, jamais écrit).
    Downsample 1/ds_ms pour rester léger. Vide si le tape est absent."""
    p = Path(root) / "runtime" / "data" / "bbo_tape.jsonl"
    cible = set(coins)
    out: dict[str, list] = {c: [] for c in coins}
    last: dict[tuple, int] = {}
    try:
        with p.open(encoding="utf-8", errors="ignore") as f:
            for i, l in enumerate(f):
                if i >= limite_lignes:
                    break
                if '"HL"' not in l:
                    continue
                try:
                    q = json.loads(l)
                except ValueError:
                    continue
                if q.get("venue") != "HL":
                    continue
                c = q.get("coin")
                if c not in cible:
                    continue
                ts = q.get("ts_wall_ms"); b = q.get("bid"); a = q.get("ask")
                if ts is None or not b or not a or a <= b:
                    continue
                bk = int(ts // ds_ms)
                if last.get((c,)) == bk:
                    continue
                last[(c,)] = bk
                out[c].append((float(ts), float(b), float(a)))
    except OSError:
        return {c: [] for c in coins}
    return out


def regime_courant(root: Path) -> dict:
    """Régime écrit par REGIME_ROUTER. Absent -> régime permissif par défaut (aucun plugin bloqué),
    mais deny-by-default sur la QUALITÉ : sans mesure, un plugin doit lui-même s'abstenir si sa data manque."""
    p = ISO.lab_root(root) / "data" / "regime.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"autorises": None}          # None = pas de filtre (le routeur n'a pas encore tourné)


def autorise(regime: dict, plugin_id: str) -> bool:
    aut = regime.get("autorises")
    return True if aut is None else (plugin_id in aut)


__all__ = ["signal", "charger_lab_jsonl", "series_par_coin", "prix_bbo_hl", "regime_courant", "autorise"]
