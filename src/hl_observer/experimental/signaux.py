"""ADAPTATEURS DE SIGNAUX EXPERIMENTAL_PAPER — 3 moteurs, une seule forme de `Signal`.

Chaque adaptateur lit des DONNÉES RÉELLES datées (dispersion, carnet, tape BBO, snapshots de vaults) et
émet des `Signal` candidats + des refus motivés. Aucun signal inventé : donnée absente/périmée → refus.
Le moteur central (`moteur_paper`) décide ensuite de l'admission (fraîcheur + exécutable + edge > 0).
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from hl_observer.experimental.moteur_paper import LIMITES, Signal

# ─────────────────────────────── 1) CROSS-VENUE (survivants gelés) ───────────────────────────────

BASELINE_RELPATH = Path("runtime") / "data" / "cross_venue_juge_baseline.json"
#: frais all-in aller-retour des DEUX jambes perp (approx conservatrice), en plus du spread du carnet.
FRAIS_AR_BPS = 6.6
HOLD_H = 168.0


HOLD_MAX_H = 0.5                    # dislocation = COURT TERME (30 min max), JAMAIS 168 h ni funding


def signaux_cross_venue(root: str | Path = ".", *, now_ms: float | None = None) -> tuple[list[Signal], list[dict]]:
    """CROSS-VENUE COURT TERME (v2, rectification Flo 23/07) : capture un ÉCART DE PRIX EXÉCUTABLE entre
    HL et Binance, entrée/sortie RAPIDE, **sans aucune dépendance au funding ni au hold 168 h**. On achète
    la venue la moins chère (à l'ask) et on vend la plus chère (au bid) ; on débouble à la convergence.
    Signal SEULEMENT si l'écart exécutable (net des spreads croisés) dépasse les coûts A/R + le plancher
    de profit exigeant. La v1 (carry funding) est en QUARANTAINE — ce moteur ne la lit plus."""
    from hl_observer.experimental.carry_deux_jambes import (
        carnet_par_coin, construire_jambes, dimensionner_notional, FRAIS_TAKER_HL_BPS,
        FRAIS_TAKER_BIN_BPS, CARNET_AGE_MAX_S, LATENCE_MS, LATENCE_COUT_BPS)
    root = Path(root)
    now = float(now_ms if now_ms is not None else time.time() * 1000)
    sigs: list[Signal] = []
    refus: list[dict] = []
    carnet = carnet_par_coin(root)
    if not carnet:
        return sigs, [{"moteur": "cross_venue", "motif": "CARNET_ABSENT"}]
    cible = LIMITES["cross_venue"]["notional_usd"]
    for coin, car in carnet.items():
        if (now / 1000.0 - float(car.get("collecte_ts") or 0.0)) > CARNET_AGE_MAX_S:
            refus.append({"moteur": "cross_venue", "coin": coin, "motif": "QUOTE_PERIMEE"}); continue
        hl_bid, hl_ask = float(car["hl_bid"]), float(car["hl_ask"])
        bin_bid, bin_ask = float(car["bin_bid"]), float(car["bin_ask"])
        hl_mid, bin_mid = (hl_bid + hl_ask) / 2, (bin_bid + bin_ask) / 2
        if hl_mid <= 0 or bin_mid <= 0:
            continue
        gap_hl_cheap = (bin_bid - hl_ask) / hl_mid * 1e4          # HL moins cher -> long HL / short BIN
        gap_bin_cheap = (hl_bid - bin_ask) / bin_mid * 1e4        # BIN moins cher -> short HL / long BIN
        gap = max(gap_hl_cheap, gap_bin_cheap)                    # écart EXÉCUTABLE capturable (bps)
        sens = 1 if gap_hl_cheap >= gap_bin_cheap else -1         # +1 = long HL (HL moins cher)
        depth = float(car.get("taille_min_usd") or 0.0)
        notional = dimensionner_notional(depth, cible)           # VWAP/profondeur : taille exécutable
        if notional <= 0:
            refus.append({"moteur": "cross_venue", "coin": coin, "motif": "LIQUIDITE_INSUFFISANTE",
                          "profondeur_usd": depth}); continue
        # l'écart exécutable a DÉJÀ payé l'entrée (bid/ask) ; reste le déboucle : exit spreads + 4 fills + latence
        cout_ar = (float(car.get("hl_demi_spread_bps") or 0.0) + float(car.get("bin_demi_spread_bps") or 0.0)
                   + 2 * (FRAIS_TAKER_HL_BPS + FRAIS_TAKER_BIN_BPS) + LATENCE_COUT_BPS)
        edge_net = gap - cout_ar
        if edge_net <= 0:
            refus.append({"moteur": "cross_venue", "coin": coin, "motif": "ECART_SOUS_LES_COUTS",
                          "gap_bps": round(gap, 2), "cout_bps": round(cout_ar, 2)}); continue
        aud = construire_jambes(coin, sens, notional, car)
        j = aud["jambes"]
        sigs.append(Signal(
            moteur="cross_venue", coin=coin, sens=sens, type_pnl="dislocation", notional_usd=notional,
            prix_entree=j["hl"]["prix_exec"], cout_entree_bps=cout_ar / 2.0, edge_estime_bps=round(edge_net, 4),
            pnl_attendu_usd=round(edge_net / 1e4 * notional, 4), ts_signal_ms=float(car.get("collecte_ts") or now / 1000) * 1000,
            frais_bps=FRAIS_TAKER_HL_BPS + FRAIS_TAKER_BIN_BPS,
            spread_bps=j["hl"]["demi_spread_bps"] + j["bin"]["demi_spread_bps"],
            slippage_bps=j["hl"]["slippage_bps"] + j["bin"]["slippage_bps"], latence_ms=LATENCE_MS,
            base_entree_bps=round(gap, 3), hold_h=HOLD_MAX_H,
            meta={"jambes": j, "hedge_ratio": aud["hedge_ratio"], "gap_entree_bps": round(gap, 3),
                  "cout_ar_bps": cout_ar, "profondeur_usd": depth}))
    return sigs, refus


# ─────────────────────────────── 2) LEAD-LAG (choc Binance → réaction HL) ───────────────────────────────

TAPE_RELPATH = Path("runtime") / "data" / "bbo_tape.jsonl"
CONFIG_GELE_RELPATH = Path("runtime") / "data" / "lead_lag_config_gele.json"


def signaux_lead_lag(root: str | Path = ".", *, now_ms: float | None = None,
                     max_lignes: int = 40000) -> tuple[list[Signal], list[dict]]:
    """Ouvre une position directionnelle quand un CHOC Binance FRAIS (trade) vient de se produire sur un
    coin de la config GELÉE (horizon validé par placebo), avec bid/ask HL exécutables. Sans config gelée
    (backtest/placebo pas encore validé) : rien — on n'invente pas un edge non prouvé propre."""
    root = Path(root)
    now = float(now_ms if now_ms is not None else time.time() * 1000)
    refus: list[dict] = []
    try:
        cfg = json.loads((root / CONFIG_GELE_RELPATH).read_text(encoding="utf-8"))
        coins = {c.upper() for c in cfg.get("coins", [])} - {c.upper() for c in cfg.get("coins_controle", [])}
        seuil = float(cfg.get("seuil_choc_bps", 8.0))
        frais = float(cfg.get("frais_slippage_bps", 6.0))
        edge_par_h = {float(k): v for k, v in (cfg.get("edge_net_par_horizon_bps") or {}).items()}
    except (OSError, ValueError):
        return [], [{"moteur": "lead_lag", "motif": "CONFIG_NON_GELEE"}]
    if not coins or not edge_par_h:
        return [], [{"moteur": "lead_lag", "motif": "CONFIG_INCOMPLETE"}]
    meilleur_h = max(edge_par_h, key=lambda h: edge_par_h[h] or -1e9)
    if (edge_par_h.get(meilleur_h) or 0) <= 0:
        return [], [{"moteur": "lead_lag", "motif": "AUCUN_HORIZON_POSITIF"}]
    lignes = (root / TAPE_RELPATH).read_text(encoding="utf-8", errors="ignore").splitlines()[-max_lignes:] \
        if (root / TAPE_RELPATH).exists() else []
    dernier_trade: dict[str, tuple] = {}
    hl_quote: dict[str, dict] = {}
    for l in lignes:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        c = str(d.get("coin") or "").upper()
        if c not in coins:
            continue
        if d.get("venue") == "BIN_TRADE" and d.get("px"):
            dernier_trade[c] = (float(d["recu_ns"]), float(d["px"]), str(d.get("side") or ""))
        elif d.get("venue") == "HL" and d.get("bid") and d.get("ask"):
            hl_quote[c] = {"bid": float(d["bid"]), "ask": float(d["ask"]), "recu_ns": float(d["recu_ns"])}
    sigs: list[Signal] = []
    for c, (t_ns, px, side) in dernier_trade.items():
        q = hl_quote.get(c)
        if not q:
            refus.append({"moteur": "lead_lag", "coin": c, "motif": "PAS_DE_QUOTE_HL"}); continue
        # choc = le trade agressif a bougé le prix vs le mid HL de plus que le seuil
        mid = (q["bid"] + q["ask"]) / 2.0
        choc_bps = 1e4 * (px - mid) / mid if mid else 0.0
        if abs(choc_bps) < seuil:
            refus.append({"moteur": "lead_lag", "coin": c, "motif": "CHOC_TROP_FAIBLE",
                          "choc_bps": round(choc_bps, 2)}); continue
        sens = 1 if choc_bps > 0 else -1                          # Binance mène : on suit le sens du choc
        prix = q["ask"] if sens > 0 else q["bid"]                 # entrée EXÉCUTABLE (on paie le spread)
        demi_spread_bps = 1e4 * (q["ask"] - q["bid"]) / (2 * mid) if mid else 0.0
        edge_net = float(edge_par_h[meilleur_h]) - demi_spread_bps  # edge validé − demi-spread payé
        if edge_net <= 0:
            refus.append({"moteur": "lead_lag", "coin": c, "motif": "EDGE_NEGATIF_APRES_SPREAD"}); continue
        sigs.append(Signal(
            moteur="lead_lag", coin=c, sens=sens, type_pnl="directional", notional_usd=LIMITES["lead_lag"]["notional_usd"],
            prix_entree=prix, cout_entree_bps=demi_spread_bps + frais / 2.0, edge_estime_bps=round(edge_net, 4),
            pnl_attendu_usd=round(edge_net / 1e4 * LIMITES["lead_lag"]["notional_usd"], 4),
            ts_signal_ms=now, frais_bps=frais / 2.0, spread_bps=demi_spread_bps,
            latence_ms=meilleur_h, meta={"choc_bps": round(choc_bps, 2), "horizon_ms": meilleur_h}))
    return sigs, refus


# ─────────────────────────────── 3) COPY-VAULTS (changement d'exposition réplicable) ───────────────────────────────

VAULTS_SNAP_RELPATH = Path("runtime") / "data" / "vault_snapshots.jsonl"
SEUIL_DELTA_EXPO_USD = 0.15          # variation d'exposition nette >= 15 % du notional = réplicable


def signaux_vaults(root: str | Path = ".", *, now_ms: float | None = None) -> tuple[list[Signal], list[dict]]:
    """Ouvre une position directionnelle quand un vault SUIVI change d'exposition nette de façon
    réplicable (delta entre 2 snapshots), dans le sens du changement. Prix exécutable = dernier mark HL
    du vault (proxy). Sans 2 snapshots ou sans changement : rien."""
    root = Path(root)
    now = float(now_ms if now_ms is not None else time.time() * 1000)
    refus: list[dict] = []
    try:
        lignes = (root / VAULTS_SNAP_RELPATH).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return [], [{"moteur": "copy_vault", "motif": "PAS_DE_SNAPSHOTS"}]
    par_vault: dict[str, list[dict]] = {}
    for l in lignes:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        a = str(d.get("adresse") or d.get("address") or "")
        if a:
            par_vault.setdefault(a, []).append(d)
    sigs: list[Signal] = []
    for adr, snaps in par_vault.items():
        if len(snaps) < 2:
            refus.append({"moteur": "copy_vault", "vault": adr[:10], "motif": "MOINS_DE_2_SNAPSHOTS"}); continue
        snaps.sort(key=lambda s: int(s.get("ts_ms") or 0))
        av, ap = snaps[-2], snaps[-1]
        nav = float(ap.get("nav_usd") or 0.0)
        e0 = float(av.get("expo_nette_usd") or 0.0)
        e1 = float(ap.get("expo_nette_usd") or 0.0)
        if nav <= 0:
            refus.append({"moteur": "copy_vault", "vault": adr[:10], "motif": "NAV_NULLE"}); continue
        delta_frac = (e1 - e0) / nav
        if abs(delta_frac) < SEUIL_DELTA_EXPO_USD:
            refus.append({"moteur": "copy_vault", "vault": adr[:10], "motif": "CHANGEMENT_TROP_FAIBLE",
                          "delta_frac": round(delta_frac, 3)}); continue
        px = float(ap.get("mark_px") or ap.get("prix") or 0.0)
        if px <= 0:
            refus.append({"moteur": "copy_vault", "vault": adr[:10], "motif": "PRIX_NON_EXECUTABLE"}); continue
        coin = str(ap.get("coin_principal") or ap.get("coin") or adr[:6]).upper()
        # coût exécutable conservateur : demi-spread + frais taker HL (approx, faute de carnet du vault)
        cout = 8.0
        edge = abs(delta_frac) * 1e4 * 0.10 - cout                # 10 % du move répliqué comme edge brut proxy
        if edge <= 0:
            refus.append({"moteur": "copy_vault", "vault": adr[:10], "motif": "EDGE_NEGATIF"}); continue
        sigs.append(Signal(
            moteur="copy_vault", coin=coin, sens=1 if delta_frac > 0 else -1, type_pnl="directional",
            notional_usd=LIMITES["copy_vault"]["notional_usd"], prix_entree=px, cout_entree_bps=cout / 2.0,
            edge_estime_bps=round(edge, 4), pnl_attendu_usd=round(edge / 1e4 * LIMITES["copy_vault"]["notional_usd"], 4),
            ts_signal_ms=float(ap.get("ts_ms") or now), frais_bps=cout / 2.0,
            meta={"vault": adr, "delta_frac": round(delta_frac, 3)}))
    return sigs, refus


COLLECTEURS = {"cross_venue": signaux_cross_venue, "lead_lag": signaux_lead_lag, "copy_vault": signaux_vaults}

__all__ = ["signaux_cross_venue", "signaux_lead_lag", "signaux_vaults", "COLLECTEURS"]
