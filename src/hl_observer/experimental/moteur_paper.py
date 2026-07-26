"""MOTEUR EXPERIMENTAL_PAPER — le cœur commun des 3 moteurs (cross-venue, lead-lag, copy-vaults).

Ouvre de VRAIES positions SIMULÉES dès qu'un signal est FRAIS + EXÉCUTABLE + edge net estimé > 0 après
coûts, SANS exiger `prouve_oos` (l'allocateur strict de promotion reste séparé et intact). Ledger,
budget et limites ISOLÉS du livre live : rien de ce moteur n'entre dans le PnL canonique.

Règles dures conservées : aucun ordre réel, aucune signature (real_execution=False partout) ; entrées
ET sorties aux bid/ask avec frais + spread + slippage + latence + risque de jambe ; aucun signal inventé
(un signal vient d'une mesure réelle datée) ; donnée périmée/incomplète → NO_TRADE avec motif.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from hl_observer.experimental import invariants as INV

MODE = "EXPERIMENTAL_PAPER"
VERSION = "v2"                            # v1 (carry-style) EN QUARANTAINE ; v2 = deux jambes VWAP + barème exigeant
LEDGER_RELPATH = Path("runtime") / "data" / ("experimental_paper_%s_ledger.jsonl" % VERSION)
POSITIONS_RELPATH = Path("runtime") / "data" / ("experimental_paper_%s_positions.json" % VERSION)
STATUS_RELPATH = Path("runtime") / "data" / ("experimental_paper_%s_status.json" % VERSION)

BUDGET_TOTAL_USD = 1000.0                 # budget FICTIF isolé (jamais le capital live)
AGE_MAX_SIGNAL_MS = 30_000.0              # un signal plus vieux que ça = périmé (NO_TRADE)
#: 🔴 BARÈME EXIGEANT v2 (Flo) : « PnL énorme, ROI ultra positif, refuse micro-edges / illiquide /
#: capital-pour-des-centimes ». On ne prend QUE ce qui bat clairement l'alternative (HLP ~15-30 %/an).
MIN_EDGE_NET_BPS = 12.0                   # edge net après TOUS les coûts < ça -> micro-edge, REFUSÉ
MIN_ROI_ANNUEL_NET_PCT = 15.0            # ROI net annualisé < ça -> dominé par HLP/cash, REFUSÉ
MIN_PNL_ATTENDU_USD = 0.25               # PnL attendu sur le hold < ça -> capital pour des centimes, REFUSÉ
#: petites limites PAR moteur : max positions simultanées, notional max déployé, notional par entrée.
LIMITES: dict[str, dict[str, float]] = {
    "cross_venue": {"max_positions": 6, "max_notional_usd": 300.0, "notional_usd": 50.0},
    "lead_lag":    {"max_positions": 4, "max_notional_usd": 200.0, "notional_usd": 50.0},
    "copy_vault":  {"max_positions": 4, "max_notional_usd": 600.0, "notional_usd": 150.0},
}
MOTEURS = tuple(LIMITES)


@dataclass
class Signal:
    """Un signal ADMISSIBLE candidat. Vient TOUJOURS d'une mesure réelle datée (jamais inventé)."""
    moteur: str                            # cross_venue | lead_lag | copy_vault
    coin: str
    sens: int                              # +1 long / -1 short (directionnel) ; pour le carry = signe du funding
    type_pnl: str                          # "directional" | "funding_carry"
    notional_usd: float
    prix_entree: float                     # prix EXÉCUTABLE d'entrée (bid si on vend, ask si on achète)
    cout_entree_bps: float                 # frais + demi-spread + slippage payés À L'ENTRÉE
    edge_estime_bps: float                 # edge NET estimé après TOUS les coûts (doit passer le barème)
    ts_signal_ms: float                    # horodatage RÉEL de l'événement (trade Binance / snapshot leader), pas now
    roi_annuel_pct: float | None = None    # ROI net annualisé estimé, ou None = NON MESURÉ (≠ 0.0 qui bloquait tout)
    pnl_attendu_usd: float = 0.0           # PnL $ attendu sur le hold (refuse les centimes)
    frais_bps: float = 0.0
    spread_bps: float = 0.0
    slippage_bps: float = 0.0
    latence_ms: float = 0.0
    d_bps_h: float = 0.0                   # carry : funding net/heure signé
    base_entree_bps: float = 0.0           # carry : base (hl_px-bin_px) à l'entrée
    hold_h: float = 168.0                  # carry : horizon d'amortissement
    meta: dict[str, Any] = field(default_factory=dict)


