"""LOT13 Part 3 — HL_SPOT_PERP_CARRY_V1 : carry DELTA-NEUTRE (long spot + short perp) sur Hyperliquid.
Mécanisme DISTINCT de tout ce qui est KILL (aucune prédiction directionnelle : on capte le FUNDING).

Découverte auto des actifs ayant SPOT ET PERP (`spotMeta`/`meta`). Entrée SEULEMENT si le funding
conservateur (+ convergence de basis) couvre TOUS les coûts (4 exécutions : ouvrir+fermer × 2 jambes) avec
une MARGE de sécurité. Horizons 6 h / 24 h / 3 j / 7 j. Delta-neutre -> le PnL vient du funding capturé
(short perp reçoit le funding quand il est positif) + convergence de basis − coûts. Sans données spot
locales, le basis est pris CONSERVATEUR (0) : on ne compte QUE le funding, jamais un gain de basis inventé.

Lecture seule, 0 ordre. Cœur PUR + mesure sur le funding réel (asset_ctx du labo)."""
from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

import recherche_14h_mecanismes as MEC  # noqa: E402

HORIZONS_H = (6, 24, 72, 168)          # 6h, 24h, 3j, 7j
COUT_AR_4EXEC_BPS = 20.0               # 4 exécutions taker (spot+perp × ouvrir+fermer), conservateur
MARGE_SECURITE = 1.5                   # le funding attendu doit couvrir 1,5× les coûts pour entrer
CAPITAL_PAR_JAMBE_USD = 10.0           # notional par jambe (2 jambes -> capital immobilisé = 2×)


def decouvrir_spot_perp(meta: dict, spot_meta: dict) -> list[str]:
    """Coins ayant PERP (meta.universe) ET SPOT (spotMeta.universe/tokens). Pur. Rend l'intersection triée."""
    perp = set()
    try:
        for a in meta.get("universe", []):
            if isinstance(a, dict) and a.get("name"):
                perp.add(str(a["name"]).upper())
    except AttributeError:
        pass
    spot = set()
    try:
        for a in spot_meta.get("universe", []):     # spot: paires ; le nom de base est dans tokens
            nom = a.get("name") if isinstance(a, dict) else None
            if nom:
                spot.add(str(nom).split("/")[0].split("-")[0].upper())
        for t in spot_meta.get("tokens", []):
            if isinstance(t, dict) and t.get("name"):
                spot.add(str(t["name"]).upper())
    except AttributeError:
        pass
    return sorted(perp & spot)


def carry_net_bps(funding_bps_h: float, horizon_h: float, *, basis_entry_bps: float = 0.0,
                  basis_exit_bps: float = 0.0, cout_ar_bps: float = COUT_AR_4EXEC_BPS) -> float:
    """PnL net d'une position carry sur `horizon_h`. Short perp -> reçoit le funding s'il est POSITIF.
    Convergence de basis = (|basis_entry| − |basis_exit|) capté. Net = funding_capté + basis_capté − coûts."""
    funding_capte = funding_bps_h * horizon_h                 # short perp reçoit (funding>0) ; paie (funding<0)
    basis_capte = abs(basis_entry_bps) - abs(basis_exit_bps)  # 0 par défaut (conservateur, pas de spot)
    return funding_capte + basis_capte - cout_ar_bps


def _funding_par_coin(ctx: list[dict]) -> dict:
    """{coin: [(ts, funding_bps_h)]} depuis asset_ctx. Le funding HL est en fraction/heure -> ×1e4 = bps/h."""
    s = defaultdict(list)
    for r in ctx:
        f = r.get("funding"); c = r.get("coin"); t = r.get("ts_wall_ms")
        if f is None or c is None or t is None:
            continue
        try:
            s[c].append((float(t), float(f) * 1e4))
        except (TypeError, ValueError):
            continue
    for c in s:
        s[c].sort()
    return s


def backtest_carry(ctx: list[dict], *, horizon_h=24, cout_ar_bps=COUT_AR_4EXEC_BPS,
                   marge=MARGE_SECURITE) -> dict:
    """Mesure le carry par coin sur le funding réel. ENTRÉE seulement si le funding moyen récent × horizon
    couvre marge×coûts (gate conservateur, aucune prédiction). Rend PnL net, ROI capital immobilisé, PF, DD,
    2 moitiés, leave-one-coin-out, turnover, capacité, stress."""
    fund = _funding_par_coin(ctx)
    episodes = []            # {coin, ts, net_bps, funding_capte_bps}
    for coin, serie in fund.items():
        if len(serie) < 4:
            continue
        # fenêtre glissante : au point i, funding "attendu" = médiane des N derniers ; entrée si couvre coûts.
        for i in range(3, len(serie)):
            f_attendu = statistics.median([x[1] for x in serie[max(0, i - 3):i]])  # bps/h attendu (passé)
            if abs(f_attendu) * horizon_h < marge * cout_ar_bps:
                continue                                    # funding insuffisant -> pas d'entrée (deny-by-default)
            sens = 1 if f_attendu > 0 else -1               # short perp si funding+, long perp si funding−
            # funding RÉALISÉ sur l'horizon (intègre le funding réel entre i et i+horizon, delta-neutre)
            t0 = serie[i][0]; t1 = t0 + horizon_h * 3600 * 1000
            realises = [x[1] for x in serie if t0 <= x[0] <= t1]
            if len(realises) < 2:
                continue
            dt_h = (min(t1, serie[-1][0]) - t0) / 3600e3
            funding_capte = sens * statistics.mean(realises) * dt_h   # capté dans le bon sens
            net = funding_capte - cout_ar_bps               # basis conservateur = 0
            episodes.append({"coin": coin, "ts_ms": t0, "net_bps": round(net, 3),
                             "funding_capte_bps": round(funding_capte, 3)})
    return _juger_carry(episodes, horizon_h, cout_ar_bps)


