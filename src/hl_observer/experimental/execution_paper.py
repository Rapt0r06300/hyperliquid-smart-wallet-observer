"""Exécution paper pure et testable, sans réseau ni ordre réel.

Pour une dislocation deux-jambes le realized est calculé au bid/ask exécutable
de chaque venue et paie explicitement les coûts d'entrée ET de sortie. Les
anciens callers qui fournissent seulement ``fee_bps``/``slippage_bps`` sont
interprétés conservativement comme un coût one-way appliqué aux deux côtés du
round-trip.
"""
from __future__ import annotations

from hl_observer.experimental import invariants as INV


def _round_trip_leg_costs(jambe: dict) -> dict[str, float]:
    """Normalise les coûts d'une jambe sans double comptage implicite.

    Nouveau contrat : ``entry_fee_bps``/``exit_fee_bps`` et
    ``entry_slippage_bps``/``exit_slippage_bps`` sont autoritaires. Pour les
    positions historiques qui ne portent qu'un coût one-way ``fee_bps`` ou
    ``slippage_bps``, on l'applique à l'entrée et à la sortie : une position
    ouverte puis fermée paie bien deux exécutions.
    """
    legacy_fee = float(jambe.get("fee_bps") or 0.0)
    legacy_slip = float(jambe.get("slippage_bps") or 0.0)
    entry_fee = float(jambe.get("entry_fee_bps")) if jambe.get("entry_fee_bps") is not None else legacy_fee
    exit_fee = float(jambe.get("exit_fee_bps")) if jambe.get("exit_fee_bps") is not None else legacy_fee
    entry_slip = (
        float(jambe.get("entry_slippage_bps"))
        if jambe.get("entry_slippage_bps") is not None
        else legacy_slip
    )
    exit_slip = (
        float(jambe.get("exit_slippage_bps"))
        if jambe.get("exit_slippage_bps") is not None
        else legacy_slip
    )
    values = (entry_fee, exit_fee, entry_slip, exit_slip)
    if any((not INV.est_fini(v) or v < 0) for v in values):
        raise ValueError("cout de jambe invalide")
    return {
        "entry_fee_bps": entry_fee,
        "exit_fee_bps": exit_fee,
        "entry_slippage_bps": entry_slip,
        "exit_slippage_bps": exit_slip,
        "round_trip_cost_bps": entry_fee + exit_fee + entry_slip + exit_slip,
    }


def pnl_jambe(jambe: dict) -> float:
    """PnL net d'une jambe, coûts d'entrée + sortie compris exactement une fois."""
    for k in ("side", "entry_px", "exit_px", "size_usd"):
        if not INV.est_fini(jambe.get(k)):
            raise ValueError("jambe invalide: %s" % k)
    e, x, s = float(jambe["entry_px"]), float(jambe["exit_px"]), float(jambe["size_usd"])
    if e <= 0 or x <= 0 or s <= 0:
        raise ValueError("prix/taille non positifs")
    brut = (x - e) / e if int(jambe["side"]) > 0 else (e - x) / e
    costs = _round_trip_leg_costs(jambe)
    return round((brut - costs["round_trip_cost_bps"] / 1e4) * s, 6)


def pnl_deux_jambes(jambes: list[dict]) -> dict:
    """PnL net total = somme exacte des deux jambes réconciliées."""
    detail = []
    total = 0.0
    total_cost_usd = 0.0
    for j in jambes:
        costs = _round_trip_leg_costs(j)
        p = pnl_jambe(j)
        size = float(j["size_usd"])
        cost_usd = costs["round_trip_cost_bps"] / 1e4 * size
        total += p
        total_cost_usd += cost_usd
        detail.append(
            {
                "venue": j.get("venue"),
                "side": int(j["side"]),
                "entry_px": float(j["entry_px"]),
                "exit_px": float(j["exit_px"]),
                "size_usd": size,
                # Champs legacy conservés pour les lecteurs existants.
                "fee_bps": float(j.get("fee_bps") or 0.0),
                "slippage_bps": float(j.get("slippage_bps") or 0.0),
                **costs,
                "round_trip_cost_usd": round(cost_usd, 6),
                "latency_ms": float(j.get("latency_ms") or 0.0),
                "realized_usd": p,
            }
        )
    return {
        "realized_usd": round(total, 6),
        "round_trip_cost_usd": round(total_cost_usd, 6),
        "n_jambes": len(detail),
        "jambes": detail,
    }