def _p(root: str | Path, rel: Path) -> Path:
    return Path(root) / rel


def charger_store(root: str | Path = ".") -> dict[str, Any]:
    try:
        d = json.loads(_p(root, POSITIONS_RELPATH).read_text(encoding="utf-8"))
        if isinstance(d, dict) and d.get("mode") == MODE and isinstance(d.get("ouvertes"), dict):
            return d
    except (OSError, ValueError):
        pass
    return {"mode": MODE, "ouvertes": {}}


def sauver_store(root: str | Path, store: dict[str, Any]) -> None:
    p = _p(root, POSITIONS_RELPATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _ledger(root: str | Path, row: dict[str, Any]) -> None:
    """Append-only au ledger ISOLÉ. Toujours mode=EXPERIMENTAL_PAPER + real_execution=False."""
    p = _p(root, LEDGER_RELPATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    row = {**row, "mode": MODE, "real_execution": False}
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _cout_usd(bps: float, notional: float) -> float:
    return float(bps) / 1e4 * float(notional)


def _positions_moteur(store: dict, moteur: str) -> list[dict]:
    return [p for p in store["ouvertes"].values() if p.get("moteur") == moteur]


#: tolérance d'horloge : un signal horodaté dans le FUTUR au-delà de ça = donnée corrompue (P8).
CLOCK_SKEW_TOL_MS = 2_000.0


def admettre(sig: Signal, store: dict, *, now_ms: float, mode: str = "experimental_paper") -> tuple[bool, str | None]:
    """Porte d'admission — SANS prouve_oos. Fraîcheur + exécutable + edge net > 0 + limites moteur.
    Renvoie (True, None) si admis, sinon (False, motif). Un refus est TOUJOURS motivé.

    `mode` (LOT14 P0) :
      * "experimental_paper" (défaut) : ROI INFORMATIF — un ROI non mesuré (None) N'INTERDIT PAS la
        collecte forward sous limites isolées ; un candidat valide n'est jamais rejeté pour roi=indéterminé ;
      * "strict" : ROI doit être MESURÉ et >= plancher (sinon ROI_NON_MESURABLE / ROI_INSUFFISANT)."""
    if sig.moteur not in LIMITES:
        return False, "MOTEUR_INCONNU"
    # 🔴 LOT14 #3 : validation numérique CENTRALE d'abord — aucune décision sur un NaN/inf/notionnel<=0/horizon<=0.
    ok_num, motif_num = INV.valider_signal(sig)
    if not ok_num:
        return False, motif_num
    # 🔴 P8 : un horodatage dans le FUTUR (au-delà de la tolérance d'horloge) = donnée corrompue.
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
    if float(sig.edge_estime_bps) < MIN_EDGE_NET_BPS:          # 🔴 barème v2 : refuse les micro-edges
        return False, "MICRO_EDGE"
    # 🔴 LOT14 P0 : gate ROI DEUX VOIES. En strict, le ROI doit être mesuré et battre le plancher. En
    # experimental_paper, le ROI est INFORMATIF : un ROI indéterminé (None) ne bloque PAS la collecte forward
    # (le bug corrigé : roi=0.0 par défaut rejetait TOUS les vrais signaux avec ROI_INSUFFISANT).
    if mode == "strict":
        ok_roi, motif_roi = INV.roi_gate(sig.roi_annuel_pct, min_roi=MIN_ROI_ANNUEL_NET_PCT)
        if not ok_roi:
            return False, motif_roi
    if float(sig.pnl_attendu_usd) < MIN_PNL_ATTENDU_USD:       # capital immobilisé pour des centimes
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
    # 🔴 LOT14 #2 : gate BUDGET GLOBAL — les limites par moteur totalisent 1100 > budget 1000 ; on borne la
    # somme de TOUTES les positions (tous moteurs) au budget total. Sans ça, le PnL/ROI reposerait sur un
    # capital incohérent.
    ok_bud, motif_bud = INV.budget_global_ok(store, sig.notional_usd, budget_total=BUDGET_TOTAL_USD)
    if not ok_bud:
        return False, motif_bud
    return True, None


def _nouveau_position_id(moteur: str, coin: str, now_ms: float) -> str:
    """position_id UNIQUE par ÉPISODE (P9) : la clé moteur:coin peut se réutiliser sur des épisodes
    successifs ; le position_id, lui, ne se répète jamais (horodatage + suffixe aléatoire court)."""
    import uuid
    return "%s:%s:%d:%s" % (moteur, coin.upper(), int(now_ms), uuid.uuid4().hex[:8])


def ouvrir(sig: Signal, store: dict, root: str | Path, *, now_ms: float) -> dict:
    """Ouvre la position PAPER à `prix_entree` (exécutable), débite le coût d'entrée, journalise OPEN.
    LOT14 : position_id unique (P9), initial_paper_notional_usd + suivi de coûts cumulés (P1/P4),
    et champs de déduplication du snapshot leader (P1) initialisés à l'entrée."""
    cle = "%s:%s" % (sig.moteur, sig.coin.upper())
    notional0 = float(sig.notional_usd)
    cout_entree_usd = round(_cout_usd(sig.cout_entree_bps, notional0), 6)
    pos = {
        "id": cle, "position_id": _nouveau_position_id(sig.moteur, sig.coin, now_ms),
        "moteur": sig.moteur, "coin": sig.coin.upper(), "sens": int(sig.sens),
        "type_pnl": sig.type_pnl, "notional_usd": notional0,
        "initial_paper_notional_usd": notional0,                # P1 : référence FIGÉE (jamais re-multipliée)
        "prix_entree": float(sig.prix_entree), "cout_entree_bps": float(sig.cout_entree_bps),
        "edge_estime_bps": float(sig.edge_estime_bps), "ts_ouverture_ms": int(now_ms),
        "ts_signal_ms": float(sig.ts_signal_ms), "roi_annuel_pct": sig.roi_annuel_pct,
        "frais_bps": float(sig.frais_bps), "spread_bps": float(sig.spread_bps),
        "slippage_bps": float(sig.slippage_bps), "latence_ms": float(sig.latence_ms),
        "d_bps_h": float(sig.d_bps_h), "base_entree_bps": float(sig.base_entree_bps),
        "hold_h": float(sig.hold_h), "meta": dict(sig.meta),
        "cout_entree_usd": cout_entree_usd,
        # P4 : suivi des coûts pour répartir le coût d'entrée sur chaque tranche fermée
        "entry_cost_remaining_usd": cout_entree_usd,
        "cumulative_realized_usd": 0.0, "cumulative_entry_cost_allocated_usd": 0.0,
        "cumulative_exit_cost_usd": 0.0,
        # P1 : déduplication du snapshot leader — on n'applique une réduction qu'une seule fois par snapshot
        "entry_leader_szi": float((sig.meta or {}).get("szi_apres") or 0.0),
        "last_leader_szi_applied": float((sig.meta or {}).get("szi_apres") or 0.0),
        "last_vault_snapshot_ts": float((sig.meta or {}).get("snapshot_ts_ms") or now_ms),
        "last_vault_snapshot_id": (sig.meta or {}).get("snapshot_id"),
    }
    store["ouvertes"][cle] = pos
    _ledger(root, {"kind": "OPEN", "position_id": pos["position_id"], "strategie": sig.moteur,
                   "coin": pos["coin"], "sens": pos["sens"], "notional_usd": pos["notional_usd"],
                   "prix_entree": pos["prix_entree"], "cout_entree_bps": pos["cout_entree_bps"],
                   "edge_estime_bps": pos["edge_estime_bps"], "roi_annuel_pct": sig.roi_annuel_pct,
                   "type_pnl": pos["type_pnl"], "ts_ms": int(now_ms), "ts_signal_ms": float(sig.ts_signal_ms)})
    return pos


def pnl_courant_usd(pos: dict, *, mark: float | None = None, base_courant_bps: float | None = None,
                    now_ms: float | None = None) -> float:
    """Mark-to-market en USD, HORS coût de sortie (ajouté à la fermeture). Directionnel = variation de
    prix × sens ; funding_carry = funding accru + dérive de base − rien inventé si la donnée manque."""
    notional = float(pos.get("notional_usd") or 0.0)
    entree_cout = _cout_usd(pos.get("cout_entree_bps") or 0.0, notional)
    if pos.get("type_pnl") == "funding_carry":
        now = float(now_ms if now_ms is not None else time.time() * 1000)
        ts_ouv = pos.get("ts_ouverture_ms")           # 🔴 ne PAS faire `or now` : ts=0 est falsy -> heures=0
        ts_ouv = float(ts_ouv) if ts_ouv is not None else now
        heures = max(0.0, (now - ts_ouv) / 3.6e6)
        funding = float(pos.get("d_bps_h") or 0.0) * heures / 1e4 * notional
        derive = 0.0
        if base_courant_bps is not None:
            derive = -abs(float(base_courant_bps) - float(pos.get("base_entree_bps") or 0.0)) / 1e4 * notional
        return round(funding + derive - entree_cout, 6)
    if pos.get("type_pnl") == "dislocation":                   # court terme : convergence de l'écart capturée
        gap_ent = float((pos.get("meta") or {}).get("gap_entree_bps") or pos.get("base_entree_bps") or 0.0)
        gap_cur = float(base_courant_bps) if base_courant_bps is not None else gap_ent
        return round((gap_ent - gap_cur) / 1e4 * notional - entree_cout, 6)
    # directionnel : variation relative de prix × sens
    if mark is None or not pos.get("prix_entree"):
        return round(-entree_cout, 6)
    var = (float(mark) - float(pos["prix_entree"])) / float(pos["prix_entree"])
    return round(int(pos.get("sens") or 1) * var * notional - entree_cout, 6)


def sortir(pos: dict, store: dict, root: str | Path, *, prix_sortie: float | None,
           cout_sortie_bps: float, raison: str, now_ms: float,
           base_courant_bps: float | None = None) -> dict:
    """Ferme la position au bid/ask (prix_sortie), retranche le coût de sortie, journalise CLOSE."""
    notional_ferme = float(pos.get("notional_usd") or 0.0)                 # le résidu, entièrement fermé
    exit_cost_usd = _cout_usd(cout_sortie_bps, notional_ferme)
    mtm = pnl_courant_usd(pos, mark=prix_sortie, base_courant_bps=base_courant_bps, now_ms=now_ms)
    realized = round(mtm - exit_cost_usd, 6)
    entry_cost_alloc = float(pos.get("entry_cost_remaining_usd") or 0.0)   # P4 : le résidu du coût d'entrée
    store["ouvertes"].pop(pos["id"], None)
    _ledger(root, {"kind": "CLOSE", "position_id": pos.get("position_id"), "strategie": pos["moteur"],
                   "coin": pos["coin"], "realized_net_pnl_usdc": realized, "prix_sortie": prix_sortie,
                   "cout_sortie_bps": float(cout_sortie_bps), "raison": raison,
                   "notional_ferme_usd": round(notional_ferme, 6),
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
    """REDUCE PARTIEL : le LEADER a réduit -> on ferme la FRACTION réduite au prix exécutable et on GARDE le
    résidu ouvert. `realized_usd` inclut DÉJÀ le coût d'entrée réparti (P4) calculé par reduce_proportionnel.
    Met à jour les cumuls (P4) et les marqueurs de déduplication du snapshot leader (P1). Journalise REDUCE."""
    pos["notional_usd"] = round(float(notional_residuel_usd), 6)
    pos["entry_cost_remaining_usd"] = round(max(0.0, float(pos.get("entry_cost_remaining_usd") or 0.0)
                                                 - float(entry_cost_allocated_usd)), 6)
    pos["cumulative_realized_usd"] = round(float(pos.get("cumulative_realized_usd") or 0.0) + float(realized_usd), 6)
    pos["cumulative_entry_cost_allocated_usd"] = round(
        float(pos.get("cumulative_entry_cost_allocated_usd") or 0.0) + float(entry_cost_allocated_usd), 6)
    pos["cumulative_exit_cost_usd"] = round(float(pos.get("cumulative_exit_cost_usd") or 0.0) + float(exit_cost_usd), 6)
    if leader_szi_applied is not None:                          # P1 : mémorise l'état leader DÉJÀ appliqué
        pos["last_leader_szi_applied"] = float(leader_szi_applied)
    if snapshot_ts is not None:
        pos["last_vault_snapshot_ts"] = float(snapshot_ts)
    if snapshot_id is not None:
        pos["last_vault_snapshot_id"] = snapshot_id
    _ledger(root, {"kind": "REDUCE", "position_id": pos.get("position_id"), "strategie": pos["moteur"],
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
    """P7 — FERME une DISLOCATION comme DEUX JAMBES réconciliées : le realized = SOMME EXACTE des jambes
    (venue/side/entrée_exec/sortie_exec/taille/frais/slippage), jamais un seul mid HL ni une convergence
    synthétique. Écrit le détail des DEUX jambes dans le ledger CLOSE."""
    from hl_observer.experimental.execution_paper import pnl_deux_jambes
    res = pnl_deux_jambes(jambes)
    realized = round(float(res["realized_usd"]), 6)
    entry_cost_alloc = float(pos.get("entry_cost_remaining_usd") or 0.0)
    store["ouvertes"].pop(pos["id"], None)
    _ledger(root, {"kind": "CLOSE", "position_id": pos.get("position_id"), "strategie": pos["moteur"],
                   "coin": pos["coin"], "realized_net_pnl_usdc": realized, "raison": raison,
                   "notional_ferme_usd": round(float(pos.get("notional_usd") or 0.0), 6),
                   "entry_cost_allocated_usd": round(entry_cost_alloc, 6),
                   "jambes": res["jambes"], "n_jambes": res["n_jambes"],
                   "edge_estime_bps": pos.get("edge_estime_bps"), "ts_ms": int(now_ms)})
    return {"coin": pos["coin"], "moteur": pos["moteur"], "realized_usd": realized, "raison": raison,
            "position_id": pos.get("position_id"), "jambes": res["jambes"]}


def resume(root: str | Path = ".") -> dict[str, Any]:
    """État du livre EXPERIMENTAL_PAPER pour le dashboard/rapport : positions + PnL réalisé, PAR moteur."""
    store = charger_store(root)
    par_moteur: dict[str, dict[str, float]] = {m: {"positions": 0, "realise_usd": 0.0} for m in MOTEURS}
    for p in store["ouvertes"].values():
        m = p.get("moteur")
        if m in par_moteur:
            par_moteur[m]["positions"] += 1
    realized_total = 0.0
    try:
        for l in _p(root, LEDGER_RELPATH).read_text(encoding="utf-8").splitlines():
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if r.get("kind") in ("CLOSE", "REDUCE"):        # 🔴 P5 : le realized vient AUSSI des REDUCE partiels
                v = float(r.get("realized_net_pnl_usdc") or 0.0)
                realized_total += v
                if r.get("strategie") in par_moteur:
                    par_moteur[r["strategie"]]["realise_usd"] += v
    except OSError:
        pass
    return {"mode": MODE, "positions_ouvertes": len(store["ouvertes"]),
            "realise_total_usd": round(realized_total, 6), "par_moteur": par_moteur,
            "budget_total_usd": BUDGET_TOTAL_USD, "real_execution": False}


__all__ = ["MODE", "LEDGER_RELPATH", "POSITIONS_RELPATH", "BUDGET_TOTAL_USD", "AGE_MAX_SIGNAL_MS",
           "CLOCK_SKEW_TOL_MS", "LIMITES", "MOTEURS", "Signal", "charger_store", "sauver_store", "admettre",
           "ouvrir", "pnl_courant_usd", "sortir", "reduire", "sortir_deux_jambes", "resume"]
