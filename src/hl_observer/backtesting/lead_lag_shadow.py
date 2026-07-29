"""LEAD-LAG SHADOW — Binance mène, HL suit ? Mesure NETTE, méthodo gelée (23/07, chantier ARB).

Corrections méthodo de Flo, AVANT la collecte :
  1. HL n'émet le BBO que quand il change sur un bloc -> on MESURE d'abord la distribution réelle des
     intervalles entre messages (`distribution_intervalles`) et on ne GARDE un horizon que si la
     donnée permet de l'observer (`horizons_observables` : un horizon < ~2× l'intervalle médian HL
     est illusoire, on le jette).
  2. Le CHOC se détecte sur les TRADES Binance (aggTrade), pas sur le mid BBO ; l'ENTRÉE se simule au
     bid/ask HL réellement dispo (demi-spread réel), avec la profondeur au top ; horloge MONOTONE.
  3. Coins, horizons, seuils, critère de réussite GELÉS avant le live-forward (`geler_config`) — on ne
     les réajuste pas après avoir vu le PnL.
  4. On mesure l'espérance nette, la CAPACITÉ, le DRAWDOWN et la STABILITÉ PAR PÉRIODE — pas le winrate.

Coins de CONTRÔLE gardés : si le contrôle gagne autant, c'est un artefact d'horloge, pas un edge.
PAPER/shadow only : mesurer n'est pas trader.
"""
from __future__ import annotations

import bisect
import hashlib
import json
import math
import statistics as st
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hl_observer.backtesting.anti_overfit_gate import evaluer as evaluer_dsr
from hl_observer.backtesting.anti_overfit_gate import sharpe
from hl_observer.backtesting.lead_lag_evidence import (
    REQUIRED_CRITERIA,
    SCHEMA_VERSION,
    SUPPORTED_HORIZONS_MS,
)
from hl_observer.backtesting.quant_methods import block_bootstrap
from hl_observer.backtesting.robustesse_selection import pbo_cscv

TAPE = Path("runtime") / "data" / "bbo_tape.jsonl"
CONFIG_GELE = Path("runtime") / "data" / "lead_lag_config_gele.json"
GLOBAL_TRIAL_LEDGER = Path("runtime") / "research_lab" / "ledgers" / "global_trials.jsonl"
SEUIL_CHOC_BPS = 8.0
FRAIS_SLIPPAGE_BPS = 6.0
HORIZONS_MS = (50.0, 100.0, 250.0, 500.0, 1000.0)
MIN_CHOCS = 30
N_PERIODES = 4                     # pour juger la stabilité dans le temps


def charger_tape(root: str | Path) -> dict[str, dict[str, list]]:
    """{coin: {'HL':[(ns,mid,bid,ask)], 'BIN':[(ns,mid)], 'TRADE':[(ns,px,dir)]}} trié."""
    from collections import defaultdict
    p = Path(root) / TAPE
    if not p.exists():
        return {}
    par: dict[str, dict[str, list]] = defaultdict(lambda: {"HL": [], "BIN": [], "TRADE": []})
    for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            d = json.loads(line)
            coin = str(d["coin"]).upper()
            r = int(d["recu_ns"])
        except (KeyError, TypeError, ValueError):
            continue
        v = d.get("venue")
        if v == "HL":
            m = _flt(d.get("mid"))
            if m:
                par[coin]["HL"].append((r, m, _flt(d.get("bid")) or m, _flt(d.get("ask")) or m))
        elif v == "BIN":
            m = _flt(d.get("mid"))
            if m:
                par[coin]["BIN"].append((r, m))
        elif v == "BIN_TRADE":
            px = _flt(d.get("px"))
            if px:
                par[coin]["TRADE"].append((r, px, 1.0 if d.get("side") == "BUY" else -1.0))
    for c in par:
        for k in par[c]:
            par[c][k].sort()
    return dict(par)


