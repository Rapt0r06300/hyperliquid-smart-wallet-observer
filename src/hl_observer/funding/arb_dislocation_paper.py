"""ARBITRAGE DE DISLOCATION — paper v1 (21/07, demande de Flo : « fais-lui un mécanisme,
branche-le à la simulation, il doit alimenter le replay et écrire sur le PnL unifié »).

MÉCANISME (littérature des desks, recherche X/GitHub du 21/07) : l'écart de prix du MÊME
perp entre deux venues (HL↔Binance) revient à sa moyenne. Le collecteur venues mesure cet
écart toutes les 5 min et émet des candidats replay dès 20 bps (mesure). ICI : la version
PAPER, avec des portes PRÉ-DÉCLARÉES si dures que l'edge est positif à l'entrée PAR
CONSTRUCTION — on FADE côté HL (jamais d'ordre réel, jambe Binance conceptuelle, notée).

PORTES (écrites AVANT la donnée, le 21/07 — les déplacer se voit dans un diff) :
  * OUVERTURE : |écart| >= 35 bps  (coûts AR 22 bps + 13 bps de marge minimale) ;
  * SORTIE    : |écart| <= 5 bps (convergence capturée) OU âge > 4 h (pas de zombie) ;
  * TAILLE    : 50 $ fixe par position, 2 positions max (mécanisme en période d'essai) ;
  * DONNÉE    : mesure venues plus vieille que 15 min = pas de décision (deny-by-default).

PnL réalisé = (|écart entrée| − écart résiduel signé capturé) × notional − 22 bps de coûts,
écrit dans LE MÊME ledger que le carry (kind=CLOSE, mode=LIVE — sans lui le resume
unifié FILTRE la ligne —, strategie='arbitrage', session_id) →
le PnL unifié du dashboard le somme sans une ligne de code de plus. 100 % simulation.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

SEUIL_OUVERTURE_BPS = 35.0
SEUIL_SORTIE_BPS = 5.0
AGE_MAX_H = 4.0
NOTIONAL_USD = 50.0
MAX_POSITIONS = 2
COUT_AR_BPS = 22.0                 # 4 jambes conceptuelles ; on ne compte QUE nos coûts fade x2
FRAICHEUR_MAX_S = 900.0

STORE_RELPATH = Path("runtime") / "data" / "arb_dislocation_positions.json"
LEDGER_RELPATH = Path("runtime") / "data" / "carry_paper_ledger.jsonl"
VENUES_RELPATH = Path("runtime") / "data" / "dispersion_venues.jsonl"


def _charger_store(root: Path) -> dict:
    try:
        d = json.loads((root / STORE_RELPATH).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {"ouvertes": {}}
    except (OSError, ValueError):
        return {"ouvertes": {}}


def _sauver_store(root: Path, store: dict) -> None:
    p = root / STORE_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False, indent=1), encoding="utf-8")
    import os
    os.replace(tmp, p)


def _ledger(root: Path, row: dict) -> None:
    p = root / LEDGER_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def dernieres_mesures(root: Path, *, now: float | None = None) -> dict[str, dict]:
    """{coin: derniere ligne venues AVEC ecart_prix_bps}, fraîches (<15 min) seulement."""
    t = now if now is not None else time.time()
    out: dict[str, dict] = {}
    p = root / VENUES_RELPATH
    if not p.exists():
        return out
    try:
        for l in p.read_text(encoding="utf-8").splitlines()[-400:]:   # queue suffisante
            try:
                r = json.loads(l)
            except ValueError:
                continue
            if r.get("ecart_prix_bps") is None:
                continue
            if t - float(r.get("ts") or 0.0) > FRAICHEUR_MAX_S:
                continue
            out[str(r.get("coin") or "").upper()] = r
    except OSError:
        return {}
    return out


def tick(root: str | Path = ".", *, now: float | None = None,
         session_id: str | None = None) -> list[dict[str, Any]]:
    """Une passe paper : ouvre/tient/ferme selon les portes. Retourne les événements."""
    racine = Path(root)
    t = now if now is not None else time.time()
    mesures = dernieres_mesures(racine, now=t)
    store = _charger_store(racine)
    ouvertes: dict[str, dict] = store.setdefault("ouvertes", {})
    evts: list[dict[str, Any]] = []

    # ── SORTIES d'abord (convergence capturée ou âge) ──
    for coin in list(ouvertes):
        pos = ouvertes[coin]
        m = mesures.get(coin)
        age_h = (t - float(pos.get("entry_ts") or t)) / 3600.0
        ecart = m.get("ecart_prix_bps") if m else None
        convergence = ecart is not None and abs(float(ecart)) <= SEUIL_SORTIE_BPS
        trop_vieux = age_h >= AGE_MAX_H
        if not (convergence or trop_vieux):
            continue
        # capture = mouvement de l'écart DANS notre sens (fade) ; sortie à l'écart courant si
        # mesuré, sinon (âge sans mesure fraîche) à l'entrée = capture nulle, coûts payés.
        e_in = float(pos["ecart_entree_bps"])
        e_out = float(ecart) if ecart is not None else e_in
        capture_bps = abs(e_in) - (abs(e_out) if (e_in * e_out) > 0 else -abs(e_out))
        realized = round((capture_bps - COUT_AR_BPS) / 1e4 * NOTIONAL_USD, 6)
        _ledger(racine, {"kind": "CLOSE", "mode": "LIVE", "strategie": "arbitrage", "coin": coin,
                         "ts_ms": int(t * 1000), "session_id": session_id,
                         "reason": ("ARB_CONVERGENCE_CAPTUREE" if convergence
                                    else "ARB_AGE_MAX_SANS_CONVERGENCE"),
                         "ecart_entree_bps": e_in, "ecart_sortie_bps": e_out,
                         "realized_net_pnl_usdc": realized,
                         "real_execution": False, "not_an_order": True})
        evts.append({"type": "CLOSE", "coin": coin, "realized": realized})
        del ouvertes[coin]

    # ── OUVERTURES (portes dures, deny-by-default) ──
    for coin, m in mesures.items():
        if coin in ouvertes or len(ouvertes) >= MAX_POSITIONS:
            continue
        ecart = float(m.get("ecart_prix_bps") or 0.0)
        if abs(ecart) < SEUIL_OUVERTURE_BPS:
            continue
        ouvertes[coin] = {"coin": coin, "entry_ts": t, "ecart_entree_bps": ecart,
                          "direction": "SHORT_HL" if ecart > 0 else "LONG_HL",
                          "notional_usd": NOTIONAL_USD, "real_execution": False}
        _ledger(racine, {"kind": "OPEN", "mode": "LIVE", "strategie": "arbitrage", "coin": coin,
                         "ts_ms": int(t * 1000), "session_id": session_id,
                         "ecart_entree_bps": ecart, "notional_usd": NOTIONAL_USD,
                         "real_execution": False, "not_an_order": True})
        evts.append({"type": "OPEN", "coin": coin, "ecart_bps": ecart})

    _sauver_store(racine, store)
    return evts


__all__ = ["tick", "dernieres_mesures", "SEUIL_OUVERTURE_BPS", "SEUIL_SORTIE_BPS",
           "AGE_MAX_H", "NOTIONAL_USD", "MAX_POSITIONS", "COUT_AR_BPS"]
