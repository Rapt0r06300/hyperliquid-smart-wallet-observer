"""LIQUIDATION_CASCADE_RAPID_V1 — mesure la RÉVERSION après flux forcé (liquidations), sur DONNÉES RÉELLES.
PUR, 0 réseau, 0 ordre. Réutilise `overshoots_liquidation.jsonl` (déjà collecté : overshoot_bps, sens, mid_at_event,
mid_fwd_15/30/60/120s, reversion_bps) + les helpers testés de `rapid_alpha_run` (épisodes, 2 fenêtres, leave-one-out).

Idée : après un SELL_OVERSHOOT (liquidations forcées → mark SOUS l'oracle), on FADE = on ACHÈTE et on parie la
réversion vers l'oracle ; BUY_OVERSHOOT → on VEND. On sépare CONTINUATION (le mark s'enfonce encore) de REVERSAL.
Coûts HL conservateurs (le fichier n'a que le MID → raffinement bid/ask = join bbo, noté). Filtre coins liquides
(sinon mid gelé = artefact). Placebo directionnel (−gross−coûts) + temporel. Variantes pré-enregistrées PEU nombreuses.
"""
from __future__ import annotations

import importlib.util
import json
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("rapid_alpha_run", RACINE / "tools" / "rapid_alpha_run.py")
RAR = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(RAR)

OVERSHOOTS = RACINE / "runtime" / "data" / "overshoots_liquidation.jsonl"
SORTIE = RACINE / "runtime" / "rapports" / "liquidation_cascade"
HORIZONS_S = (15, 30, 60, 120)                       # présents dans le fichier ; 1/3/5 s = join bbo (NON_MESURABLE ici)
COINS_LIQUIDES = {"BTC", "ETH", "SOL", "AVAX", "INJ", "LINK", "DASH", "NEO", "DOGE", "XRP", "SUI", "WLD",
                  "ARB", "OP", "APT", "SEI", "TIA", "PEPE", "BNB", "LTC", "AAVE", "ORDI", "RNDR"}
FEE_AR_BPS = 9.0
SPREAD_EST_BPS = 3.0                                  # estimation conservatrice (mid-only) ; raffiner via bbo bid/ask
SLIPPAGE_BPS = 1.0
COUT_AR_BPS = FEE_AR_BPS + SPREAD_EST_BPS + SLIPPAGE_BPS   # ~13 bps A/R
EPISODE_GAP_MS = 5000.0                               # liquidations contiguës même coin/sens < 5 s = 1 cascade


def charger(path: Path, *, min_overshoot_bps: float) -> list:
    """Événements filtrés : coin liquide, |overshoot| ≥ seuil, mid valide, au moins un forward NON gelé."""
    out = []
    for L in path.open(encoding="utf-8", errors="ignore"):
        L = L.strip()
        if not L:
            continue
        try:
            d = json.loads(L)
        except (ValueError, TypeError):
            continue
        coin = d.get("coin")
        mid = d.get("mid_at_event")
        sens = d.get("sens", "")
        ov = d.get("overshoot_bps")
        t = d.get("ts_ms")
        if not coin or coin not in COINS_LIQUIDES or not mid or mid <= 0 or not isinstance(t, (int, float)):
            continue
        if ov is None or abs(ov) < min_overshoot_bps:
            continue
        fwd = {h: d.get("mid_fwd_%ds" % h) for h in HORIZONS_S}
        if not any(isinstance(v, (int, float)) and abs(v - mid) > 1e-12 for v in fwd.values()):
            continue                                 # mid gelé partout → artefact illiquide, exclu
        out.append({"coin": coin, "t": int(t), "mid": float(mid), "sens": sens,
                    "overshoot_bps": float(ov), "fwd": fwd})
    out.sort(key=lambda e: (e["coin"], e["t"]))
    return out


def episodes_liq(events: list) -> list:
    """1 obs = 1 épisode : liquidations contiguës même coin+sens espacées < EPISODE_GAP_MS → garde la 1re."""
    out, dernier = [], {}
    for e in events:
        cle = (e["coin"], e["sens"])
        d = dernier.get(cle)
        if d is None or e["t"] - d >= EPISODE_GAP_MS:
            out.append(e)
            dernier[cle] = e["t"]
    return out


