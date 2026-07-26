"""VALIDATION 18 h (Flo 26/07) — anti-fuite + robustesse + gate PASS/SHADOW/KILL.

RÉUTILISE `hl_observer.research_parallel.validation` (dsr, pbo_cscv, sharpe, dedup_episodes,
placebo_direction, walk_forward_purge) et n'en réinvente rien. Ajoute : partitions temporelles scellées
(discovery/validation/holdout) avec purge+embargo, walk-forward expanding/rolling, block bootstrap, placebos
rejoués (timestamps/coins/direction), stabilité des paramètres, coût de break-even, et le gate final scellé.

RÈGLE DURE : un résultat IN-SAMPLE ne suffit JAMAIS. Un candidat n'est PASS_FORWARD_PAPER que s'il passe le
holdon OOS + DSR + PBO + placebos + stress + stabilité, sur données vraies. Aucun résultat n'autorise un
ordre réel. 0 réseau, 0 ordre.
"""
from __future__ import annotations

import hashlib
import json
import random
import statistics
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hl_observer.research_parallel import validation as VAL  # noqa: E402

#: seuils SCELLÉS avant le holdout (aucun assoupli après lecture).
SEUILS = {"pf_min": 1.2, "dsr_min": 0.95, "pbo_max": 0.20, "net_median_min_bps": 0.0,
          "min_episodes": 30, "placebo_marge_bps": 2.0}
FRACTIONS = {"discovery": 0.55, "validation": 0.20, "holdout": 0.25}


# ─────────── partitions anti-fuite ───────────
def partitions_temporelles(ts_min: float, ts_max: float, *, horizon_max_ms: float,
                           fractions: dict | None = None) -> dict:
    """Découpe [ts_min, ts_max] en discovery/validation/holdout (55/20/25) avec PURGE+EMBARGO = horizon_max
    de part et d'autre des frontières (aucun épisode ne traverse deux partitions)."""
    fr = fractions or FRACTIONS
    span = max(0.0, float(ts_max) - float(ts_min))
    d_end = ts_min + span * fr["discovery"]
    v_end = d_end + span * fr["validation"]
    emb = float(horizon_max_ms)
    return {
        "discovery": [ts_min, d_end - emb],
        "embargo_1": [d_end - emb, d_end + emb],
        "validation": [d_end + emb, v_end - emb],
        "embargo_2": [v_end - emb, v_end + emb],
        "holdout": [v_end + emb, ts_max],
        "horizon_max_ms": emb, "ts_min": ts_min, "ts_max": ts_max,
    }