def _flt(x):
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def distribution_intervalles(evenements: list) -> dict[str, float]:
    """Percentiles (ms) des intervalles entre messages — DIT si un horizon est observable."""
    ns = [e[0] for e in evenements]
    if len(ns) < 5:
        return {"n": len(ns), "p50_ms": None, "p90_ms": None}
    d = sorted((ns[i] - ns[i - 1]) / 1e6 for i in range(1, len(ns)))
    return {"n": len(ns), "p50_ms": round(d[len(d) // 2], 2),
            "p90_ms": round(d[int(len(d) * 0.9)], 2), "p99_ms": round(d[int(len(d) * 0.99)], 2)}


def horizons_observables(dist_hl: dict, horizons) -> list[float]:
    """On ne garde un horizon que s'il est >= 2× l'intervalle médian HL : sinon la 'réaction' à cet
    horizon n'est PAS observable (HL n'a pas encore réémis). C'est le garde-fou n°1 de Flo."""
    p50 = dist_hl.get("p50_ms")
    if not p50:
        return []
    return [h for h in horizons if h >= 2.0 * p50]


FENETRE_GROUPE_MS = 100.0          # deux chocs à moins de ça = le MÊME mouvement -> groupés (1 seul)


def detecter_chocs(trades: list, *, seuil_bps: float,
                   fenetre_groupe_ms: float = FENETRE_GROUPE_MS) -> list[tuple[int, float]]:
    """Chocs exécutables depuis les TRADES Binance : un saut de prix >= seuil entre trades consécutifs.
    Les chocs qui SE CHEVAUCHENT (< fenetre_groupe_ms) sont GROUPÉS en un seul (sinon on compte 5 fois
    le même mouvement et on gonfle l'échantillon). Retour [(recu_ns, direction)]."""
    out = []
    dernier_ns = -1e30
    for i in range(1, len(trades)):
        if trades[i - 1][1] <= 0:
            continue
        mv = (trades[i][1] - trades[i - 1][1]) / trades[i - 1][1] * 1e4
        if abs(mv) < seuil_bps:
            continue
        t = trades[i][0]
        if (t - dernier_ns) / 1e6 < fenetre_groupe_ms:        # chevauche le choc précédent -> groupé
            continue
        out.append((t, 1.0 if mv > 0 else -1.0))
        dernier_ns = t
    return out


def _hl_a(hl: list, t_ns: int) -> tuple | None:
    i = bisect.bisect_right([e[0] for e in hl], t_ns) - 1
    return hl[i] if i >= 0 else None


def net_par_horizon(hl: list, chocs: list, *, frais_slippage_bps: float,
                    horizons_ms) -> dict[float, list[tuple[float, float]]]:
    """Pour chaque choc, (net_bps, capacité_usd) forward HL par horizon. ENTRÉE au côté cher, SORTIE au
    côté défavorable (bid/ask HL RÉELS des deux côtés — le spread est payé aller ET retour, pas modélisé
    par un forfait). Cœur PUR (testable)."""
    out: dict[float, list] = {h: [] for h in horizons_ms}
    for t0, direction in chocs:
        e0 = _hl_a(hl, t0)
        if e0 is None:
            continue
        entree = e0[3] if direction > 0 else e0[2]             # long -> on paie l'ASK ; short -> le BID
        if entree <= 0:
            continue
        for h in horizons_ms:
            eh = _hl_a(hl, t0 + int(h * 1e6))
            if eh is None or eh[0] <= e0[0]:
                continue
            sortie = eh[2] if direction > 0 else eh[3]         # long -> on sort au BID ; short -> à l'ASK
            net = (sortie - entree) / entree * 1e4 * direction - frais_slippage_bps
            out[h].append((net, e0[2]))                        # capacité proxy = prix (taille au top ailleurs)
    return out


def _metriques(nets: list[float], *, n_periodes: int) -> dict[str, Any]:
    """Espérance, drawdown du cumul, et stabilité PAR PÉRIODE (pas le winrate)."""
    esper = st.mean(nets)
    cum, pic, dd = 0.0, 0.0, 0.0
    for x in nets:
        cum += x
        pic = max(pic, cum)
        dd = min(dd, cum - pic)
    taille = max(1, len(nets) // n_periodes)
    periodes = [nets[i:i + taille] for i in range(0, len(nets), taille)]
    moys = [st.mean(p) for p in periodes if p]
    bootstrap_totals = block_bootstrap(
        nets,
        block=max(1, int(math.sqrt(len(nets)))),
        n=500,
        seed=20260729,
    )
    bootstrap_means = sorted(total / len(nets) for total in bootstrap_totals)
    lower_index = max(0, int(len(bootstrap_means) * 0.025) - 1)
    upper_index = min(len(bootstrap_means) - 1, int(len(bootstrap_means) * 0.975))
    bootstrap_ci = (
        [round(bootstrap_means[lower_index], 3), round(bootstrap_means[upper_index], 3)]
        if bootstrap_means
        else [None, None]
    )
    return {"esperance_nette_bps": round(esper, 3), "n": len(nets),
            "drawdown_cumule_bps": round(dd, 2),
            "periodes_positives": (
                f"{sum(1 for value in moys if value > 0)}/{len(moys)}"
            ),
            "moyennes_par_periode_bps": [round(value, 3) for value in moys],
            "bootstrap_mean_ci95_bps": bootstrap_ci,
            "stable": bool(moys) and all(m > 0 for m in moys)}


def backtest(root: str | Path = ".", *, seuil_choc_bps: float = SEUIL_CHOC_BPS,
             frais_slippage_bps: float = FRAIS_SLIPPAGE_BPS, horizons_ms=HORIZONS_MS,
             coins_controle: tuple = (), min_chocs: int = MIN_CHOCS) -> dict[str, Any]:
    """Verdict lead-lag NET par horizon (gaté par l'observable), par coin, test vs contrôle, avec
    espérance/capacité/drawdown/stabilité. NEED_MORE_DATA tant que trop peu de chocs."""
    tape = charger_tape(root)
    if not tape:
        return {"strategie": "lead_lag_shadow", "statut": "NEED_MORE_DATA", "detail": "tape vide"}
    controle = {c.upper() for c in coins_controle}
    # 1) cadence HL PAR COIN (jamais poolée : l'interleaving de N coins donne un p50 illusoire ~0 ms
    #    et ferait croire que 50/100 ms sont observables alors qu'HL n'emet ~qu'aux 100 ms PAR coin).
    p50s = [d["p50_ms"] for ev in tape.values() if len(ev["HL"]) >= 5
            and (d := distribution_intervalles(ev["HL"]))["p50_ms"]]
    med_p50 = st.median(p50s) if p50s else None
    dist = {"p50_ms_par_coin_median": round(med_p50, 2) if med_p50 else None, "n_coins_mesures": len(p50s)}
    horizons = [h for h in horizons_ms if med_p50 and h >= 2.0 * med_p50]
    if not horizons:
        return {"strategie": "lead_lag_shadow", "statut": "NEED_MORE_DATA",
                "intervalles_hl": dist, "detail": "aucun horizon observable (HL trop lent / peu de data)"}
    # 2) chocs sur trades -> net par horizon, séparé test/contrôle
    import random
    test: dict[float, list] = {h: [] for h in horizons}
    ctrl: dict[float, list] = {h: [] for h in horizons}
    placebo: dict[float, list] = {h: [] for h in horizons}     # directions MÉLANGÉES -> doit donner ~0
    cap: list[float] = []
    test_event_times: list[int] = []
    for coin, ev in tape.items():
        chocs = detecter_chocs(ev["TRADE"], seuil_bps=seuil_choc_bps)
        if not chocs or len(ev["HL"]) < 3:
            continue
        nets = net_par_horizon(ev["HL"], chocs, frais_slippage_bps=frais_slippage_bps, horizons_ms=horizons)
        cible = ctrl if coin in controle else test
        for h in horizons:
            cible[h].extend(x[0] for x in nets[h])
        if coin not in controle:
            test_event_times.extend(t0 for t0, _direction in chocs)
            for h in horizons:
                cap.extend(x[1] for x in nets[h])
            rng = random.Random(20260723)                      # placebo REPRODUCTIBLE : mêmes t0, sens aléatoire
            faux = [(t0, 1.0 if rng.random() > 0.5 else -1.0) for t0, _ in chocs]
            netpl = net_par_horizon(ev["HL"], faux, frais_slippage_bps=frais_slippage_bps, horizons_ms=horizons)
            for h in horizons:
                placebo[h].extend(x[0] for x in netpl[h])
    n_test = max((len(v) for v in test.values()), default=0)
    if n_test < min_chocs:
        return {"strategie": "lead_lag_shadow", "statut": "NEED_MORE_DATA", "chocs_test": n_test,
                "cible": min_chocs, "intervalles_hl": dist, "horizons_observables": horizons}
    par_h = {h: _metriques(v, n_periodes=N_PERIODES) for h, v in test.items() if v}
    ctrl_h = {h: round(st.mean(v), 3) for h, v in ctrl.items() if v}
    plac_h = {h: round(st.mean(v), 3) for h, v in placebo.items() if v}
    trial_sharpes = [sharpe(values) for values in test.values() if len(values) >= 2]
    dsr_h = {
        h: evaluer_dsr(
            values,
            n_essais=max(1, len(horizons_ms)),
            trial_sharpes=trial_sharpes,
        ).as_dict()
        for h, values in test.items()
        if values
    }
    pbo_rows = [
        metrics["moyennes_par_periode_bps"]
        for metrics in par_h.values()
        if len(metrics.get("moyennes_par_periode_bps") or ()) >= 4
    ]
    pbo = pbo_cscv(pbo_rows) if len(pbo_rows) >= 2 else pbo_cscv([])
    event_frequency = None
    if len(test_event_times) >= 2:
        duration_days = (max(test_event_times) - min(test_event_times)) / 1e9 / 86400.0
        if duration_days > 0:
            event_frequency = round(len(test_event_times) / duration_days, 6)
    # KEEP seulement si : espérance>0, STABLE par période, ET bat le PLACEBO (sinon = artefact d'horloge)
    gagnants = {h: r for h, r in par_h.items()
                if r["esperance_nette_bps"] > 0 and r["stable"]
                and r["esperance_nette_bps"] > plac_h.get(h, 0.0)}
    return {"strategie": "lead_lag_shadow",
            "statut": "PROMETTEUR" if gagnants else "PAS_D_EDGE",
            "intervalles_hl": dist, "horizons_observables": horizons,
            "capacite_mediane_usd": round(st.median(cap), 2) if cap else None,
            "net_par_horizon": par_h, "controle_par_horizon": ctrl_h, "placebo_par_horizon": plac_h,
            "dsr_par_horizon": dsr_h,
            "pbo": pbo,
            "frequence_evenements_par_jour": event_frequency,
            "information_coefficient": {
                "value": None,
                "status": "UNMEASURABLE_WITH_DIRECTION_ONLY_SHOCKS",
            },
            "regimes": {
                "period_count": N_PERIODES,
                "stable_horizons_ms": [h for h, row in par_h.items() if row.get("stable")],
            },
            "avertissement": "Choc sur trades Binance ; entrée demi-spread HL réel + frais/slippage ; "
                             "horizons GATÉS par l'observable ; stabilité par période. Contrôle > 0 = "
                             "artefact d'horloge. Sub-seconde souvent gagnée par des racers co-localisés."}


def _legacy_geler_config(root: str | Path = ".", *, coins: list[str], coins_controle: list[str],
                         horizons_ms=HORIZONS_MS, seuil_choc_bps: float = SEUIL_CHOC_BPS,
                         frais_slippage_bps: float = FRAIS_SLIPPAGE_BPS) -> dict[str, Any]:
    """GÈLE coins/horizons/seuils/critère AVANT le live-forward. On lira CE fichier, jamais des seuils
    réajustés après avoir vu le PnL (anti-cherry-picking)."""
    import time
    cfg = {"gele_ts": time.time(), "coins": [c.upper() for c in coins],
           "coins_controle": [c.upper() for c in coins_controle], "horizons_ms": list(horizons_ms),
           "seuil_choc_bps": seuil_choc_bps, "frais_slippage_bps": frais_slippage_bps,
           "critere_reussite": "esperance_nette_bps > 0 ET stable sur toutes les périodes ET contrôle <= 0",
           "min_chocs": MIN_CHOCS}
    p = Path(root) / CONFIG_GELE
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=1), encoding="utf-8")
    import os
    os.replace(tmp, p)
    return cfg


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    if path.exists():
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    else:
        digest.update(b"<missing>")
    return f"sha256:{digest.hexdigest()}"


def _horizon_value(mapping: Any, horizon: float, default: Any = None) -> Any:
    if not isinstance(mapping, dict):
        return default
    for key in (horizon, str(horizon), str(int(horizon))):
        if key in mapping:
            return mapping[key]
    return default


def _register_clock_boundary_trials(
    root: Path,
    *,
    dataset_hash: str,
    pipeline_hash: str,
    requested_horizons: list[float],
) -> dict[str, Any]:
    """Register every tested clock boundary once in the global research ledger."""

    ledger = root / GLOBAL_TRIAL_LEDGER
    ledger.parent.mkdir(parents=True, exist_ok=True)
    known_ids: set[str] = set()
    valid_rows = 0
    if ledger.exists():
        for line in ledger.read_text(encoding="utf-8", errors="ignore").splitlines():
            try:
                row = json.loads(line)
            except (TypeError, ValueError):
                continue
            if isinstance(row, dict):
                valid_rows += 1
                if row.get("trial_id"):
                    known_ids.add(str(row["trial_id"]))

    added = 0
    now = datetime.now(timezone.utc).isoformat()
    with ledger.open("a", encoding="utf-8") as handle:
        for horizon in requested_horizons:
            identity = "|".join(
                (dataset_hash, pipeline_hash, "lead_lag_shadow", f"{horizon:g}ms")
            )
            trial_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
            if trial_id in known_ids:
                continue
            row = {
                "trial_id": trial_id,
                "strategy": "lead_lag_shadow",
                "dimension": "clock_boundary_ms",
                "value": horizon,
                "dataset_hash": dataset_hash,
                "pipeline_hash": pipeline_hash,
                "registered_at": now,
                "real_execution": False,
            }
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
            known_ids.add(trial_id)
            added += 1
    return {
        "count": valid_rows + added,
        "added": added,
        "ledger": str(ledger),
    }


def geler_config(
    root: str | Path = ".",
    *,
    coins: list[str],
    coins_controle: list[str],
    horizons_ms=HORIZONS_MS,
    seuil_choc_bps: float = SEUIL_CHOC_BPS,
    frais_slippage_bps: float = FRAIS_SLIPPAGE_BPS,
    minimum_events: int = MIN_CHOCS,
    evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Freeze a complete, versioned and deny-by-default lead-lag evidence artefact."""

    root_path = Path(root)
    requested = [float(value) for value in horizons_ms]
    unsupported = [value for value in requested if value not in SUPPORTED_HORIZONS_MS]
    if unsupported:
        raise ValueError(f"unsupported lead-lag horizons: {unsupported}")

    dataset_path = root_path / TAPE
    pipeline_path = Path(__file__)
    dataset_hash = _sha256_file(dataset_path)
    pipeline_hash = _sha256_file(pipeline_path)
    global_trials = _register_clock_boundary_trials(
        root_path,
        dataset_hash=dataset_hash,
        pipeline_hash=pipeline_hash,
        requested_horizons=requested,
    )
    result = evidence or backtest(
        root_path,
        seuil_choc_bps=seuil_choc_bps,
        frais_slippage_bps=frais_slippage_bps,
        horizons_ms=requested,
        coins_controle=tuple(coins_controle),
        min_chocs=minimum_events,
    )
    observable = [
        float(value)
        for value in result.get("horizons_observables", ())
        if float(value) in requested
    ]
    net_rows = result.get("net_par_horizon") or {}
    controls = result.get("controle_par_horizon") or {}
    placebos = result.get("placebo_par_horizon") or {}
    dsr_rows = result.get("dsr_par_horizon") or {}

    edges: dict[str, float] = {}
    samples: dict[str, int] = {}
    stability: dict[str, bool] = {}
    bootstrap: dict[str, list[float | None]] = {}
    placebo_edges: dict[str, float | None] = {}
    control_edges: dict[str, float | None] = {}
    dsr: dict[str, dict[str, Any]] = {}
    for horizon in observable:
        key = str(int(horizon) if horizon.is_integer() else horizon)
        row = _horizon_value(net_rows, horizon, {}) or {}
        edges[key] = float(row.get("esperance_nette_bps") or 0.0)
        samples[key] = int(row.get("n") or 0)
        stability[key] = row.get("stable") is True
        bootstrap[key] = list(row.get("bootstrap_mean_ci95_bps") or [None, None])
        placebo = _horizon_value(placebos, horizon)
        control = _horizon_value(controls, horizon)
        placebo_edges[key] = float(placebo) if placebo is not None else None
        control_edges[key] = float(control) if control is not None else None
        dsr[key] = dict(_horizon_value(dsr_rows, horizon, {}) or {})

    pbo = dict(result.get("pbo") or {})
    criteria = {
        "minimum_sample": bool(observable)
        and all(samples.get(str(int(h)), 0) >= minimum_events for h in observable),
        "observable_horizon": bool(observable),
        "net_positive": bool(observable)
        and all(edges.get(str(int(h)), 0.0) > 0 for h in observable),
        "period_stability": bool(observable)
        and all(stability.get(str(int(h))) is True for h in observable),
        "placebo_beaten": bool(observable)
        and all(
            placebo_edges.get(str(int(h))) is not None
            and edges.get(str(int(h)), 0.0) > float(placebo_edges[str(int(h))])
            for h in observable
        ),
        "controls_non_winning": bool(observable)
        and all(
            control_edges.get(str(int(h))) is not None
            and float(control_edges[str(int(h))]) <= 0
            for h in observable
        ),
        "costs_executable": math.isfinite(float(frais_slippage_bps))
        and float(frais_slippage_bps) >= 0,
        "bootstrap_positive": bool(observable)
        and all(
            len(bootstrap.get(str(int(h)), ())) == 2
            and bootstrap[str(int(h))][0] is not None
            and float(bootstrap[str(int(h))][0]) > 0
            for h in observable
        ),
        "pbo_acceptable": pbo.get("pbo") is not None and float(pbo["pbo"]) <= 0.5,
        "dsr_acceptable": bool(observable)
        and all(dsr.get(str(int(h)), {}).get("survit") is True for h in observable),
    }
    promotion_status = (
        "PROMOTED"
        if all(criteria.get(name) is True for name in REQUIRED_CRITERIA)
        else "REJECTED"
    )
    now = datetime.now(timezone.utc)
    config = {
        "schema_version": SCHEMA_VERSION,
        "strategy": "lead_lag_shadow",
        "promotion_status": promotion_status,
        "dataset_hash": dataset_hash,
        "pipeline_hash": pipeline_hash,
        "freeze_ts": now.isoformat(),
        "freeze_ts_ms": int(now.timestamp() * 1000),
        "coins": sorted({str(coin).upper() for coin in coins if coin}),
        "control_coins": sorted(
            {str(coin).upper() for coin in coins_controle if coin}
        ),
        "requested_horizons_ms": requested,
        "observable_horizons_ms": observable,
        "unobservable_horizons_ms": [
            horizon for horizon in requested if horizon not in observable
        ],
        "minimum_events": int(minimum_events),
        "seuil_choc_bps": float(seuil_choc_bps),
        "edge_net_par_horizon_bps": edges,
        "sample_n_by_horizon": samples,
        "period_stability_by_horizon": stability,
        "bootstrap_mean_ci95_bps": bootstrap,
        "placebo_edge_by_horizon_bps": placebo_edges,
        "control_edge_by_horizon_bps": control_edges,
        "dsr_by_horizon": dsr,
        "pbo": pbo,
        "costs": {
            "round_trip_bps": float(frais_slippage_bps),
            "model": "real_hl_bid_ask_plus_configured_fees_and_slippage",
            "executable": criteria["costs_executable"],
        },
        "frequency": {
            "events_per_day": result.get("frequence_evenements_par_jour"),
        },
        "information_coefficient": result.get("information_coefficient")
        or {"value": None, "status": "UNMEASURABLE"},
        "regimes": result.get("regimes") or {},
        "criteria": criteria,
        "global_trials": global_trials,
        "source_status": str(result.get("statut") or "UNKNOWN"),
        "source_detail": result.get("detail"),
        "real_execution": False,
    }
    output = root_path / CONFIG_GELE
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(config, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    import os

    os.replace(temporary, output)
    return config


__all__ = ["SEUIL_CHOC_BPS", "FRAIS_SLIPPAGE_BPS", "HORIZONS_MS", "charger_tape",
           "distribution_intervalles", "horizons_observables", "detecter_chocs",
           "net_par_horizon", "backtest", "geler_config", "GLOBAL_TRIAL_LEDGER"]
