"""Persistance sur disque de l'ETAPE 2 du carry (positions ouvertes + ledger PnL realise).

Le core `carry_position_lifecycle` est PUR (sans I/O). Ici on ajoute la couche disque pour que les
positions survivent entre les polls du bot :
  * `runtime/data/carry_paper_positions.json`  -> les positions OUVERTES (dict coin->pos), avec le `mode` ;
  * `runtime/data/carry_paper_ledger.jsonl`    -> append-only : chaque OPEN / CLOSE (PnL realise).

Regle dure : un fichier d'etat = UN seul mode. Si le mode demande != le mode du fichier, on repart
VIDE (jamais de melange LIVE/BACKTEST/REPLAY/TEST_FIXTURE). PAPER only : aucun ordre, aucune signature.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hl_observer.funding.carry_position_lifecycle import (
    MODE_LIVE, MODES_VALIDES, GestionnaireCarry, pnl_realise,
)

SORTIE_HORS_SHORTLIST = "COIN_PLUS_DANS_SHORTLIST"

POSITIONS_RELPATH = Path("runtime") / "data" / "carry_paper_positions.json"
LEDGER_RELPATH = Path("runtime") / "data" / "carry_paper_ledger.jsonl"


def _positions_path(root: str | Path) -> Path:
    return Path(root) / POSITIONS_RELPATH


def _ledger_path(root: str | Path) -> Path:
    return Path(root) / LEDGER_RELPATH


def charger_gestionnaire(root: str | Path = ".", *, mode: str = MODE_LIVE) -> GestionnaireCarry:
    """Reconstruit le gestionnaire depuis le disque. Mode different sur le fichier -> on repart VIDE
    (on ne melange jamais deux modes de PnL)."""
    if mode not in MODES_VALIDES:
        raise ValueError("mode inconnu: %r" % (mode,))
    try:
        data = json.loads(_positions_path(root).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = None
    ouvertes: dict[str, dict[str, Any]] = {}
    if isinstance(data, dict) and data.get("mode") == mode and isinstance(data.get("ouvertes"), dict):
        for coin, pos in data["ouvertes"].items():
            if isinstance(pos, dict) and pos.get("mode") == mode:
                ouvertes[str(coin).upper()] = pos
    return GestionnaireCarry(mode=mode, ouvertes=ouvertes)


def sauver_gestionnaire(root: str | Path, g: GestionnaireCarry) -> None:
    p = _positions_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"mode": g.mode, "ouvertes": g.ouvertes}, ensure_ascii=False, indent=2),
                 encoding="utf-8")


def _append_ledger(root: str | Path, row: dict[str, Any]) -> None:
    p = _ledger_path(root)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def tick_sur_disque(root: str | Path, decision: dict[str, Any], inputs: dict[str, Any], *,
                    now_ms: int, funding_bps_h_courant: float | None = None,
                    hausse_depuis_entree: float = 0.0, mode: str = MODE_LIVE) -> dict[str, Any]:
    """Une passe persistee : charge, tick (accrue/sort/ouvre), sauve, append OPEN/CLOSE au ledger."""
    g = charger_gestionnaire(root, mode=mode)
    evt = g.tick(decision, inputs, now_ms=now_ms, funding_bps_h_courant=funding_bps_h_courant,
                 hausse_depuis_entree=hausse_depuis_entree)
    sauver_gestionnaire(root, g)
    for r in g.journal.rows():                       # journal frais a chaque charge -> uniquement CE tick
        _append_ledger(root, {**r, "ts_ms": int(now_ms), "mode": mode})
    return evt


def tick_multi_sur_disque(root: str | Path, mesures: dict[str, dict[str, Any]], *,
                          now_ms: int, mode: str = MODE_LIVE) -> list[dict[str, Any]]:
    """Une passe MULTI-COINS persistee. `mesures` = {coin: {"decision","inputs","funding"}}.
    Ouvre/tient une position par coin mesuré ; FERME tout coin ouvert qui n'est PLUS mesuré ce
    poll (deny-by-default : on ne tient jamais une position sur une donnée disparue). Un coin =
    une position (le store est déjà multi-coins)."""
    g = charger_gestionnaire(root, mode=mode)
    evts: list[dict[str, Any]] = []
    for coin, m in mesures.items():
        evts.append(g.tick(m["decision"], m["inputs"], now_ms=now_ms,
                           funding_bps_h_courant=m.get("funding"), prix_courant=m.get("prix")))
    for coin in list(g.ouvertes):                      # coins ouverts mais absents des mesures -> fermer
        if coin not in mesures:
            pos = g.ouvertes[coin]
            realized = pnl_realise(pos)                # on réalise l'accru, sans inventer de funding en +
            g.journal.record(kind="CLOSE", coin=coin, side="CARRY", notional_usdt=pos["notional_usdt"],
                             realized_net_pnl_usdc=realized, reason=SORTIE_HORS_SHORTLIST, now_ms=int(now_ms))
            g.ouvertes.pop(coin, None)
            evts.append({"coin": coin, "mode": mode, "ouvert": False, "ferme": SORTIE_HORS_SHORTLIST,
                         "pnl_realise_usdt": realized, "funding_add_usdt": 0.0})
    sauver_gestionnaire(root, g)
    for r in g.journal.rows():
        _append_ledger(root, {**r, "ts_ms": int(now_ms), "mode": mode})
    return evts


def resume_depuis_ledger(root: str | Path = ".", *, mode: str = MODE_LIVE) -> dict[str, Any]:
    """Le PnL realise TOTAL, lu depuis le ledger append-only (source de verite, pas un compteur)."""
    realized, opens, closes = 0.0, 0, 0
    try:
        lignes = _ledger_path(root).read_text(encoding="utf-8").splitlines()
    except OSError:
        lignes = []
    for l in lignes:
        try:
            r = json.loads(l)
        except ValueError:
            continue
        if r.get("mode") != mode:
            continue
        if r.get("kind") == "OPEN":
            opens += 1
        elif r.get("kind") == "CLOSE":
            closes += 1
            realized += float(r.get("realized_net_pnl_usdc") or 0.0)
    return {"mode": mode, "opens": opens, "closes": closes,
            "realized_net_pnl_usdc": round(realized, 6)}


def etat_carry(root: str | Path = ".", *, mode: str = MODE_LIVE) -> dict[str, Any]:
    """Vue complete pour le dashboard/metrics : PnL realise CUMULE (du ledger) + positions
    ouvertes + funding deja accru (non encore realise). Source de verite = les fichiers, jamais
    un compteur en memoire."""
    r = resume_depuis_ledger(root, mode=mode)
    g = charger_gestionnaire(root, mode=mode)
    r["positions_ouvertes"] = len(g.ouvertes)
    r["coins_ouverts"] = sorted(g.ouvertes)
    r["funding_accru_ouvert_usdt"] = round(
        sum(float(p.get("funding_accrued_usdt") or 0.0) for p in g.ouvertes.values()), 6)
    return r


__all__ = ["POSITIONS_RELPATH", "LEDGER_RELPATH", "SORTIE_HORS_SHORTLIST", "charger_gestionnaire",
           "sauver_gestionnaire", "tick_sur_disque", "tick_multi_sur_disque", "resume_depuis_ledger",
           "etat_carry"]
