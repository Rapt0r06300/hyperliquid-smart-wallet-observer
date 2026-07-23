"""RUNNER EXPERIMENTAL_PAPER — un tick complet : collecte les signaux des 3 moteurs, ADMET (fraîcheur +
exécutable + edge > 0, jamais prouve_oos), OUVRE, puis GÈRE et SORT les positions ouvertes au bid/ask.

Écrit un statut (`experimental_paper_status.json`) : positions par moteur, 1er signal, refus par motif.
Aucun ordre réel, aucune signature. Rejouable à chaque cycle du lanceur.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from hl_observer.experimental import moteur_paper as MP
from hl_observer.experimental.signaux import COLLECTEURS

STATUS_RELPATH = Path("runtime") / "data" / "experimental_paper_status.json"


def _marks_cross_venue(root: Path) -> dict[str, dict]:
    """{coin: {hl_px, d_bps_h, base_bps, cout_ar_bps, ts}} pour marquer/sortir le carry cross-venue."""
    try:
        from hl_observer.funding.cross_venue_carry_judge import charger_series
        from hl_observer.funding.cross_venue_carry_paper import couts_carnet
    except Exception:  # noqa: BLE001
        return {}
    series = charger_series(root)
    couts = couts_carnet(root)
    out: dict[str, dict] = {}
    for c, s in series.items():
        if not s:
            continue
        ts, hl_px, bin_px, hl_f, bin_f = s[-1]
        out[c.upper()] = {"hl_px": hl_px, "d_bps_h": hl_f - bin_f,
                          "base_bps": 1e4 * (hl_px - bin_px) / bin_px if bin_px else 0.0,
                          "cout_ar_bps": couts.get(c.upper()), "ts": ts}
    return out


def _marks_hl_mid(root: Path, coins: set[str], *, max_lignes: int = 40000) -> dict[str, float]:
    """{coin: mid HL} depuis la tape BBO — pour marquer/sortir les positions directionnelles."""
    p = root / Path("runtime") / "data" / "bbo_tape.jsonl"
    if not p.exists():
        return {}
    out: dict[str, float] = {}
    for l in p.read_text(encoding="utf-8", errors="ignore").splitlines()[-max_lignes:]:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        c = str(d.get("coin") or "").upper()
        if c in coins and d.get("venue") == "HL" and d.get("bid") and d.get("ask"):
            out[c] = (float(d["bid"]) + float(d["ask"])) / 2.0
    return out


BASIS_ADVERSE_BPS = 15.0            # base qui dérive contre nous de > ça -> sortie


def _raison_sortie_carry(pos: dict, m: dict, car: dict | None, *, now_ms: float, age_h: float) -> str | None:
    """Les 6 sorties auto du carry : funding flip, quote périmée, liquidité insuffisante, basis adverse,
    edge net restant disparu, durée max. Renvoie le motif OU None (on garde)."""
    from hl_observer.experimental.carry_deux_jambes import CARNET_AGE_MAX_S
    d_now, d_ent = float(m["d_bps_h"]), float(pos.get("d_bps_h") or 0.0)
    if (d_now >= 0) != (d_ent >= 0):
        return "FUNDING_FLIP"
    if car and (now_ms / 1000.0 - float(car.get("collecte_ts") or 0.0)) > CARNET_AGE_MAX_S:
        return "QUOTE_PERIMEE"
    if car and float(car.get("taille_min_usd") or 0.0) < float(pos.get("notional_usd") or 0.0):
        return "LIQUIDITE_INSUFFISANTE"
    base_ent = float(pos.get("base_entree_bps") or 0.0)
    base_cur = float(m.get("base_bps") if m.get("base_bps") is not None else base_ent)
    if -int(pos.get("sens") or 1) * (base_cur - base_ent) < -BASIS_ADVERSE_BPS:
        return "BASIS_ADVERSE"
    if age_h >= float(pos.get("hold_h") or 168.0):          # durée max AVANT edge (sinon reste_h=0 masque)
        return "HOLD_ATTEINT"
    reste_h = max(0.0, float(pos.get("hold_h") or 168.0) - age_h)
    cout_ar = float((pos.get("meta") or {}).get("cout_ar_bps") or 0.0)
    if abs(d_now) * reste_h <= cout_ar:
        return "EDGE_DISPARU"
    return None


def _gerer_sorties(store: dict, root: Path, *, now_ms: float) -> list[dict]:
    """Sort les positions dont une condition de sortie est atteinte, au prix exécutable courant.
    Les sorties CROSS-VENUE sont GELÉES pendant l'audit (HYPERSMART_EXPERIMENTAL_CROSS_VENUE_GELE=1) :
    on garde la cohorte intacte. Les sorties directionnelles (lead-lag) restent actives."""
    import os
    fermetures: list[dict] = []
    cv = _marks_cross_venue(root)
    from hl_observer.experimental.carry_deux_jambes import carnet_par_coin
    carnet = carnet_par_coin(root)
    gele_cv = os.environ.get("HYPERSMART_EXPERIMENTAL_CROSS_VENUE_GELE", "0") == "1"
    dir_coins = {p["coin"] for p in store["ouvertes"].values() if p.get("type_pnl") == "directional"}
    mids = _marks_hl_mid(root, dir_coins) if dir_coins else {}
    for pos in list(store["ouvertes"].values()):
        age_h = (now_ms - float(pos.get("ts_ouverture_ms") or now_ms)) / 3.6e6
        if pos.get("type_pnl") == "funding_carry":
            if gele_cv:
                continue                                          # cohorte GELÉE pour l'audit -> aucune sortie
            m = cv.get(pos["coin"])
            if not m or m.get("hl_px") is None:
                continue                                          # pas de mark frais -> on GARDE (pas de sortie aveugle)
            raison = _raison_sortie_carry(pos, m, carnet.get(pos["coin"]), now_ms=now_ms, age_h=age_h)
            if raison:
                cout_sortie = (m.get("cout_ar_bps") or 0.0) / 2.0 + 3.3
                fermetures.append(MP.sortir(pos, store, root, prix_sortie=m["hl_px"],
                                            cout_sortie_bps=cout_sortie, base_courant_bps=m["base_bps"],
                                            raison=raison, now_ms=now_ms))
        else:  # directionnel (lead_lag / copy_vault)
            horizon_ms = float((pos.get("meta") or {}).get("horizon_ms") or 1000.0)
            mur_ms = max(horizon_ms, 2000.0) if pos["moteur"] == "lead_lag" else 24 * 3.6e6
            if (now_ms - float(pos.get("ts_ouverture_ms") or now_ms)) >= mur_ms:
                mid = mids.get(pos["coin"]) or pos.get("prix_entree")
                fermetures.append(MP.sortir(pos, store, root, prix_sortie=mid,
                                            cout_sortie_bps=float(pos.get("spread_bps") or 0.0) + float(pos.get("frais_bps") or 0.0),
                                            raison="HORIZON_ATTEINT", now_ms=now_ms))
    return fermetures


def tick(root: str | Path = ".", *, now_ms: float | None = None,
         moteurs: tuple[str, ...] | None = None) -> dict[str, Any]:
    """Un cycle complet. Renvoie {ouvertures, fermetures, refus, premier_signal, resume}."""
    root = Path(root)
    now = float(now_ms if now_ms is not None else time.time() * 1000)
    store = MP.charger_store(root)
    fermetures = _gerer_sorties(store, root, now_ms=now)          # d'abord les sorties (libère des slots)
    ouvertures: list[dict] = []
    refus: list[dict] = []
    premier_signal: dict | None = None
    for m in (moteurs or MP.MOTEURS):
        adaptateur = COLLECTEURS.get(m)
        if not adaptateur:
            continue
        try:
            sigs, refs = adaptateur(root, now_ms=now)
        except Exception as exc:  # noqa: BLE001 — un moteur qui échoue n'arrête pas les autres
            refus.append({"moteur": m, "motif": "ADAPTATEUR_ERREUR", "detail": str(exc)[:120]}); continue
        refus.extend(refs)
        sigs.sort(key=lambda s: -s.edge_estime_bps)              # les meilleurs edges d'abord
        for sig in sigs:
            ok, motif = MP.admettre(sig, store, now_ms=now)
            if not ok:
                refus.append({"moteur": m, "coin": sig.coin, "motif": motif}); continue
            pos = MP.ouvrir(sig, store, root, now_ms=now)
            info = {"moteur": m, "coin": sig.coin, "sens": sig.sens, "prix_entree": sig.prix_entree,
                    "cout_entree_bps": round(sig.cout_entree_bps, 3), "edge_estime_bps": sig.edge_estime_bps,
                    "notional_usd": sig.notional_usd, "type_pnl": sig.type_pnl}
            ouvertures.append(info)
            if premier_signal is None:
                premier_signal = info
    MP.sauver_store(root, store)
    resume = MP.resume(root)
    # 🔴 MtM COURANT par position -> pour que le dashboard MONTRE le mouvement (funding qui s'accumule,
    # prix qui bougent). Recalcule les marks une fois ; donnée absente -> MtM = coût d'entrée (honnête).
    from hl_observer.experimental.carry_deux_jambes import carnet_par_coin, decomposer
    cv = _marks_cross_venue(root)
    carnet = carnet_par_coin(root)
    dir_coins = {p["coin"] for p in store["ouvertes"].values() if p.get("type_pnl") == "directional"}
    mids = _marks_hl_mid(root, dir_coins) if dir_coins else {}
    positions = []
    mtm_total = 0.0
    for p in store["ouvertes"].values():
        m = cv.get(p["coin"]) or {}
        mtm = MP.pnl_courant_usd(p, mark=(mids.get(p["coin"]) or m.get("hl_px")),
                                 base_courant_bps=m.get("base_bps"), now_ms=now)
        mtm_total += mtm
        e = {"coin": p["coin"], "moteur": p["moteur"], "sens": p["sens"], "notional_usd": p["notional_usd"],
             "prix_entree": p["prix_entree"], "edge_estime_bps": p["edge_estime_bps"], "type_pnl": p["type_pnl"],
             "mtm_usd": round(mtm, 6), "age_min": round((now - float(p["ts_ouverture_ms"])) / 60000.0, 1)}
        if p.get("type_pnl") == "funding_carry":                 # AUDIT DEUX JAMBES + décomposition PnL
            dec = decomposer(p, carnet_courant=carnet.get(p["coin"]), d_courant=m.get("d_bps_h"),
                             base_courant_bps=m.get("base_bps"), now_ms=now)
            e["decomposition"] = dec
            e["jambes"] = dec.get("jambes") or (p.get("meta") or {}).get("jambes")
            e["hedge_ratio"] = dec.get("hedge_ratio") or (p.get("meta") or {}).get("hedge_ratio")
            e["liquidite_ok"] = dec.get("liquidite_ok")
        positions.append(e)
    from collections import Counter
    refus_par_motif = dict(Counter(r.get("motif") for r in refus))
    statut = {"ts": time.time(), "now_ms": int(now), "ouvertures": ouvertures, "fermetures": fermetures,
              "n_refus": len(refus), "refus_par_motif": refus_par_motif, "premier_signal": premier_signal,
              "resume": resume, "positions": positions, "mtm_total_usd": round(mtm_total, 6),
              "real_execution": False}
    p = root / STATUS_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(statut, ensure_ascii=False, indent=1), encoding="utf-8")
    import os
    os.replace(tmp, p)
    return statut


__all__ = ["tick", "STATUS_RELPATH"]
