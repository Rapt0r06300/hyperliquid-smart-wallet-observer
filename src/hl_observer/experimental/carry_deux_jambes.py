"""AUDIT DEUX JAMBES du carry cross-venue EXPERIMENTAL_PAPER (correction Flo 23/07).

Un carry delta-neutre = DEUX jambes perp exécutables (HL + Binance), pas un « mid » unique. Ce module
construit les deux jambes aux VRAIS bid/ask du carnet (profondeur, demi-spread et frais SÉPARÉS par
venue), et décompose le PnL en postes distincts :
  * frais d'entrée RÉELLEMENT payés (demi-spread croisé + taker, les DEUX jambes) — réalisé ;
  * coût de sortie SEULEMENT estimé (au carnet courant) — pas encore payé ;
  * funding SETTLED heure par heure (heures pleines franchies) vs funding COURU estimé (heure en cours) ;
  * PnL de BASIS (dérive hl_px−bin_px, delta-neutre) ;
  * PnL total LIQUIDABLE maintenant (ce qu'on encaisserait en fermant tout de suite).

Frais takers RÉALISTES (le v1 les sous-estimait) : on croise le spread (fill au bid/ask) ET on paie le
taker. Profondeur fine -> slippage, voire LIQUIDITE_INSUFFISANTE. Lecture seule, aucun ordre réel.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CARNET_RELPATH = Path("runtime") / "data" / "carnet_venues.jsonl"
FRAIS_TAKER_HL_BPS = 3.5           # HL perp taker (tier 0, conservateur)
FRAIS_TAKER_BIN_BPS = 4.5          # Binance USDⓈ-M perp taker (conservateur)
CARNET_AGE_MAX_S = 120.0           # carnet plus vieux = quote périmée


def carnet_par_coin(root: str | Path = ".", *, max_lignes: int = 60000) -> dict[str, dict]:
    """{coin: dernière ligne de carnet} (bid/ask des deux venues, demi-spreads, profondeur, ts)."""
    p = Path(root) / CARNET_RELPATH
    if not p.exists():
        return {}
    out: dict[str, dict] = {}
    for l in p.read_text(encoding="utf-8", errors="ignore").splitlines()[-max_lignes:]:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        c = str(d.get("coin") or "").upper()
        if c and d.get("hl_bid") and d.get("bin_bid"):
            out[c] = d
    return out


def _slippage_bps(notional: float, profondeur_usd: float, demi_spread_bps: float) -> float:
    """Slippage estimé : nul si le notional tient dans la profondeur top-of-book, sinon on « marche »
    le carnet -> pénalité ∝ au dépassement (proxy conservateur, faute de profondeur multi-niveaux)."""
    prof = float(profondeur_usd or 0.0)
    if prof <= 0:
        return demi_spread_bps * 4.0                       # profondeur inconnue -> pénalité forte
    if notional <= prof:
        return 0.0
    return (notional / prof - 1.0) * demi_spread_bps * 2.0  # dépassement -> slippage croissant


def construire_jambes(coin: str, sens: int, notional: float, carnet: dict) -> dict[str, Any]:
    """Les DEUX jambes exécutables. `sens=+1` -> SHORT HL / LONG Binance (funding HL > Binance) ;
    `sens=-1` -> LONG HL / SHORT Binance. Chaque jambe : venue, sens, qté, prix EXÉCUTABLE (bid si on
    vend, ask si on achète), profondeur, demi-spread, frais, slippage — tout SÉPARÉ."""
    hl_bid, hl_ask = float(carnet["hl_bid"]), float(carnet["hl_ask"])
    bin_bid, bin_ask = float(carnet["bin_bid"]), float(carnet["bin_ask"])
    hl_mid, bin_mid = (hl_bid + hl_ask) / 2, (bin_bid + bin_ask) / 2
    hl_dspr = float(carnet.get("hl_demi_spread_bps") or 0.0)
    bin_dspr = float(carnet.get("bin_demi_spread_bps") or 0.0)
    prof = float(carnet.get("taille_min_usd") or 0.0)
    ts_ms = float(carnet.get("collecte_ts") or 0.0) * 1000.0
    hl_short = sens >= 0
    hl_px = hl_bid if hl_short else hl_ask                  # short -> on VEND au bid ; long -> on ACHÈTE à l'ask
    bin_px = bin_ask if hl_short else bin_bid               # jambe opposée
    hl_slip = _slippage_bps(notional, prof, hl_dspr)
    bin_slip = _slippage_bps(notional, prof, bin_dspr)
    jambe_hl = {"venue": "HL", "sens": -1 if hl_short else 1, "sens_txt": "SHORT" if hl_short else "LONG",
                "qty": round(notional / hl_mid, 6), "prix_exec": hl_px, "bid": hl_bid, "ask": hl_ask,
                "profondeur_usd": prof, "demi_spread_bps": round(hl_dspr, 3), "frais_bps": FRAIS_TAKER_HL_BPS,
                "slippage_bps": round(hl_slip, 3), "ts_ms": int(ts_ms)}
    jambe_bin = {"venue": "BINANCE", "sens": 1 if hl_short else -1, "sens_txt": "LONG" if hl_short else "SHORT",
                 "qty": round(notional / bin_mid, 6), "prix_exec": bin_px, "bid": bin_bid, "ask": bin_ask,
                 "profondeur_usd": prof, "demi_spread_bps": round(bin_dspr, 3), "frais_bps": FRAIS_TAKER_BIN_BPS,
                 "slippage_bps": round(bin_slip, 3), "ts_ms": int(ts_ms)}
    frais_entree_bps = (hl_dspr + bin_dspr + FRAIS_TAKER_HL_BPS + FRAIS_TAKER_BIN_BPS + hl_slip + bin_slip)
    hedge_ratio = round((jambe_hl["qty"] * hl_mid) / (jambe_bin["qty"] * bin_mid), 4) if bin_mid else 0.0
    return {"jambes": {"hl": jambe_hl, "bin": jambe_bin}, "hedge_ratio": hedge_ratio,
            "frais_entree_reels_bps": round(frais_entree_bps, 3), "cout_sortie_estime_bps": round(frais_entree_bps, 3),
            "profondeur_usd": prof, "liquidite_ok": bool(prof >= notional),
            "hl_mid": hl_mid, "bin_mid": bin_mid, "base_bps": round(1e4 * (hl_mid - bin_mid) / bin_mid, 3) if bin_mid else 0.0}


def decomposer(pos: dict, *, carnet_courant: dict | None, d_courant: float | None,
               base_courant_bps: float | None, now_ms: float) -> dict[str, Any]:
    """Décompose le PnL de la position en postes SÉPARÉS (settled vs accrued, basis, coûts réels)."""
    notional = float(pos.get("notional_usd") or 0.0)
    sens = int(pos.get("sens") or 1)
    d = float(pos.get("d_bps_h") or 0.0)                    # funding net/h signé (à l'entrée)
    ts_ouv = pos.get("ts_ouverture_ms")                     # 🔴 pas de `or now` : ts=0 est falsy -> age=0
    ts_ouv = float(ts_ouv) if ts_ouv is not None else now_ms
    age_h = max(0.0, (now_ms - ts_ouv) / 3.6e6)
    heures_pleines = int(age_h)                             # heures FRANCHIES -> funding réglé
    # frais d'entrée RÉELS (recalculés au carnet, corrige le v1) ; sortie ESTIMÉE au carnet courant
    aud = construire_jambes(pos["coin"], sens, notional, carnet_courant) if carnet_courant else None
    frais_entree_bps = aud["frais_entree_reels_bps"] if aud else float(pos.get("cout_entree_bps") or 0.0) * 2
    cout_sortie_bps = aud["cout_sortie_estime_bps"] if aud else float(pos.get("cout_entree_bps") or 0.0) * 2
    frais_entree_usd = frais_entree_bps / 1e4 * notional
    cout_sortie_usd = cout_sortie_bps / 1e4 * notional
    funding_settled_usd = abs(d) * heures_pleines / 1e4 * notional        # heures pleines = réglé
    funding_accru_usd = abs(d) * (age_h - heures_pleines) / 1e4 * notional  # heure en cours = estimé
    base_ent = float(pos.get("base_entree_bps") or 0.0)
    base_cur = float(base_courant_bps if base_courant_bps is not None else base_ent)
    pnl_basis_usd = -sens * (base_cur - base_ent) / 1e4 * notional         # delta-neutre : dérive de base
    # LIQUIDABLE MAINTENANT : funding réglé + basis − frais entrée payés − coût sortie estimé
    pnl_liquidable = funding_settled_usd + pnl_basis_usd - frais_entree_usd - cout_sortie_usd
    return {"frais_entree_payes_usd": round(frais_entree_usd, 6), "frais_entree_reels_bps": round(frais_entree_bps, 3),
            "cout_sortie_estime_usd": round(cout_sortie_usd, 6),
            "funding_settled_usd": round(funding_settled_usd, 6), "heures_settled": heures_pleines,
            "funding_accru_estime_usd": round(funding_accru_usd, 6),
            "pnl_basis_usd": round(pnl_basis_usd, 6), "base_entree_bps": round(base_ent, 3),
            "base_courant_bps": round(base_cur, 3),
            "pnl_liquidable_maintenant_usd": round(pnl_liquidable, 6),
            "pnl_avec_accru_usd": round(pnl_liquidable + funding_accru_usd, 6),
            "jambes": aud["jambes"] if aud else None, "hedge_ratio": aud["hedge_ratio"] if aud else None,
            "profondeur_usd": aud["profondeur_usd"] if aud else None,
            "liquidite_ok": aud["liquidite_ok"] if aud else None,
            "d_courant_bps_h": round(float(d_courant), 4) if d_courant is not None else None}


__all__ = ["carnet_par_coin", "construire_jambes", "decomposer",
           "FRAIS_TAKER_HL_BPS", "FRAIS_TAKER_BIN_BPS", "CARNET_AGE_MAX_S"]
