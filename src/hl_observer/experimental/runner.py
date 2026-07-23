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

STATUS_RELPATH = MP.STATUS_RELPATH        # versionné (v2) : la v1 reste en quarantaine


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


def _gap_courant_bps(car: dict, sens: int) -> float:
    """Écart EXÉCUTABLE courant dans le sens d'entrée (bps). Converge vers 0 (ou négatif) quand les
    deux venues se rejoignent -> c'est le signal de déboucle rentable."""
    hl_bid, hl_ask = float(car["hl_bid"]), float(car["hl_ask"])
    bin_bid, bin_ask = float(car["bin_bid"]), float(car["bin_ask"])
    hl_mid, bin_mid = (hl_bid + hl_ask) / 2, (bin_bid + bin_ask) / 2
    if sens >= 0:                                              # long HL / short BIN
        return (bin_bid - hl_ask) / hl_mid * 1e4 if hl_mid else 0.0
    return (hl_bid - bin_ask) / bin_mid * 1e4 if bin_mid else 0.0


def _raison_sortie_dislocation(pos: dict, car: dict | None, *, now_ms: float) -> tuple[str | None, float]:
    """Sorties dislocation : convergence capturée, écart aggravé (stop), liquidité, quote périmée, durée
    max. Renvoie (motif|None, gap_courant_bps)."""
    from hl_observer.experimental.carry_deux_jambes import CARNET_AGE_MAX_S
    if not car:
        return None, 0.0                                      # pas de carnet -> on garde (pas de sortie aveugle)
    gap_ent = float((pos.get("meta") or {}).get("gap_entree_bps") or 0.0)
    gap_cur = _gap_courant_bps(car, int(pos.get("sens") or 1))
    age_min = (now_ms - float(pos.get("ts_ouverture_ms") or now_ms)) / 60000.0
    if (now_ms / 1000.0 - float(car.get("collecte_ts") or 0.0)) > CARNET_AGE_MAX_S:
        return "QUOTE_PERIMEE", gap_cur
    if float(car.get("taille_min_usd") or 0.0) < float(pos.get("notional_usd") or 0.0):
        return "LIQUIDITE_INSUFFISANTE", gap_cur
    if gap_cur <= gap_ent * 0.3:                              # écart quasi refermé -> on capture
        return "CONVERGENCE_CAPTUREE", gap_cur
    if gap_cur > gap_ent * 1.5:                               # écart s'aggrave contre nous -> stop
        return "ECART_AGGRAVE", gap_cur
    if age_min >= float(pos.get("hold_h") or 0.5) * 60.0:     # durée max (court terme)
        return "DUREE_MAX", gap_cur
    return None, gap_cur


