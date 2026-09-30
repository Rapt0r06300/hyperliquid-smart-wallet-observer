"""SHADOW multi-seuils relatifs × buckets d'ÂGE RÉEL (rectif Flo 24/07).

PUR : lit le journal de fills (OPEN candidats : coin, vault, dir, sz, px, âge réel du fill) + la tape de
prix + les TVL des vaults, et mesure le rendement forward NET pour une GRILLE de seuils relatifs
(frac × TVL, clampé [floor, plafond]) × buckets d'âge réel — pour DÉCOUVRIR où l'edge disparaît (le gate
5 s est un PLAFOND de sécurité, pas une cible). Écrit une variante VERSIONNÉE. Ne modifie JAMAIS la
cohorte live — c'est de la mesure en shadow. Aucun réseau, aucune écriture d'ordre.
"""
from __future__ import annotations

import json
from pathlib import Path

JOURNAL_RELPATH = Path("runtime") / "data" / "fills_journal.jsonl"
SCORES_RELPATH = Path("runtime") / "data" / "vaults_scores.json"
SORTIE_RELPATH = Path("runtime") / "data" / "raw_shadow_variantes.json"

FRACS = [0.0005, 0.001, 0.002, 0.004, 0.008]        # seuils relatifs testés : 0.05 % .. 0.8 % du TVL
FLOOR_USD, PLAFOND_USD = 150.0, 2000.0              # mêmes bornes que le déclencheur live (clamp)
BUCKETS = [("<1s", -1e18, 1000.0), ("1-2s", 1000.0, 2000.0), ("2-5s", 2000.0, 5000.0),
           ("5-30s", 5000.0, 30000.0), (">30s", 30000.0, 1e18)]   # âge réel = recu_ms − fill_ts_ms


def _tvl_par_prefixe(root: Path) -> dict:
    """TVL par vault, CLÉ = préfixe 12 car. (le journal tronque le vault à 12) pour pouvoir joindre."""
    try:
        d = json.loads((root / SCORES_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {}
    for c in (d.get("classement") or []):
        v = c.get("vault")
        if v:
            out[str(v)[:12]] = float((c.get("facteurs") or {}).get("tvl_usd") or 0.0)
    return out


def _bucket(age_ms: float) -> str:
    for nom, lo, hi in BUCKETS:
        if lo <= age_ms < hi:
            return nom
    return ">30s"


def mesurer(root: str | Path, *, tape: dict | None = None, horizon_ms: float = 3_600_000.0,
            frais_bps: float = 12.0, variante: str = "v1") -> dict:
    """Grille (frac_tvl × bucket_âge) du rendement forward NET des OPEN candidats. Rend le payload versionné."""
    from hl_observer.experimental.copy_edge_forward import rendement_forward, charger_prix_tape
    root = Path(root)
    tape = tape if tape is not None else charger_prix_tape(root)
    tvl = _tvl_par_prefixe(root)
    try:
        lignes = (root / JOURNAL_RELPATH).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        lignes = []
    cells = {f: {b[0]: [] for b in BUCKETS} for f in FRACS}
    n_open = 0
    for l in lignes:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        dir_bas = str(d.get("dir") or "").lower()
        if "open" not in dir_bas:
            continue
        coin = str(d.get("coin") or "").upper()
        serie = (tape or {}).get(coin)
        if not serie:
            continue
        notional = abs(float(d.get("sz") or 0.0)) * float(d.get("px") or 0.0)
        if notional <= 0:
            continue                                             # anciennes lignes sans sz/px -> ignorées
        direction = -1 if "short" in dir_bas else 1
        r = rendement_forward({"ts_ms": d.get("fill_ts_ms") or 0, "direction": direction}, serie, horizon_ms)
        if r is None:
            continue
        net = r - frais_bps
        bkt = _bucket(float(d.get("latence_fill_decision_ms") or 0.0))
        t = tvl.get(str(d.get("vault") or "")[:12], 0.0)
        n_open += 1
        for f in FRACS:
            seuil = min(max(FLOOR_USD, f * t), PLAFOND_USD) if t > 0 else 200.0
            if notional >= seuil:
                cells[f][bkt].append(net)
    grille = []
    for f in FRACS:
        for nom, _lo, _hi in BUCKETS:
            xs = cells[f][nom]
            grille.append({"frac_tvl": f, "bucket_age": nom, "n": len(xs),
                           "net_bps_moyen": round(sum(xs) / len(xs), 3) if xs else None,
                           "positif": bool(xs and sum(xs) / len(xs) > 0)})
    return {"variante": variante, "n_open_journal": n_open, "horizon_ms": horizon_ms, "frais_bps": frais_bps,
            "fracs": FRACS, "buckets": [b[0] for b in BUCKETS], "floor_usd": FLOOR_USD,
            "plafond_usd": PLAFOND_USD, "grille": grille}


def ecrire(root: str | Path, **kw) -> Path:
    payload = mesurer(root, **kw)
    p = Path(root) / SORTIE_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)
    return p


__all__ = ["mesurer", "ecrire", "FRACS", "BUCKETS", "JOURNAL_RELPATH", "SORTIE_RELPATH"]