def _juger_carry(episodes, horizon_h, cout_ar_bps):
    n = len(episodes)
    if n < 8:
        return {"horizon_h": horizon_h, "n_episodes": n, "decision": "SHADOW", "motif": "INSUFFISANT"}
    nets = [e["net_bps"] for e in episodes]
    tri = sorted(episodes, key=lambda e: e["ts_ms"]); m = n // 2
    med = statistics.median(nets)
    med1 = statistics.median([e["net_bps"] for e in tri[:m]]); med2 = statistics.median([e["net_bps"] for e in tri[m:]])
    pos = sum(x for x in nets if x > 0); neg = sum(-x for x in nets if x < 0); pf = round(pos / neg, 3) if neg else float("inf")
    # leave-one-COIN-out : retirer le meilleur coin, rester positif ?
    par_coin = defaultdict(list)
    for e in episodes:
        par_coin[e["coin"]].append(e["net_bps"])
    contrib = {c: sum(v) for c, v in par_coin.items()}
    pire_sans = None
    if len(contrib) >= 2:
        meilleur_coin = max(contrib, key=contrib.get)
        sans = [e["net_bps"] for e in episodes if e["coin"] != meilleur_coin]
        pire_sans = round(statistics.median(sans), 3) if sans else None
    # ROI sur capital immobilisé (2 jambes) annualisé
    roi_horizon = med / 1e4 / (2 * CAPITAL_PAR_JAMBE_USD) * CAPITAL_PAR_JAMBE_USD   # net$/capital
    roi_annuel_pct = (med / 1e4) * (8760 / horizon_h) / 2 * 100                     # net_bps -> %/an sur 2 jambes
    cum = pic = dd = 0.0
    for e in tri:
        cum += e["net_bps"] / 1e4 * CAPITAL_PAR_JAMBE_USD; pic = max(pic, cum); dd = min(dd, cum - pic)
    # stress : funding ÷2 et coûts ×1,5
    net_stress = statistics.median([(e["funding_capte_bps"] / 2.0) - cout_ar_bps * 1.5 for e in episodes])
    robuste = med > 0 and med1 > 0 and med2 > 0 and pf > 1.2 and (pire_sans or -1) > 0 and net_stress > 0
    dec = "KILL" if med <= 0 or pf < 1.0 else ("ARM_PAPER" if robuste else "SHADOW")
    return {"horizon_h": horizon_h, "n_episodes": n, "coins": len(par_coin), "net_median_bps": round(med, 3),
            "funding_capte_median_bps": round(statistics.median([e["funding_capte_bps"] for e in episodes]), 3),
            "cout_ar_bps": cout_ar_bps, "roi_annuel_pct_capital": round(roi_annuel_pct, 3), "pf": pf,
            "median_moitie1_bps": round(med1, 3), "median_moitie2_bps": round(med2, 3),
            "median_sans_meilleur_coin_bps": pire_sans, "dd_usd": round(dd, 4),
            "net_median_sous_stress_bps": round(net_stress, 3), "decision": dec}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="HL_SPOT_PERP_CARRY_V1 (delta-neutre, lecture seule).")
    ap.add_argument("--root", default=str(RACINE))
    ap.add_argument("--sortie", default=str(RACINE / "docs" / "audit" / "LOT13_carry_spot_perp.json"))
    a = ap.parse_args(argv)
    root = Path(a.root)
    ctx = MEC._charger(root, "asset_ctx")
    rap = {"note": "funding perp reel (asset_ctx) ; basis CONSERVATEUR=0 (spot HL non collecte localement) ; "
                   "spotMeta/meta a decouvrir en forward (Windows).",
           "couverture": {"asset_ctx_lignes": len(ctx), "coins_funding": len(_funding_par_coin(ctx))},
           "horizons": {}}
    for h in HORIZONS_H:
        rap["horizons"][str(h)] = backtest_carry(ctx, horizon_h=h)
    Path(a.sortie).parent.mkdir(parents=True, exist_ok=True)
    Path(a.sortie).write_text(json.dumps(rap, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(rap, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