def _leader_a_reduit(pos: dict, root: Path, *, seuil: float = 0.5) -> tuple[bool, str]:
    """Copy-vault (rectif Flo 23/07) : le LEADER a-t-il RÉDUIT/CLOS sa position sur le coin depuis notre
    entrée ? On copie son alpha ; s'il sort, le signal a disparu → on sort aussi. Lit le dernier snapshot
    du vault : |szi actuel| ≈ 0 → LEADER_A_CLOS ; < seuil × |szi à l'entrée| → LEADER_A_REDUIT."""
    import json as _j
    meta = pos.get("meta") or {}
    vault, coin = meta.get("vault"), str(pos.get("coin") or "").upper()
    szi_entree = abs(float(meta.get("szi_apres") or 0.0))
    if not vault or not coin or szi_entree <= 0:
        return False, ""
    try:
        lignes = (root / "runtime" / "data" / "vault_snapshots.jsonl").read_text(
            encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return False, ""
    dernier = None
    for l in reversed(lignes[-8000:]):
        try:
            d = _j.loads(l)
        except ValueError:
            continue
        if d.get("vault") == vault:
            dernier = d
            break
    if not dernier:
        return False, ""
    szi_now = 0.0
    for p in (dernier.get("positions") or []):
        if str(p.get("coin") or "").upper() == coin:
            szi_now = abs(float(p.get("szi") or 0.0))
            break
    if szi_now <= 1e-9:
        return True, "LEADER_A_CLOS"
    if szi_now < seuil * szi_entree:
        return True, "LEADER_A_REDUIT"
    return False, ""


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
        if pos.get("type_pnl") == "dislocation":              # cross-venue COURT TERME : capture/stop rapide
            car = carnet.get(pos["coin"])
            raison, gap_cur = _raison_sortie_dislocation(pos, car, now_ms=now_ms)
            if raison:
                px = (float(car["hl_bid"]) + float(car["hl_ask"])) / 2 if car else pos.get("prix_entree")
                fermetures.append(MP.sortir(pos, store, root, prix_sortie=px,
                                            cout_sortie_bps=float(pos.get("spread_bps") or 0.0) + float(pos.get("frais_bps") or 0.0),
                                            base_courant_bps=gap_cur, raison=raison, now_ms=now_ms))
        elif pos.get("type_pnl") == "funding_carry":         # LEGACY (v1 quarantaine) — plus émis en v2
            if gele_cv:
                continue
            m = cv.get(pos["coin"])
            if not m or m.get("hl_px") is None:
                continue
            raison = _raison_sortie_carry(pos, m, carnet.get(pos["coin"]), now_ms=now_ms, age_h=age_h)
            if raison:
                cout_sortie = (m.get("cout_ar_bps") or 0.0) / 2.0 + 3.3
                fermetures.append(MP.sortir(pos, store, root, prix_sortie=m["hl_px"],
                                            cout_sortie_bps=cout_sortie, base_courant_bps=m["base_bps"],
                                            raison=raison, now_ms=now_ms))
        else:  # directionnel (lead_lag / copy_vault)
            # COPY-VAULT : sortir si le LEADER a réduit/clos (suivi réel demandé par Flo), avant l'horizon
            leader_sort, raison_leader = (_leader_a_reduit(pos, root) if pos["moteur"] == "copy_vault" else (False, ""))
            horizon_ms = float((pos.get("meta") or {}).get("horizon_ms") or 1000.0)
            mur_ms = max(horizon_ms, 2000.0) if pos["moteur"] == "lead_lag" else 24 * 3.6e6
            horizon_atteint = (now_ms - float(pos.get("ts_ouverture_ms") or now_ms)) >= mur_ms
            if leader_sort or horizon_atteint:
                mid = mids.get(pos["coin"]) or pos.get("prix_entree")
                fermetures.append(MP.sortir(pos, store, root, prix_sortie=mid,
                                            cout_sortie_bps=float(pos.get("spread_bps") or 0.0) + float(pos.get("frais_bps") or 0.0),
                                            raison=(raison_leader or "HORIZON_ATTEINT"), now_ms=now_ms))
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
        car = carnet.get(p["coin"])
        typ = p.get("type_pnl")
        if typ == "dislocation":                                 # court terme : MtM = convergence de l'écart
            gap_ent = float((p.get("meta") or {}).get("gap_entree_bps") or 0.0)
            gap_cur = _gap_courant_bps(car, int(p.get("sens") or 1)) if car else gap_ent
            mtm = MP.pnl_courant_usd(p, base_courant_bps=gap_cur, now_ms=now)
        else:
            m = cv.get(p["coin"]) or {}
            mtm = MP.pnl_courant_usd(p, mark=(mids.get(p["coin"]) or m.get("hl_px")),
                                     base_courant_bps=m.get("base_bps"), now_ms=now)
        mtm_total += mtm
        e = {"coin": p["coin"], "moteur": p["moteur"], "sens": p["sens"], "notional_usd": p["notional_usd"],
             "prix_entree": p["prix_entree"], "edge_estime_bps": p["edge_estime_bps"], "type_pnl": typ,
             "mtm_usd": round(mtm, 6), "age_min": round((now - float(p["ts_ouverture_ms"])) / 60000.0, 1)}
        if typ == "dislocation":
            e["jambes"] = (p.get("meta") or {}).get("jambes")
            e["hedge_ratio"] = (p.get("meta") or {}).get("hedge_ratio")
            e["liquidite_ok"] = bool(car and float(car.get("taille_min_usd") or 0.0) >= float(p["notional_usd"]))
            e["decomposition"] = {"gap_entree_bps": round(gap_ent, 3), "gap_courant_bps": round(gap_cur, 3),
                                  "convergence_bps": round(gap_ent - gap_cur, 3), "funding_settled_usd": 0.0,
                                  "funding_accru_estime_usd": 0.0, "pnl_basis_usd": round((gap_ent - gap_cur) / 1e4 * float(p["notional_usd"]), 6),
                                  "frais_entree_payes_usd": round(MP._cout_usd(p.get("cout_entree_bps") or 0.0, p["notional_usd"]), 6),
                                  "pnl_liquidable_maintenant_usd": round(mtm, 6)}
        elif typ == "funding_carry":                            # legacy quarantaine
            dec = decomposer(p, carnet_courant=car, d_courant=None, base_courant_bps=None, now_ms=now)
            e["decomposition"] = dec
            e["jambes"] = dec.get("jambes") or (p.get("meta") or {}).get("jambes")
            e["hedge_ratio"] = dec.get("hedge_ratio") or (p.get("meta") or {}).get("hedge_ratio")
            e["liquidite_ok"] = dec.get("liquidite_ok")
        positions.append(e)
    from collections import Counter
    refus_par_motif = dict(Counter(r.get("motif") for r in refus))
    try:
        from hl_observer.experimental.signaux import metriques_cross_venue
        metriques = metriques_cross_venue(root)
    except Exception:  # noqa: BLE001 — les métriques ne bloquent jamais le tick
        metriques = {}
    statut = {"ts": time.time(), "now_ms": int(now), "ouvertures": ouvertures, "fermetures": fermetures,
              "n_refus_ce_tick": len(refus), "refus_par_motif_ce_tick": refus_par_motif,   # PAR TICK, pas cumulé
              "premier_signal": premier_signal, "resume": resume, "positions": positions,
              "mtm_total_usd": round(mtm_total, 6), "metriques_cross_venue": metriques, "real_execution": False}
    p = root / STATUS_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(statut, ensure_ascii=False, indent=1), encoding="utf-8")
    import os
    os.replace(tmp, p)
    return statut


__all__ = ["tick", "STATUS_RELPATH"]