def mesurer(ev: dict) -> dict:
    """FADE : SELL_OVERSHOOT → long (dir +1, parie réversion HAUT) ; BUY_OVERSHOOT → short (dir −1).
    net = dir·(fwd−mid)/mid·1e4 − coût A/R. gross (pour placebo) = même sans coût. REVERSAL si gross>0."""
    dir_ = 1 if "SELL" in ev["sens"] else -1
    par_h = {}
    for h in HORIZONS_S:
        f = ev["fwd"].get(h)
        if not isinstance(f, (int, float)) or abs(f - ev["mid"]) < 1e-12:
            par_h[str(h)] = {"statut": "NON_MESURABLE"}
            continue
        gross = dir_ * (f - ev["mid"]) / ev["mid"] * 1e4
        par_h[str(h)] = {"statut": "OK", "gross_bps": round(gross, 3),
                         "net_bps": round(gross - COUT_AR_BPS, 3),
                         "type": "REVERSAL" if gross > 0 else "CONTINUATION"}
    return {"statut": "OK", "coin": ev["coin"], "t": ev["t"], "heure": int((ev["t"] // 3_600_000) % 24),
            "dir": dir_, "overshoot_bps": ev["overshoot_bps"], "par_horizon": par_h}


def _pf(nets):
    pos = sum(x for x in nets if x > 0); neg = sum(-x for x in nets if x < 0)
    return round(pos / neg, 3) if neg > 0 else (float("inf") if pos > 0 else 0.0)


def analyser(events: list, horizon_ref: int) -> dict:
    eps = episodes_liq(events)
    mes = [mesurer(e) for e in eps]
    def nets(h): return [m["par_horizon"][str(h)]["net_bps"] for m in mes if m["par_horizon"].get(str(h), {}).get("statut") == "OK"]
    def gross(h): return [m["par_horizon"][str(h)]["gross_bps"] for m in mes if m["par_horizon"].get(str(h), {}).get("statut") == "OK"]
    types = {}
    for m in mes:
        r = m["par_horizon"].get(str(horizon_ref), {})
        if r.get("statut") == "OK":
            types[r["type"]] = types.get(r["type"], 0) + 1
    nH = nets(horizon_ref)
    placebo_dir = [-g - COUT_AR_BPS for g in gross(horizon_ref)]
    return {
        "n_episodes": len(eps),
        "net_bps_par_horizon": {str(h): round(sum(nets(h)), 2) for h in HORIZONS_S},
        "net_moyen_bps_par_horizon": {str(h): (round(sum(nets(h)) / len(nets(h)), 3) if nets(h) else None) for h in HORIZONS_S},
        "gross_moyen_bps@ref": (round(sum(gross(horizon_ref)) / len(gross(horizon_ref)), 3) if gross(horizon_ref) else None),
        "continuation_vs_reversal@ref": types,
        "profit_factor@ref": _pf(nH), "drawdown_bps@ref": round(RAR.CVE._drawdown(nH), 2),
        "placebo_directionnel_net@ref": round(sum(placebo_dir), 2) if placebo_dir else None,
        "leave_one_out@ref": RAR.leave_one_out(mes, horizon_ref),
        "decision_2_fenetres@ref": RAR.deux_fenetres_ep(mes, horizon_ref),
    }


def executer(path=OVERSHOOTS, *, horizon_ref=30) -> dict:
    SORTIE.mkdir(parents=True, exist_ok=True)
    # variantes PRÉ-ENREGISTRÉES (peu nombreuses) : taille de liquidation (magnitude d'overshoot)
    variantes = {"overshoot>=30bps": 30.0, "overshoot>=80bps": 80.0, "overshoot>=150bps": 150.0}
    rap = {"ts_ms": int(time.time() * 1000), "source": path.name, "horizon_ref_s": horizon_ref,
           "cout_ar_bps": COUT_AR_BPS, "note_couts": "mid-only (fichier) ; bid/ask reel = raffinement via join bbo",
           "variantes": {}}
    armables = []
    for nom, seuil in variantes.items():
        ev = charger(path, min_overshoot_bps=seuil)
        r = analyser(ev, horizon_ref)
        r["n_events_filtres"] = len(ev)
        rap["variantes"][nom] = r
        if r["decision_2_fenetres@ref"].get("probe_armable"):
            armables.append(nom)
    rap["verdict"] = ("PROBE_ARMABLE:" + ",".join(armables)) if armables else "PAS_ENCORE_PROBE"
    (SORTIE / "liquidation_cascade_go_nogo.json").write_text(json.dumps(rap, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return rap


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--horizon", type=int, default=30)
    a = ap.parse_args()
    r = executer(horizon_ref=a.horizon)
    print("VERDICT:", r["verdict"], "· horizon_ref:", r["horizon_ref_s"], "s · coût A/R:", r["cout_ar_bps"], "bps")
    for nom, x in r["variantes"].items():
        print("  [%s] events=%d episodes=%d net@%ds=%s net_moyen=%s PF=%s C/R=%s placebo=%s probe=%s" % (
            nom, x["n_events_filtres"], x["n_episodes"], a.horizon,
            x["net_bps_par_horizon"][str(a.horizon)], x["net_moyen_bps_par_horizon"][str(a.horizon)],
            x["profit_factor@ref"], x["continuation_vs_reversal@ref"], x["placebo_directionnel_net@ref"],
            x["decision_2_fenetres@ref"].get("probe_armable")))
