"""[Stratégie Lead-Lag PAPER — item 13/4] Lead-Lag transformé en VRAIE stratégie paper indépendante :

  signal CAUSAL → décision (edge net prévu > 0) → entrée → sortie GELÉE (horizon fixé À L'ENTRÉE)
  → fill / missed fill → coûts (frais + demi-spread + latence causale) → ledger → PnL IS/OOS/FORWARD.

Règles dures d'honnêteté :
- la DÉCISION n'utilise QUE l'information connue au ts du signal (signe leader, mid, edge prévu) ;
  le mouvement réalisé (`delta_mid_futur`) sert au PnL, JAMAIS à décider (aucun look-ahead).
- la sortie est GELÉE : l'horizon est fixé à l'entrée ; `delta_mid_futur` EST le move jusqu'à cette
  sortie gelée (mesuré, pas choisi).
- fill modélisé (ratio de liquidité) ; en dessous du minimum → MISSED (aucune position, PnL 0, tracé).
- coûts réels soustraits ; latence via `paper_trading.latency_truth` (STRESS_ONLY).
- IS/OOS/FORWARD par ÉPISODES INDIVISIBLES (aucun épisode à cheval). Métriques + gate = lab_metriques.

Réutilise les briques canoniques (latency_truth, separer_par_episodes, lab_metriques) — pas de pipeline
parallèle. Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from hl_observer.mega_cablage.replay_driver import separer_par_episodes
from hl_observer.ops import lab_metriques as M
from hl_observer.paper_trading import latency_truth as _LT


@dataclass(frozen=True)
class SignalLeadLag:
    ts_ms: int
    coin: str
    signe_leader: int                 # +1 / -1 : direction anticipée par le leader (Binance→HL)
    mid_entree: float                 # mid HL au moment du signal (causal, connu)
    delta_mid_futur: float            # Δ prix réalisé jusqu'à la sortie GELÉE (sert au PnL, pas à décider)
    edge_bps_prevu: float             # edge causal ESTIMÉ à l'entrée (connu)
    liquidite: float = 1.0            # profondeur relative disponible (0..1) → ratio de fill
    horizon_ms: int = 1_000           # horizon de la sortie gelée (fixé à l'entrée)


def cout_total_bps(config: dict[str, Any], *, delai_sec: float = 1.0) -> float:
    """Coûts d'aller-retour en bps : frais + demi-spread + latence causale (STRESS_ONLY). Jamais nul par
    défaut : un edge doit les couvrir."""
    fee = float(config.get("fee_bps", 2.5))
    demi_spread = float(config.get("demi_spread_bps", fee))
    lat = float(_LT.latence_scalaire_stress_bps(float(delai_sec), coeff_bps_per_sec=0.20,
                                                cap_bps=15.0).get("latency_stress_bps") or 0.0)
    return round(fee + demi_spread + lat, 6)


def _bps(delta: float, mid: float) -> float:
    return (float(delta) / float(mid)) * 1e4 if mid else 0.0


def simuler_episode(sig: SignalLeadLag, *, config: dict[str, Any]) -> dict[str, Any]:
    """Simule UN épisode Lead-Lag complet. Rend un dict {statut, pnl_usd, notional, coin, ledger[...]}.
    statut ∈ {NO_TRADE, MISSED_FILL, FILLED}. Décision CAUSALE ; sortie gelée ; coûts complets."""
    notional = float(config.get("notional", 100.0))
    min_fill = float(config.get("min_fill_ratio", 0.5))
    couts = cout_total_bps(config)
    ledger: list[dict[str, Any]] = [{"evt": "SIGNAL", "ts": sig.ts_ms, "coin": sig.coin,
                                     "signe": int(sig.signe_leader), "edge_prevu_bps": sig.edge_bps_prevu}]
    # DÉCISION CAUSALE : edge net PRÉVU (connu à l'entrée) doit être > 0 après coûts. Aucun look-ahead.
    edge_net_prevu = float(sig.edge_bps_prevu) - couts
    if edge_net_prevu <= 0:
        ledger.append({"evt": "NO_TRADE", "raison": "EDGE_NET_PREVU<=0", "edge_net_prevu_bps": round(edge_net_prevu, 6)})
        return {"statut": "NO_TRADE", "pnl_usd": 0.0, "notional": 0.0, "coin": sig.coin, "ledger": ledger}
    ledger.append({"evt": "ENTREE", "mid": sig.mid_entree, "horizon_ms": sig.horizon_ms,
                   "sortie": "GELEE"})
    # FILL / MISSED : le ratio de liquidité doit atteindre le minimum, sinon on n'entre pas (honnête).
    if float(sig.liquidite) < min_fill:
        ledger.append({"evt": "MISSED_FILL", "liquidite": sig.liquidite, "min_fill_ratio": min_fill})
        return {"statut": "MISSED_FILL", "pnl_usd": 0.0, "notional": 0.0, "coin": sig.coin, "ledger": ledger}
    # SORTIE GELÉE : le PnL réalisé = alignement (signe × move réalisé) − coûts. Le move est mesuré.
    gross_bps = float(sig.signe_leader) * _bps(sig.delta_mid_futur, sig.mid_entree)
    net_bps = gross_bps - couts
    pnl_usd = round(net_bps / 1e4 * notional, 8)
    ledger.append({"evt": "SORTIE", "gross_bps": round(gross_bps, 6), "couts_bps": couts,
                   "net_bps": round(net_bps, 6)})
    ledger.append({"evt": "PNL", "pnl_usd": pnl_usd, "notional": notional})
    return {"statut": "FILLED", "pnl_usd": pnl_usd, "notional": notional, "coin": sig.coin, "ledger": ledger}


def _as_signal(x: Any) -> SignalLeadLag:
    if isinstance(x, SignalLeadLag):
        return x
    return SignalLeadLag(ts_ms=int(x.get("ts_ms") or 0), coin=str(x.get("coin") or "?"),
                         signe_leader=int(x.get("signe_leader") or x.get("signe") or 0),
                         mid_entree=float(x.get("mid_entree") or x.get("mid") or 0.0),
                         delta_mid_futur=float(x.get("delta_mid_futur") or 0.0),
                         edge_bps_prevu=float(x.get("edge_bps_prevu") or 0.0),
                         liquidite=float(x.get("liquidite", 1.0)),
                         horizon_ms=int(x.get("horizon_ms", 1_000)))


def _net_segment(signaux: Sequence[Any], *, config: dict[str, Any]) -> dict[str, Any]:
    net = 0.0
    notional = 0.0
    fills = 0
    missed = 0
    nets_episodes: list[float] = []
    contrib: dict[str, float] = {}
    ledger: list[dict[str, Any]] = []
    for x in signaux:
        r = simuler_episode(_as_signal(x), config=config)
        ledger.extend(r["ledger"])
        if r["statut"] == "FILLED":
            fills += 1
            net += r["pnl_usd"]
            notional += r["notional"]
            nets_episodes.append(r["pnl_usd"])
            contrib[r["coin"]] = contrib.get(r["coin"], 0.0) + r["pnl_usd"]
        elif r["statut"] == "MISSED_FILL":
            missed += 1
    return {"net": round(net, 8), "notional": round(notional, 8), "fills": fills, "missed": missed,
            "nets_episodes": nets_episodes, "contributions": contrib, "ledger": ledger}


def rejouer_lead_lag(signaux: list[Any], *, config: dict[str, Any] | None = None,
                     fractions: tuple[float, ...] = (0.6, 0.2, 0.2),
                     min_episodes: int = 5) -> dict[str, Any]:
    """Rejoue la stratégie Lead-Lag paper sur IS/OOS/FORWARD (épisodes indivisibles) + PLACEBO (signe
    inversé → l'edge doit disparaître). Rend {segments, metriques, verdict, placebo_net, ledger}."""
    config = {"notional": 100.0, "fee_bps": 2.5, "min_fill_ratio": 0.5, **(config or {})}
    evs = [{"ts_ms": _as_signal(s).ts_ms, "coin": _as_signal(s).coin,
            "signe": _as_signal(s).signe_leader, "_sig": s} for s in signaux]
    segs = separer_par_episodes(evs, fractions=fractions)
    res_seg = {lab: _net_segment([e["_sig"] for e in segs[lab]], config=config)
               for lab in ("IS", "OOS", "FORWARD")}
    is_ = res_seg["IS"]
    # placebo : inverser le signe leader -> l'alignement se retourne, l'edge réel doit s'annuler/inverser.
    placebo_sigs = []
    for s in [e["_sig"] for e in segs["IS"]]:
        sg = _as_signal(s)
        placebo_sigs.append(SignalLeadLag(sg.ts_ms, sg.coin, -sg.signe_leader, sg.mid_entree,
                                          sg.delta_mid_futur, sg.edge_bps_prevu, sg.liquidite, sg.horizon_ms))
    placebo = _net_segment(placebo_sigs, config=config)
    equity0 = float(config.get("equity", 1000.0))
    courbe = [equity0]
    for p in is_["nets_episodes"]:
        courbe.append(courbe[-1] + p)
    capacite = round(is_["notional"], 4) if is_["fills"] > 0 else M.UNMEASURABLE
    metriques = M.metriques_candidat(
        segments={"IS": {"net": is_["net"]}, "OOS": {"net": res_seg["OOS"]["net"]},
                  "FORWARD": {"net": res_seg["FORWARD"]["net"]},
                  # adverse = pire de OOS/FORWARD (un edge Lead-Lag doit survivre hors-échantillon ET forward).
                  "ADVERSE_P95": {"net": min(res_seg["OOS"]["net"], res_seg["FORWARD"]["net"])},
                  "ADVERSE_P99": {"net": min(res_seg["OOS"]["net"], res_seg["FORWARD"]["net"])}},
        nets_episodes=is_["nets_episodes"], courbe_equity=courbe, notional_traite=is_["notional"],
        equity_finale=courbe[-1], fees=0.0, contributions_coin=is_["contributions"],
        capacite=capacite, reconcilie=True, placebo_net=placebo["net"])
    verdict = M.verdict_promotion(metriques, min_episodes=min_episodes)
    return {"segments": {lab: {"net": res_seg[lab]["net"], "fills": res_seg[lab]["fills"],
                               "missed": res_seg[lab]["missed"]} for lab in ("IS", "OOS", "FORWARD")},
            "metriques": metriques, "verdict": verdict, "placebo_net": placebo["net"],
            "ledger_is": is_["ledger"], "real_execution": False}


def signaux_depuis_events(events: list[dict[str, Any]], *, min_historique: int = 5,
                          horizon_ms: int = 1_000, liquidite_defaut: float = 1.0) -> list[SignalLeadLag]:
    """Construit des SignalLeadLag depuis le flux d'événements du lab. L'edge PRÉVU est CAUSAL : moyenne
    (en bps) des alignements PASSÉS du même coin (jamais le move futur). Historique insuffisant → edge
    prévu 0 → NO_TRADE (conservateur). Le Δmid futur (mid suivant − mid) sert au PnL, pas à décider."""
    par_coin: dict[str, list] = {}
    for e in events:
        mid = e.get("mid", e.get("px"))
        if isinstance(mid, (int, float)) and e.get("signe"):
            par_coin.setdefault(str(e.get("coin")), []).append(
                (e.get("ts_ms") or 0, int(e.get("signe")), float(mid), e.get("liquidite")))
    signaux: list[SignalLeadLag] = []
    for coin, serie in par_coin.items():
        serie.sort(key=lambda t: t[0])
        alignements_passes: list[float] = []
        for i in range(len(serie) - 1):
            ts, signe, mid, liq = serie[i]
            delta = serie[i + 1][2] - mid
            edge_prevu = (sum(alignements_passes) / len(alignements_passes)
                          if len(alignements_passes) >= min_historique else 0.0)
            signaux.append(SignalLeadLag(
                ts_ms=ts, coin=coin, signe_leader=signe, mid_entree=mid, delta_mid_futur=delta,
                edge_bps_prevu=round(edge_prevu, 6),
                liquidite=float(liq) if isinstance(liq, (int, float)) else liquidite_defaut,
                horizon_ms=horizon_ms))
            alignements_passes.append(signe * _bps(delta, mid))       # le point courant devient passé
    signaux.sort(key=lambda s: s.ts_ms)
    return signaux


__all__ = ["SignalLeadLag", "cout_total_bps", "simuler_episode", "rejouer_lead_lag",
           "signaux_depuis_events"]