# ─────────────── copy-vault REDUCE proportionnel ───────────────
def snapshot_complet_ok(
    snapshot: dict,
    coin: str,
    *,
    ts_entree_ms: float,
    now_ms: float,
    fraicheur_max_ms: float = 60_000.0,
) -> tuple[bool, str | None]:
    if not snapshot or not snapshot.get("complet"):
        return False, "SNAPSHOT_INCOMPLET"
    ts = snapshot.get("ts_ms")
    if not INV.est_fini(ts):
        return False, "SNAPSHOT_SANS_TS"
    if float(ts) <= float(ts_entree_ms):
        return False, "SNAPSHOT_ANTERIEUR_ENTREE"
    if float(now_ms) - float(ts) > fraicheur_max_ms:
        return False, "SNAPSHOT_PERIME"
    return True, None


def classifier_changement_leader(
    *,
    entry_szi: float,
    current_szi: float,
    last_applied_szi: float,
    tol_frac: float = 0.02,
) -> str:
    if not (
        INV.est_fini(entry_szi)
        and INV.est_fini(current_szi)
        and INV.est_fini(last_applied_szi)
    ) or abs(float(entry_szi)) <= 0:
        return "INVALIDE"
    e, cur, last = float(entry_szi), float(current_szi), float(last_applied_szi)
    if cur != 0 and last != 0 and (cur > 0) != (last > 0):
        return "FLIP_LONG_SHORT" if last > 0 else "FLIP_SHORT_LONG"
    if abs(cur) <= abs(e) * 1e-9:
        return "CLOSE"
    delta = abs(cur) - abs(last)
    seuil = abs(e) * float(tol_frac)
    if delta < -seuil:
        return "REDUCE"
    if delta > seuil:
        return "ADD"
    return "AUCUN"


def reduire_vers_cible(
    pos: dict,
    *,
    entry_leader_szi: float,
    current_leader_szi: float,
    prix_sortie: float,
    cout_sortie_bps: float,
    cout_entree_bps: float = 0.0,
    quasi_zero: float = 0.05,
) -> dict:
    initial = float(pos.get("initial_paper_notional_usd") or pos.get("notional_usd") or 0.0)
    current = float(pos.get("notional_usd") or 0.0)
    if not (
        INV.est_fini(entry_leader_szi) and INV.est_fini(current_leader_szi)
    ) or abs(float(entry_leader_szi)) <= 0:
        return {"action": "AUCUNE", "motif": "TAILLE_LEADER_INVALIDE"}
    ratio = abs(float(current_leader_szi)) / abs(float(entry_leader_szi))
    if ratio <= quasi_zero:
        ferme, residuel, action = current, 0.0, "CLOSE_INTEGRAL"
    else:
        cible = min(current, initial * ratio)
        ferme = round(current - cible, 6)
        if ferme <= 1e-9:
            return {
                "action": "AUCUNE",
                "ratio_restant": round(ratio, 4),
                "notional_ferme_usd": 0.0,
                "notional_residuel_usd": round(current, 6),
            }
        residuel, action = round(current - ferme, 6), "REDUCE"
    sens = int(pos["sens"])
    entree = float(pos["prix_entree"])
    brut = (
        (float(prix_sortie) - entree) / entree
        if sens > 0
        else (entree - float(prix_sortie)) / entree
    )
    entry_cost = float(cout_entree_bps) / 1e4 * ferme
    exit_cost = float(cout_sortie_bps) / 1e4 * ferme
    realized = round(brut * ferme - entry_cost - exit_cost, 6)
    return {
        "action": action,
        "ratio_restant": round(ratio, 4),
        "notional_ferme_usd": round(ferme, 6),
        "notional_residuel_usd": residuel,
        "realized_usd": realized,
        "entry_cost_allocated_usd": round(entry_cost, 6),
        "exit_cost_usd": round(exit_cost, 6),
        "frais_partie_fermee_usd": round(entry_cost + exit_cost, 6),
    }


# ─────────────── donnée manquante ───────────────
def politique_data_missing(
    pos: dict,
    *,
    now_ms: float,
    grace_ms: float = 120_000.0,
    slippage_stress_bps: float = 25.0,
) -> dict:
    ref = pos.get("ts_derniere_donnee_ms")
    if ref is None:
        ref = pos.get("ts_ouverture_ms")
    if ref is None:
        ref = now_ms
    depuis = float(now_ms) - float(ref)
    if depuis < grace_ms:
        return {"action": "ATTENDRE", "grace_restante_ms": round(grace_ms - depuis, 1)}
    return {
        "action": "SORTIE",
        "raison": "DATA_MISSING_TIMEOUT",
        "mark_conservateur": float(pos.get("prix_entree")),
        "slippage_stress_bps": slippage_stress_bps,
    }


__all__ = [
    "pnl_jambe",
    "pnl_deux_jambes",
    "snapshot_complet_ok",
    "classifier_changement_leader",
    "reduire_vers_cible",
    "politique_data_missing",
]