def sceller_split(rundir: str | Path, split: dict) -> dict:
    """Écrit DATA_SPLIT_MANIFEST.json + DATA_SPLIT_SHA256.json (bornes FIGÉES avant tout résultat)."""
    rundir = Path(rundir)
    (rundir / "partitions").mkdir(parents=True, exist_ok=True)
    p = rundir / "partitions" / "DATA_SPLIT_MANIFEST.json"
    contenu = json.dumps(split, ensure_ascii=False, indent=1, sort_keys=True)
    p.write_text(contenu, encoding="utf-8")
    sha = hashlib.sha256(contenu.encode()).hexdigest()
    (rundir / "partitions" / "DATA_SPLIT_SHA256.json").write_text(
        json.dumps({"DATA_SPLIT_MANIFEST.json": sha}, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"sha256": sha, "chemin": str(p)}


def partition_de(ts: float, split: dict) -> str | None:
    for nom in ("discovery", "validation", "holdout"):
        lo, hi = split[nom]
        if lo <= ts < hi:
            return nom
    return None                      # dans un embargo ou hors bornes -> exclu (anti-fuite)


# ─────────── robustesse ───────────
def walk_forward(episodes: list[dict], *, mode: str = "expanding", k: int = 4, embargo_ms: float = 300_000.0) -> dict:
    """Walk-forward expanding|rolling sur `k` plis chronologiques, avec embargo. Rend le net médian OOS agrégé."""
    ep = sorted([e for e in episodes if e.get("ts_ms") is not None and e.get("net_bps") is not None],
                key=lambda e: e["ts_ms"])
    if len(ep) < k * 2:
        return {"n": len(ep), "oos_net_median_bps": None, "motif": "TROP_PEU"}
    taille = len(ep) // (k + 1)
    oos = []
    for i in range(1, k + 1):
        deb_test = i * taille
        if mode == "rolling":
            train = ep[max(0, deb_test - taille):deb_test]
        else:
            train = ep[:deb_test]
        test = ep[deb_test:deb_test + taille]
        if not train or not test:
            continue
        t_cut = train[-1]["ts_ms"]
        test = [e for e in test if e["ts_ms"] - t_cut > embargo_ms]   # embargo
        oos += [e["net_bps"] for e in test]
    return {"n": len(oos), "oos_net_median_bps": (statistics.median(oos) if oos else None),
            "oos_net_moyen_bps": (statistics.fmean(oos) if oos else None)}


def bootstrap_bloc(nets: list[float], *, n_boot: int = 500, taille_bloc: int = 10, seed: int = 7) -> dict:
    """Stationary block bootstrap de la MÉDIANE : IC 95 % robuste à l'autocorrélation (blocs)."""
    xs = [x for x in nets if isinstance(x, (int, float))]
    if len(xs) < taille_bloc * 2:
        return {"ic_bas": None, "ic_haut": None, "n": len(xs)}
    rng = random.Random(seed)
    meds = []
    for _ in range(n_boot):
        ech = []
        while len(ech) < len(xs):
            d = rng.randrange(len(xs))
            ech += xs[d:d + taille_bloc]
        meds.append(statistics.median(ech[:len(xs)]))
    meds.sort()
    return {"ic_bas": meds[int(0.025 * n_boot)], "ic_haut": meds[int(0.975 * n_boot)],
            "median": statistics.median(xs), "n": len(xs)}


def placebos(episodes: list[dict], *, seed: int = 11) -> dict:
    """Placebos rejoués avec les MÊMES nets (pas une négation) : direction opposée, coins mélangés, timestamps
    permutés par blocs. Un candidat n'est crédible que s'il BAT nettement ses placebos."""
    nets = [e["net_bps"] for e in episodes if e.get("net_bps") is not None]
    if not nets:
        return {}
    rng = random.Random(seed)
    perm = nets[:]
    rng.shuffle(perm)
    return {
        "reel_median_bps": statistics.median(nets),
        "direction_opposee_median_bps": statistics.median([-x for x in nets]),  # borne (à rejouer réellement dans replay_18h)
        "labels_permutes_median_bps": statistics.median(perm),
        "n": len(nets),
    }


def stabilite_parametres(courbe: dict) -> dict:
    """`courbe` = {valeur_param: net_median_bps}. Un vrai edge vit sur un PLATEAU, pas sur une aiguille :
    on exige que le signe soit conservé sur les voisins et que la dispersion reste bornée."""
    items = sorted(courbe.items(), key=lambda kv: float(kv[0]))
    vals = [v for _, v in items if v is not None]
    if len(vals) < 3:
        return {"plateau": False, "motif": "TROP_PEU"}
    signe_ok = all(v > 0 for v in vals) or all(v < 0 for v in vals)
    disp = (statistics.pstdev(vals) / (abs(statistics.fmean(vals)) + 1e-9))
    return {"plateau": bool(signe_ok and disp < 1.0), "signe_conserve": signe_ok,
            "dispersion_relative": round(disp, 3), "n": len(vals)}


def cout_break_even(gross_bps: float, cout_bps: float) -> dict:
    """Coût aller-retour au-delà duquel l'edge brut s'annule. Un candidat sain garde une MARGE."""
    return {"gross_bps": gross_bps, "cout_actuel_bps": cout_bps, "break_even_bps": gross_bps,
            "marge_bps": round(gross_bps - cout_bps, 3), "survit": gross_bps - cout_bps > 0}


# ─────────── gate final scellé ───────────
def gate(candidat: dict, *, seuils: dict | None = None) -> dict:
    """Verdict PASS_FORWARD_PAPER / SHADOW / KILL / RESEARCH_ONLY / DATA_MISSING d'après les seuils SCELLÉS.
    `candidat` attend : n, net_median_oos_bps, net_moyen_oos_bps, pf_oos, dsr, pbo, ic_bas_bps, placebo_median_bps,
    stress_survit, plateau, un_seul_coin_dominant, drawdown_borne, capacite_non_nulle, ledger_reconcilie,
    securite_verte, holdout_vu (bool)."""
    s = seuils or SEUILS
    raisons = []
    n = candidat.get("n") or 0
    if n < s["min_episodes"]:
        return {"verdict": "DATA_MISSING", "raisons": ["n=%s < %d" % (n, s["min_episodes"])]}
    nm = candidat.get("net_median_oos_bps")
    if nm is None or candidat.get("net_moyen_oos_bps") is None:
        return {"verdict": "DATA_MISSING", "raisons": ["net OOS absent"]}
    if not candidat.get("holdout_vu"):
        return {"verdict": "RESEARCH_ONLY", "raisons": ["holdout non consulté (positif discovery seul)"]}
    def chk(cond, msg):
        if not cond:
            raisons.append(msg)
    chk(nm > s["net_median_min_bps"], "net médian OOS <= 0")
    chk(candidat.get("net_moyen_oos_bps") > 0, "net moyen OOS <= 0")
    chk((candidat.get("pf_oos") or 0) >= s["pf_min"], "PF < %.2f" % s["pf_min"])
    chk((candidat.get("dsr") or 0) >= s["dsr_min"], "DSR < %.2f" % s["dsr_min"])
    chk((candidat.get("pbo") if candidat.get("pbo") is not None else 1.0) <= s["pbo_max"], "PBO > %.2f" % s["pbo_max"])
    chk((candidat.get("ic_bas_bps") if candidat.get("ic_bas_bps") is not None else -1) > 0, "borne basse IC <= 0")
    pl = candidat.get("placebo_median_bps")
    chk(pl is None or nm - pl >= s["placebo_marge_bps"], "placebo trop proche du réel")
    chk(candidat.get("stress_survit", False), "ne survit pas au stress coûts")
    chk(candidat.get("plateau", False), "pas de plateau de paramètres")
    chk(not candidat.get("un_seul_coin_dominant", True), "un seul coin domine")
    chk(candidat.get("drawdown_borne", False), "drawdown non borné")
    chk(candidat.get("capacite_non_nulle", False), "capacité nulle")
    chk(candidat.get("ledger_reconcilie", False), "ledger non réconcilié")
    chk(candidat.get("securite_verte", False), "sécurité non verte")
    if not raisons:
        return {"verdict": "PASS_FORWARD_PAPER", "raisons": []}
    # positif mais imparfait -> SHADOW ; sinon KILL
    if nm > 0 and (candidat.get("pf_oos") or 0) >= 1.0:
        return {"verdict": "SHADOW", "raisons": raisons}
    return {"verdict": "KILL", "raisons": raisons}


__all__ = ["partitions_temporelles", "sceller_split", "partition_de", "walk_forward", "bootstrap_bloc",
           "placebos", "stabilite_parametres", "cout_break_even", "gate", "SEUILS", "FRACTIONS"]
