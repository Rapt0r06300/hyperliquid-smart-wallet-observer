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
    "copy_vault":  {"max_positions": 4, "max_notional_usd": 200.0, "notional_usd": 50.0},
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
    ts_signal_ms: float                    # horodatage de la mesure (fraîcheur)
    roi_annuel_pct: float = 0.0            # ROI net annualisé estimé (doit battre HLP ~15-30 %)
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


def admettre(sig: Signal, store: dict, *, now_ms: float) -> tuple[bool, str | None]:
    """Porte d'admission — SANS prouve_oos. Fraîcheur + exécutable + edge net > 0 + limites moteur.
    Renvoie (True, None) si admis, sinon (False, motif). Un refus est TOUJOURS motivé."""
    if sig.moteur not in LIMITES:
        return False, "MOTEUR_INCONNU"
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
    return True, None


def ouvrir(sig: Signal, store: dict, root: str | Path, *, now_ms: float) -> dict:
    """Ouvre la position PAPER à `prix_entree` (exécutable), débite le coût d'entrée, journalise OPEN."""
    cle = "%s:%s" % (sig.moteur, sig.coin.upper())
    pos = {
        "id": cle, "moteur": sig.moteur, "coin": sig.coin.upper(), "sens": int(sig.sens),
        "type_pnl": sig.type_pnl, "notional_usd": float(sig.notional_usd),
        "prix_entree": float(sig.prix_entree), "cout_entree_bps": float(sig.cout_entree_bps),
        "edge_estime_bps": float(sig.edge_estime_bps), "ts_ouverture_ms": int(now_ms),
        "frais_bps": float(sig.frais_bps), "spread_bps": float(sig.spread_bps),
        "slippage_bps": float(sig.slippage_bps), "latence_ms": float(sig.latence_ms),
        "d_bps_h": float(sig.d_bps_h), "base_entree_bps": float(sig.base_entree_bps),
        "hold_h": float(sig.hold_h), "meta": dict(sig.meta),
        "cout_entree_usd": round(_cout_usd(sig.cout_entree_bps, sig.notional_usd), 6),
    }
    store["ouvertes"][cle] = pos
    _ledger(root, {"kind": "OPEN", "strategie": sig.moteur, "coin": pos["coin"], "sens": pos["sens"],
                   "notional_usd": pos["notional_usd"], "prix_entree": pos["prix_entree"],
                   "cout_entree_bps": pos["cout_entree_bps"], "edge_estime_bps": pos["edge_estime_bps"],
                   "type_pnl": pos["type_pnl"], "ts_ms": int(now_ms)})
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
    mtm = pnl_courant_usd(pos, mark=prix_sortie, base_courant_bps=base_courant_bps, now_ms=now_ms)
    realized = round(mtm - _cout_usd(cout_sortie_bps, pos.get("notional_usd") or 0.0), 6)
    store["ouvertes"].pop(pos["id"], None)
    _ledger(root, {"kind": "CLOSE", "strategie": pos["moteur"], "coin": pos["coin"],
                   "realized_net_pnl_usdc": realized, "prix_sortie": prix_sortie,
                   "cout_sortie_bps": float(cout_sortie_bps), "raison": raison,
                   "edge_estime_bps": pos.get("edge_estime_bps"), "ts_ms": int(now_ms)})
    return {"coin": pos["coin"], "moteur": pos["moteur"], "realized_usd": realized, "raison": raison}


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
            if r.get("kind") == "CLOSE":
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
           "LIMITES", "MOTEURS", "Signal", "charger_store", "sauver_store", "admettre", "ouvrir",
           "pnl_courant_usd", "sortir", "resume"]
