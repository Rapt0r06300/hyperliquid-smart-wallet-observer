"""MOTEUR EXPERIMENTAL_PAPER — cœur commun cross-venue, lead-lag, copy-vaults.

Paper/read-only uniquement. Le ledger v2 est isolé du PnL canonique. Les lignes
portent une session explicite et le budget global raisonne en exposition brute :
une dislocation de N USD par jambe consomme 2N de capacité. Chaque épisode a un
position_id unique, distinct de l'identifiant canonique déterministe de la chaîne.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hl_observer.experimental import invariants as INV
from hl_observer.ops.canonical_paper_intent_chain import (
    fill_vers_position_ledger_open,
    intent_canonique,
    intent_vers_ordre_paper,
    ordre_vers_fill_ledger,
)

MODE = "EXPERIMENTAL_PAPER"
VERSION = "v2"
LEDGER_RELPATH = Path("runtime") / "data" / ("experimental_paper_%s_ledger.jsonl" % VERSION)
POSITIONS_RELPATH = Path("runtime") / "data" / ("experimental_paper_%s_positions.json" % VERSION)
STATUS_RELPATH = Path("runtime") / "data" / ("experimental_paper_%s_status.json" % VERSION)
SESSION_POINTER_RELPATH = Path("runtime") / "data" / "sessions" / "COURANTE.json"

BUDGET_TOTAL_USD = 1000.0
AGE_MAX_SIGNAL_MS = 30_000.0
MIN_EDGE_NET_BPS = 12.0
MIN_ROI_ANNUEL_NET_PCT = 15.0
MIN_PNL_ATTENDU_USD = 0.25
LIMITES: dict[str, dict[str, float]] = {
    "cross_venue": {"max_positions": 6, "max_notional_usd": 300.0, "notional_usd": 50.0},
    "lead_lag": {"max_positions": 4, "max_notional_usd": 200.0, "notional_usd": 50.0},
    "copy_vault": {"max_positions": 4, "max_notional_usd": 600.0, "notional_usd": 150.0},
}
MOTEURS = tuple(LIMITES)


@dataclass
class Signal:
    moteur: str
    coin: str
    sens: int
    type_pnl: str
    notional_usd: float
    prix_entree: float
    cout_entree_bps: float
    edge_estime_bps: float
    ts_signal_ms: float
    roi_annuel_pct: float | None = None
    pnl_attendu_usd: float = 0.0
    frais_bps: float = 0.0
    spread_bps: float = 0.0
    slippage_bps: float = 0.0
    latence_ms: float = 0.0
    d_bps_h: float = 0.0
    base_entree_bps: float = 0.0
    hold_h: float = 168.0
    meta: dict[str, Any] = field(default_factory=dict)


def _p(root: str | Path, rel: Path) -> Path:
    return Path(root) / rel


def _session_id(root: str | Path) -> str:
    explicit = str(os.environ.get("HYPERSMART_SESSION_ID") or "").strip()
    if explicit:
        return explicit
    try:
        payload = json.loads(_p(root, SESSION_POINTER_RELPATH).read_text(encoding="utf-8"))
        run_id = str(payload.get("run_id") or "").strip() if isinstance(payload, dict) else ""
        if run_id:
            return run_id
    except (OSError, TypeError, ValueError):
        import logging as _lg
        _lg.getLogger(__name__).debug("session pointer experimental indisponible", exc_info=True)
    return "UNSCOPED"


def _gross_exposure_for_signal(sig: Signal) -> float:
    n = float(sig.notional_usd)
    return n * 2.0 if sig.moteur == "cross_venue" else n


def _gross_exposure_for_position(pos: dict[str, Any]) -> float:
    explicit = pos.get("gross_exposure_usd")
    if INV.est_fini(explicit) and float(explicit) >= 0:
        return float(explicit)
    n = float(pos.get("notional_usd") or 0.0)
    return n * 2.0 if pos.get("moteur") == "cross_venue" else n


def _gross_budget_used(store: dict[str, Any]) -> float:
    return sum(
        _gross_exposure_for_position(p)
        for p in (store.get("ouvertes") or {}).values()
        if isinstance(p, dict)
    )


def charger_store(root: str | Path = ".") -> dict[str, Any]:
    try:
        d = json.loads(_p(root, POSITIONS_RELPATH).read_text(encoding="utf-8"))
        if isinstance(d, dict) and d.get("mode") == MODE and isinstance(d.get("ouvertes"), dict):
            return d
    except (OSError, ValueError):
        import logging as _lg
        _lg.getLogger(__name__).debug("store experimental indisponible", exc_info=True)
    return {"mode": MODE, "ouvertes": {}}


def sauver_store(root: str | Path, store: dict[str, Any]) -> None:
    p = _p(root, POSITIONS_RELPATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _ledger(root: str | Path, row: dict[str, Any]) -> None:
    """Append-only EXP avec identité de session/lane/cohorte obligatoire."""
    p = _p(root, LEDGER_RELPATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {
        **row,
        "mode": MODE,
        "lane": str(row.get("lane") or "EXP"),
        "cohort": str(row.get("cohort") or "EXPERIMENTAL"),
        "session_id": str(row.get("session_id") or _session_id(root)),
        "real_execution": False,
    }
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _cout_usd(bps: float, notional: float) -> float:
    return float(bps) / 1e4 * float(notional)


def _positions_moteur(store: dict, moteur: str) -> list[dict]:
    return [p for p in store["ouvertes"].values() if p.get("moteur") == moteur]


CLOCK_SKEW_TOL_MS = 2_000.0


def admettre(sig: Signal, store: dict, *, now_ms: float, mode: str = "experimental_paper") -> tuple[bool, str | None]:
    if sig.moteur not in LIMITES:
        return False, "MOTEUR_INCONNU"
    ok_num, motif_num = INV.valider_signal(sig)
    if not ok_num:
        return False, motif_num
    if sig.ts_signal_ms and (float(sig.ts_signal_ms) - now_ms) > CLOCK_SKEW_TOL_MS:
        return False, "CLOCK_SKEW_FUTURE_DATA"
    if not (sig.ts_signal_ms and (now_ms - float(sig.ts_signal_ms)) <= AGE_MAX_SIGNAL_MS):
        return False, "SIGNAL_PERIME"
    if not (isinstance(sig.prix_entree, (int, float)) and sig.prix_entree > 0):
        return False, "PRIX_NON_EXECUTABLE"
    if sig.cout_entree_bps is None or float(sig.cout_entree_bps) < 0:
        return False, "COUT_INCONNU"
    if not (float(sig.edge_estime_bps) > 0.0):
        return False, "EDGE_NEGATIF_APRES_COUTS"
    if float(sig.edge_estime_bps) < MIN_EDGE_NET_BPS:
        return False, "MICRO_EDGE"
    if mode == "strict":
        ok_roi, motif_roi = INV.roi_gate(sig.roi_annuel_pct, min_roi=MIN_ROI_ANNUEL_NET_PCT)
        if not ok_roi:
            return False, motif_roi
    if float(sig.pnl_attendu_usd) < MIN_PNL_ATTENDU_USD:
        return False, "PNL_POUR_DES_CENTIMES"
    if sig.sens not in (-1, 1):
        return False, "SENS_INVALIDE"
    lim = LIMITES[sig.moteur]
    ouvertes = _positions_moteur(store, sig.moteur)
    cle = "%s:%s" % (sig.moteur, sig.coin.upper())
    if cle in store["ouvertes"]:
        return False, "DEJA_OUVERT"
    if len(ouvertes) >= int(lim["max_positions"]):
        return False, "LIMITE_POSITIONS_MOTEUR"
    if sum(float(p.get("notional_usd") or 0.0) for p in ouvertes) + float(sig.notional_usd) > lim["max_notional_usd"]:
        return False, "LIMITE_NOTIONAL_MOTEUR"
    gross_incoming = _gross_exposure_for_signal(sig)
    if _gross_budget_used(store) + gross_incoming > BUDGET_TOTAL_USD + 1e-9:
        return False, "BUDGET_GLOBAL_DEPASSE"
    return True, None


def _nouveau_position_id(moteur: str, coin: str, now_ms: float) -> str:
    import uuid
    return "%s:%s:%d:%s" % (moteur, coin.upper(), int(now_ms), uuid.uuid4().hex[:8])


def ouvrir(sig: Signal, store: dict, root: str | Path, *, now_ms: float) -> dict:
    cle = "%s:%s" % (sig.moteur, sig.coin.upper())
    notional0 = float(sig.notional_usd)
    gross0 = _gross_exposure_for_signal(sig)
    cout_entree_usd = round(_cout_usd(sig.cout_entree_bps, notional0), 6)
    strategie_canonique = {
        "cross_venue": "cross_venue_dislocation",
        "lead_lag": "lead_lag",
        "copy_vault": "copy_vault",
    }[sig.moteur]
    intent = intent_canonique(
        strategy=strategie_canonique,
        coin=sig.coin,
        side=int(sig.sens),
        notional_usd=notional0,
        signal_observable_at_ms=int(sig.ts_signal_ms),
        cohort="EXPERIMENTAL",
    )
    ordre = intent_vers_ordre_paper(intent)
    fill = ordre_vers_fill_ledger(ordre, prix=float(sig.prix_entree))
    position_canonique, ledger_open = fill_vers_position_ledger_open(fill, lane="EXP")
    canonical_position_id = str(position_canonique["position_id"])
    episode_position_id = _nouveau_position_id(sig.moteur, sig.coin, now_ms)
    pos = {
        "id": cle,
        "position_id": episode_position_id,
        "canonical_position_id": canonical_position_id,
        "intent_id": intent.intent_id,
        "order_id": ordre["order_id"],
        "fill_id": fill["fill_id"],
        "lane": "EXP",
        "cohort": "EXPERIMENTAL",
        "session_id": _session_id(root),
        "paper_only": True,
        "real_execution": False,
        "moteur": sig.moteur,
        "coin": sig.coin.upper(),
        "sens": int(sig.sens),
        "type_pnl": sig.type_pnl,
        "notional_usd": notional0,
        "per_leg_notional_usd": notional0,
        "gross_exposure_usd": gross0,
        "initial_paper_notional_usd": notional0,
        "prix_entree": float(sig.prix_entree),
        "cout_entree_bps": float(sig.cout_entree_bps),
        "edge_estime_bps": float(sig.edge_estime_bps),
        "ts_ouverture_ms": int(now_ms),
        "ts_signal_ms": float(sig.ts_signal_ms),
        "roi_annuel_pct": sig.roi_annuel_pct,
        "frais_bps": float(sig.frais_bps),
        "spread_bps": float(sig.spread_bps),
        "slippage_bps": float(sig.slippage_bps),
        "latence_ms": float(sig.latence_ms),
        "d_bps_h": float(sig.d_bps_h),
        "base_entree_bps": float(sig.base_entree_bps),
        "hold_h": float(sig.hold_h),
        "meta": dict(sig.meta),
        "cout_entree_usd": cout_entree_usd,
        "entry_cost_remaining_usd": cout_entree_usd,
        "cumulative_realized_usd": 0.0,
        "cumulative_entry_cost_allocated_usd": 0.0,
        "cumulative_exit_cost_usd": 0.0,
        "entry_leader_szi": float((sig.meta or {}).get("szi_apres") or 0.0),
        "last_leader_szi_applied": float((sig.meta or {}).get("szi_apres") or 0.0),
        "last_vault_snapshot_ts": float((sig.meta or {}).get("snapshot_ts_ms") or now_ms),
        "last_vault_snapshot_id": (sig.meta or {}).get("snapshot_id"),
    }
    store["ouvertes"][cle] = pos
    _ledger(root, {
        **ledger_open,
        "position_id": episode_position_id,
        "canonical_position_id": canonical_position_id,
        "strategie": sig.moteur,
        "canonical_strategy": strategie_canonique,
        "intent_id": intent.intent_id,
        "order_id": ordre["order_id"],
        "fill_id": fill["fill_id"],
        "coin": pos["coin"],
        "sens": pos["sens"],
        "notional_usd": pos["notional_usd"],
        "per_leg_notional_usd": pos["per_leg_notional_usd"],
        "gross_exposure_usd": pos["gross_exposure_usd"],
        "prix_entree": pos["prix_entree"],
        "cout_entree_bps": pos["cout_entree_bps"],
        "edge_estime_bps": pos["edge_estime_bps"],
        "roi_annuel_pct": sig.roi_annuel_pct,
        "type_pnl": pos["type_pnl"],
        "ts_ms": int(now_ms),
        "ts_signal_ms": float(sig.ts_signal_ms),
    })
    return pos


def pnl_courant_usd(pos: dict, *, mark: float | None = None, base_courant_bps: float | None = None,
                    now_ms: float | None = None) -> float:
    notional = float(pos.get("notional_usd") or 0.0)
    entree_cout = _cout_usd(pos.get("cout_entree_bps") or 0.0, notional)
    if pos.get("type_pnl") == "funding_carry":
        now = float(now_ms if now_ms is not None else time.time() * 1000)
        ts_ouv = pos.get("ts_ouverture_ms")
        ts_ouv = float(ts_ouv) if ts_ouv is not None else now
        heures = max(0.0, (now - ts_ouv) / 3.6e6)
        funding = float(pos.get("d_bps_h") or 0.0) * heures / 1e4 * notional
        derive = 0.0
        if base_courant_bps is not None:
            derive = -abs(float(base_courant_bps) - float(pos.get("base_entree_bps") or 0.0)) / 1e4 * notional
        return round(funding + derive - entree_cout, 6)
    if pos.get("type_pnl") == "dislocation":
        gap_ent = float((pos.get("meta") or {}).get("gap_entree_bps") or pos.get("base_entree_bps") or 0.0)
        gap_cur = float(base_courant_bps) if base_courant_bps is not None else gap_ent
        return round((gap_ent - gap_cur) / 1e4 * notional - entree_cout, 6)
    if mark is None or not pos.get("prix_entree"):
        return round(-entree_cout, 6)
    var = (float(mark) - float(pos["prix_entree"])) / float(pos["prix_entree"])
    return round(int(pos.get("sens") or 1) * var * notional - entree_cout, 6)


def sortir(pos: dict, store: dict, root: str | Path, *, prix_sortie: float | None,
           cout_sortie_bps: float, raison: str, now_ms: float,
           base_courant_bps: float | None = None) -> dict:
    courante = store.get("ouvertes", {}).get(pos.get("id"))
    if courante is None or courante.get("position_id") != pos.get("position_id"):
        return {"coin": pos.get("coin"), "moteur": pos.get("moteur"), "realized_usd": 0.0,
                "raison": "CLOSE_DUPLICATE_IGNORED", "position_id": pos.get("position_id"), "ignored": True}
    notional_ferme = float(pos.get("notional_usd") or 0.0)
    exit_cost_usd = _cout_usd(cout_sortie_bps, notional_ferme)
    mtm = pnl_courant_usd(pos, mark=prix_sortie, base_courant_bps=base_courant_bps, now_ms=now_ms)
    realized = round(mtm - exit_cost_usd, 6)
    entry_cost_alloc = float(pos.get("entry_cost_remaining_usd") or 0.0)
    store["ouvertes"].pop(pos["id"], None)
    _ledger(root, {"kind": "CLOSE", "position_id": pos.get("position_id"),
                   "canonical_position_id": pos.get("canonical_position_id"), "strategie": pos["moteur"],
                   "coin": pos["coin"], "realized_net_pnl_usdc": realized, "prix_sortie": prix_sortie,
                   "cout_sortie_bps": float(cout_sortie_bps), "raison": raison,
                   "notional_ferme_usd": round(notional_ferme, 6),
                   "gross_exposure_fermee_usd": round(_gross_exposure_for_position(pos), 6),
                   "entry_cost_allocated_usd": round(entry_cost_alloc, 6),
                   "exit_cost_usd": round(exit_cost_usd, 6),
                   "edge_estime_bps": pos.get("edge_estime_bps"), "ts_ms": int(now_ms)})
    return {"coin": pos["coin"], "moteur": pos["moteur"], "realized_usd": realized, "raison": raison,
            "position_id": pos.get("position_id")}


def reduire(pos: dict, store: dict, root: str | Path, *, notional_ferme_usd: float,
            notional_residuel_usd: float, realized_usd: float, prix_sortie: float | None,
            cout_sortie_bps: float, raison: str, now_ms: float, entry_cost_allocated_usd: float = 0.0,
            exit_cost_usd: float = 0.0, leader_szi_applied: float | None = None,
            snapshot_ts: float | None = None, snapshot_id=None) -> dict:
    old_notional = float(pos.get("notional_usd") or 0.0)
    # Calculer l'exposition AVANT de modifier le résidu : les anciennes positions sans champ
    # gross_exposure_usd doivent conserver leur multiplicateur historique (2x cross-venue, 1x directionnel).
    old_gross = _gross_exposure_for_position(pos) if old_notional > 0 else 0.0
    multiplier = (old_gross / old_notional) if old_notional > 0 else 1.0
    pos["notional_usd"] = round(float(notional_residuel_usd), 6)
    pos["gross_exposure_usd"] = round(float(notional_residuel_usd) * multiplier, 6)
    pos["per_leg_notional_usd"] = round(float(notional_residuel_usd), 6)
    pos["entry_cost_remaining_usd"] = round(max(0.0, float(pos.get("entry_cost_remaining_usd") or 0.0)
                                                 - float(entry_cost_allocated_usd)), 6)
    pos["cumulative_realized_usd"] = round(float(pos.get("cumulative_realized_usd") or 0.0) + float(realized_usd), 6)
    pos["cumulative_entry_cost_allocated_usd"] = round(
        float(pos.get("cumulative_entry_cost_allocated_usd") or 0.0) + float(entry_cost_allocated_usd), 6)
    pos["cumulative_exit_cost_usd"] = round(float(pos.get("cumulative_exit_cost_usd") or 0.0) + float(exit_cost_usd), 6)
    if leader_szi_applied is not None:
        pos["last_leader_szi_applied"] = float(leader_szi_applied)
    if snapshot_ts is not None:
        pos["last_vault_snapshot_ts"] = float(snapshot_ts)
    if snapshot_id is not None:
        pos["last_vault_snapshot_id"] = snapshot_id
    _ledger(root, {"kind": "REDUCE", "position_id": pos.get("position_id"),
                   "canonical_position_id": pos.get("canonical_position_id"), "strategie": pos["moteur"],
                   "coin": pos["coin"], "realized_net_pnl_usdc": round(float(realized_usd), 6),
                   "realized_usd": round(float(realized_usd), 6),
                   "notional_ferme_usd": round(float(notional_ferme_usd), 6),
                   "notional_residuel_usd": round(float(notional_residuel_usd), 6),
                   "entry_cost_allocated_usd": round(float(entry_cost_allocated_usd), 6),
                   "exit_cost_usd": round(float(exit_cost_usd), 6),
                   "prix_sortie": prix_sortie, "cout_sortie_bps": float(cout_sortie_bps),
                   "raison": raison, "edge_estime_bps": pos.get("edge_estime_bps"), "ts_ms": int(now_ms)})
    return {"coin": pos["coin"], "moteur": pos["moteur"], "realized_usd": round(float(realized_usd), 6),
            "notional_ferme_usd": round(float(notional_ferme_usd), 6), "raison": raison, "action": "REDUCE",
            "position_id": pos.get("position_id")}


def sortir_deux_jambes(pos: dict, store: dict, root: str | Path, *, jambes: list[dict], raison: str,
                       now_ms: float) -> dict:
    courante = store.get("ouvertes", {}).get(pos.get("id"))
    if courante is None or courante.get("position_id") != pos.get("position_id"):
        return {"coin": pos.get("coin"), "moteur": pos.get("moteur"), "realized_usd": 0.0,
                "raison": "CLOSE_DUPLICATE_IGNORED", "position_id": pos.get("position_id"),
                "ignored": True, "jambes": []}
    from hl_observer.experimental.execution_paper import pnl_deux_jambes
    res = pnl_deux_jambes(jambes)
    realized = round(float(res["realized_usd"]), 6)
    entry_cost_alloc = float(pos.get("entry_cost_remaining_usd") or 0.0)
    gross_closed = _gross_exposure_for_position(pos)
    store["ouvertes"].pop(pos["id"], None)
    _ledger(root, {"kind": "CLOSE", "position_id": pos.get("position_id"),
                   "canonical_position_id": pos.get("canonical_position_id"), "strategie": pos["moteur"],
                   "coin": pos["coin"], "realized_net_pnl_usdc": realized, "raison": raison,
                   "notional_ferme_usd": round(float(pos.get("notional_usd") or 0.0), 6),
                   "gross_exposure_fermee_usd": round(gross_closed, 6),
                   "entry_cost_allocated_usd": round(entry_cost_alloc, 6),
                   "round_trip_cost_usd": res.get("round_trip_cost_usd"),
                   "jambes": res["jambes"], "n_jambes": res["n_jambes"],
                   "edge_estime_bps": pos.get("edge_estime_bps"), "ts_ms": int(now_ms)})
    return {"coin": pos["coin"], "moteur": pos["moteur"], "realized_usd": realized, "raison": raison,
            "position_id": pos.get("position_id"), "jambes": res["jambes"]}


def resume(root: str | Path = ".") -> dict[str, Any]:
    """Résumé séparant strictement PnL de session et PnL lifetime."""
    store = charger_store(root)
    current_session = _session_id(root)
    par_moteur: dict[str, dict[str, float]] = {
        m: {"positions": 0, "realise_usd": 0.0, "realise_session_usd": 0.0, "realise_lifetime_usd": 0.0}
        for m in MOTEURS
    }
    for p in store["ouvertes"].values():
        m = p.get("moteur")
        if m in par_moteur:
            par_moteur[m]["positions"] += 1
    realized_lifetime = 0.0
    realized_session = 0.0
    try:
        for l in _p(root, LEDGER_RELPATH).read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if r.get("kind") not in ("CLOSE", "REDUCE"):
                continue
            v = float(r.get("realized_net_pnl_usdc") or 0.0)
            realized_lifetime += v
            strategy = r.get("strategie")
            if strategy in par_moteur:
                par_moteur[strategy]["realise_lifetime_usd"] += v
            row_session = str(r.get("session_id") or "")
            belongs = row_session == current_session or (current_session == "UNSCOPED" and not row_session)
            if belongs:
                realized_session += v
                if strategy in par_moteur:
                    par_moteur[strategy]["realise_session_usd"] += v
    except OSError:
        import logging as _lg
        _lg.getLogger(__name__).debug("ledger experimental indisponible", exc_info=True)
    for values in par_moteur.values():
        values["realise_usd"] = round(values["realise_session_usd"], 6)
        values["realise_session_usd"] = round(values["realise_session_usd"], 6)
        values["realise_lifetime_usd"] = round(values["realise_lifetime_usd"], 6)
    return {
        "mode": MODE,
        "lane": "EXP",
        "session_id": current_session,
        "positions_ouvertes": len(store["ouvertes"]),
        "realise_total_usd": round(realized_session, 6),
        "realise_session_usd": round(realized_session, 6),
        "realise_lifetime_usd": round(realized_lifetime, 6),
        "par_moteur": par_moteur,
        "gross_exposure_open_usd": round(_gross_budget_used(store), 6),
        "budget_total_usd": BUDGET_TOTAL_USD,
        "real_execution": False,
    }


__all__ = [
    "MODE", "LEDGER_RELPATH", "POSITIONS_RELPATH", "BUDGET_TOTAL_USD", "AGE_MAX_SIGNAL_MS",
    "CLOCK_SKEW_TOL_MS", "LIMITES", "MOTEURS", "Signal", "charger_store", "sauver_store", "admettre",
    "ouvrir", "pnl_courant_usd", "sortir", "reduire", "sortir_deux_jambes", "resume",
]
