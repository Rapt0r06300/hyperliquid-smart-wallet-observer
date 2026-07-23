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
SYNCHRO_RELPATH = Path("runtime") / "data" / "bbo_synchro.jsonl"
AGE_MAX_MS_DISLOC = 1000.0          # < 1 s (Flo) : snapshot plus vieux -> périmé
DESYNC_MAX_MS = 250.0               # HL/Binance alignés à moins de ça, sinon skew -> rejet


def _snapshots_bbo(root: str | Path, *, max_lignes: int = 20000) -> dict[str, dict]:
    """{coin: dernier snapshot SYNCHRONISÉ (flux WS bbo, horloge monotone)} : hl/bin bid/ask, profondeur
    top-of-book, âges monotones, desync (skew). C'est la source TEMPS RÉEL du cross-venue court terme."""
    p = Path(root) / SYNCHRO_RELPATH
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


ALLMIDS_RELPATH = Path("runtime") / "data" / "hl_allmids.json"
ALLMIDS_AGE_MAX_MS = 60_000.0        # cache allMids > 60 s = plus assez frais pour entrer -> ignoré
SPREAD_ESTIME_ALT_BPS = 6.0          # demi-spread conservateur pour un alt hors-BBO (pas de carnet) -> coût réaliste


def _allmids(root: str | Path, *, now_ms: float | None = None) -> dict[str, float]:
    """{coin: mid} depuis le cache allMids (tous-coins HL) SI le cache est frais (< 60 s). Sinon {}.
    C'est le prix HL exécutable de repli pour les ~92 coins que le flux BBO (8 coins) ne couvre pas."""
    p = Path(root) / ALLMIDS_RELPATH
    if not p.exists():
        return {}
    try:
        d = json.loads(p.read_text(encoding="utf-8", errors="ignore"))
    except (OSError, ValueError):
        return {}
    now = float(now_ms if now_ms is not None else time.time() * 1000)
    if now - float(d.get("ts_ms") or 0) > ALLMIDS_AGE_MAX_MS:
        return {}
    mids = d.get("mids") or {}
    return {str(c).upper(): float(v) for c, v in mids.items() if _positif(v)}


def _positif(v: Any) -> bool:
    try:
        return float(v) > 0
    except (TypeError, ValueError):
        return False


def signaux_cross_venue(root: str | Path = ".", *, now_ms: float | None = None) -> tuple[list[Signal], list[dict]]:
    """CROSS-VENUE COURT TERME (v2b, rectif Flo) : source = flux WS BBO SYNCHRONISÉ (HL bbo + Binance
    bookTicker, horloge MONOTONE). REFUSE tout snapshot > 1 s (`SNAPSHOT_PERIME_1S`) ou désaligné
    (`SKEW_DESALIGNE`). Capture un ÉCART DE PRIX EXÉCUTABLE, entrée/sortie rapide, ZÉRO funding. Frais
    SOURCÉS (config). La v1 carry est en quarantaine — ce moteur ne la lit plus."""
    from hl_observer.experimental.carry_deux_jambes import (
        construire_jambes, dimensionner_notional, frais_venues, LATENCE_MS, LATENCE_COUT_BPS)
    root = Path(root)
    now = float(now_ms if now_ms is not None else time.time() * 1000)
    sigs: list[Signal] = []
    refus: list[dict] = []
    snaps = _snapshots_bbo(root)
    if not snaps:
        return sigs, [{"moteur": "cross_venue", "motif": "BBO_ABSENT"}]
    fhl, fbin, _src = frais_venues(root)
    cible = LIMITES["cross_venue"]["notional_usd"]
    for coin, d in snaps.items():
        age = max(float(d.get("age_hl_ms") or 1e9), float(d.get("age_bin_ms") or 1e9))
        desync = float(d.get("desync_ms") or 1e9)
        if age > AGE_MAX_MS_DISLOC:
            refus.append({"moteur": "cross_venue", "coin": coin, "motif": "SNAPSHOT_PERIME_1S", "age_ms": round(age)}); continue
        if desync > DESYNC_MAX_MS:
            refus.append({"moteur": "cross_venue", "coin": coin, "motif": "SKEW_DESALIGNE", "desync_ms": round(desync, 1)}); continue
        hl_bid, hl_ask = float(d["hl_bid"]), float(d["hl_ask"])
        bin_bid, bin_ask = float(d["bin_bid"]), float(d["bin_ask"])
        hl_mid, bin_mid = (hl_bid + hl_ask) / 2, (bin_bid + bin_ask) / 2
        if hl_mid <= 0 or bin_mid <= 0:
            continue
        gap = max((bin_bid - hl_ask) / hl_mid * 1e4, (hl_bid - bin_ask) / bin_mid * 1e4)   # écart EXÉCUTABLE
        sens = 1 if (bin_bid - hl_ask) / hl_mid >= (hl_bid - bin_ask) / bin_mid else -1
        depth = float(d.get("taille_top_usd") or 0.0)
        notional = dimensionner_notional(depth, cible)
        if notional <= 0:
            refus.append({"moteur": "cross_venue", "coin": coin, "motif": "LIQUIDITE_INSUFFISANTE", "profondeur_usd": depth}); continue
        car = {"hl_bid": hl_bid, "hl_ask": hl_ask, "bin_bid": bin_bid, "bin_ask": bin_ask,
               "hl_demi_spread_bps": (hl_ask - hl_bid) / 2 / hl_mid * 1e4,
               "bin_demi_spread_bps": (bin_ask - bin_bid) / 2 / bin_mid * 1e4,
               "taille_min_usd": depth, "collecte_ts": d.get("collecte_ts") or now / 1000}
        cout_ar = (car["hl_demi_spread_bps"] + car["bin_demi_spread_bps"] + 2 * (fhl + fbin) + LATENCE_COUT_BPS)
        edge_net = gap - cout_ar
        if edge_net <= 0:
            refus.append({"moteur": "cross_venue", "coin": coin, "motif": "ECART_SOUS_LES_COUTS",
                          "gap_bps": round(gap, 2), "cout_bps": round(cout_ar, 2)}); continue
        aud = construire_jambes(coin, sens, notional, car, frais_hl=fhl, frais_bin=fbin)
        j = aud["jambes"]
        sigs.append(Signal(
            moteur="cross_venue", coin=coin, sens=sens, type_pnl="dislocation", notional_usd=notional,
            prix_entree=j["hl"]["prix_exec"], cout_entree_bps=cout_ar / 2.0, edge_estime_bps=round(edge_net, 4),
            pnl_attendu_usd=round(edge_net / 1e4 * notional, 4), ts_signal_ms=now, frais_bps=fhl + fbin,
            spread_bps=j["hl"]["demi_spread_bps"] + j["bin"]["demi_spread_bps"],
            slippage_bps=j["hl"]["slippage_bps"] + j["bin"]["slippage_bps"], latence_ms=LATENCE_MS,
            base_entree_bps=round(gap, 3), hold_h=HOLD_MAX_H,
            meta={"jambes": j, "hedge_ratio": aud["hedge_ratio"], "gap_entree_bps": round(gap, 3),
                  "cout_ar_bps": cout_ar, "profondeur_usd": depth, "desync_ms": round(desync, 1)}))
    return sigs, refus


def metriques_cross_venue(root: str | Path = ".") -> dict[str, Any]:
    """Preuve runtime (Flo) : couverture FRAÎCHE (<1 s), skew p50/p95, écarts BRUTS vs coûts, par tick."""
    import statistics as st
    from hl_observer.experimental.carry_deux_jambes import frais_venues, LATENCE_COUT_BPS
    snaps = _snapshots_bbo(root)
    fhl, fbin, src = frais_venues(root)
    fresh, skews, bruts = 0, [], []
    for coin, d in snaps.items():
        age = max(float(d.get("age_hl_ms") or 1e9), float(d.get("age_bin_ms") or 1e9))
        skews.append(float(d.get("desync_ms") or 0.0))
        if age > AGE_MAX_MS_DISLOC:
            continue
        fresh += 1
        hl_bid, hl_ask = float(d["hl_bid"]), float(d["hl_ask"])
        bin_bid, bin_ask = float(d["bin_bid"]), float(d["bin_ask"])
        hl_mid, bin_mid = (hl_bid + hl_ask) / 2, (bin_bid + bin_ask) / 2
        if hl_mid > 0 and bin_mid > 0:
            gap = max((bin_bid - hl_ask) / hl_mid * 1e4, (hl_bid - bin_ask) / bin_mid * 1e4)
            spread = (hl_ask - hl_bid) / 2 / hl_mid * 1e4 + (bin_ask - bin_bid) / 2 / bin_mid * 1e4
            cout = spread + 2 * (fhl + fbin) + LATENCE_COUT_BPS
            bruts.append({"coin": coin, "gap_brut_bps": round(gap, 2), "cout_bps": round(cout, 2),
                          "net_bps": round(gap - cout, 2), "depth_usd": round(float(d.get("taille_top_usd") or 0.0), 1)})
    bruts.sort(key=lambda x: -x["net_bps"])
    q = lambda a, p: (sorted(a)[min(len(a) - 1, int(len(a) * p))] if a else 0.0)
    return {"coins_bbo": len(snaps), "coins_frais_1s": fresh, "frais_source": src, "frais_hl_bps": fhl, "frais_bin_bps": fbin,
            "skew_p50_ms": round(st.median(skews), 1) if skews else 0.0, "skew_p95_ms": round(q(skews, 0.95), 1),
            "meilleur_net_bps": bruts[0]["net_bps"] if bruts else None, "top": bruts[:6]}


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


# ─────────────────────────────── 3) COPY-VAULTS (changement d'exposition PAR COIN réplicable) ───────────────────────────────

VAULTS_SNAP_RELPATH = Path("runtime") / "data" / "vault_snapshots.jsonl"
SEUIL_MOVE_FRAC_NAV = 0.05           # le vault doit bouger >= 5 % de son NAV sur UN coin = décision copiable
K_CONVICTION = 0.03                  # proxy conviction : 5 % de NAV bougé -> 15 bps d'edge brut (le forward MESURE le vrai)
PLAFOND_EDGE_COPY_BPS = 60.0         # on ne SURVEND jamais un edge de copie (incertain par nature)


def _positions_par_coin(snap: dict) -> dict[str, tuple[float, float]]:
    """{coin: (szi signé, entryPx)} depuis un snapshot de vault."""
    out: dict[str, tuple[float, float]] = {}
    for p in (snap.get("positions") or []):
        c = str(p.get("coin") or "").upper()
        if c:
            out[c] = (float(p.get("szi") or 0.0), float(p.get("entryPx") or 0.0))
    return out


def signaux_vaults(root: str | Path = ".", *, now_ms: float | None = None) -> tuple[list[Signal], list[dict]]:
    """Copy-Vaults : détecte le CHANGEMENT D'EXPOSITION PAR COIN (Δszi entre 2 snapshots) chez un vault
    suivi performant, et le mirroir au prix HL RÉELLEMENT EXÉCUTABLE (BBO synchro). Le coin doit être
    couvert par le flux BBO (sinon pas de prix exécutable frais → refus honnête). Sans 2 snapshots,
    sans changement significatif, ou coin non exécutable : rien. Le forward MESURE le vrai PnL de copie."""
    from hl_observer.experimental.carry_deux_jambes import frais_venues, LATENCE_MS, LATENCE_COUT_BPS
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
        a = str(d.get("vault") or d.get("adresse") or d.get("address") or "")
        if a:
            par_vault.setdefault(a, []).append(d)
    bbo = _snapshots_bbo(root)                                     # {COIN: dernier snapshot BBO synchro HL/Binance}
    allmids = _allmids(root, now_ms=now)                           # {COIN: mid HL frais} — repli tous-coins
    fhl, _fbin, _src = frais_venues(root)
    sigs: list[Signal] = []
    for adr, snaps in par_vault.items():
        if len(snaps) < 2:
            refus.append({"moteur": "copy_vault", "vault": adr[:10], "motif": "MOINS_DE_2_SNAPSHOTS"}); continue
        snaps.sort(key=lambda s: int(s.get("ts_ms") or 0))
        av, ap = snaps[-2], snaps[-1]
        nav = float(ap.get("nav_usd") or 0.0)
        if nav <= 0:
            refus.append({"moteur": "copy_vault", "vault": adr[:10], "motif": "NAV_NULLE"}); continue
        p0, p1 = _positions_par_coin(av), _positions_par_coin(ap)
        # plus gros changement d'exposition PAR COIN (Δszi × prix), en fraction du NAV
        best_coin, best_dnot, best_dszi = "", 0.0, 0.0
        for c in set(p0) | set(p1):
            dszi = p1.get(c, (0.0, 0.0))[0] - p0.get(c, (0.0, 0.0))[0]
            px_ref = p1.get(c, (0.0, 0.0))[1] or p0.get(c, (0.0, 0.0))[1]
            dnot = abs(dszi) * px_ref
            if dnot > abs(best_dnot):
                best_coin, best_dnot, best_dszi = c, dnot, dszi
        move_frac = (best_dnot / nav) if nav else 0.0
        if not best_coin or move_frac < SEUIL_MOVE_FRAC_NAV:
            refus.append({"moteur": "copy_vault", "vault": adr[:10], "motif": "CHANGEMENT_TROP_FAIBLE",
                          "coin": best_coin, "move_frac": round(move_frac, 3)}); continue
        sens = 1 if best_dszi > 0 else -1
        # prix HL exécutable : BBO synchro (bid/ask réel, < 1 s) prioritaire, sinon allMids (mid frais + spread estimé)
        b = bbo.get(best_coin)
        if b and float(b.get("hl_bid") or 0.0) > 0 and float(b.get("hl_ask") or 0.0) > 0:
            hl_bid, hl_ask = float(b["hl_bid"]), float(b["hl_ask"])
            mid = (hl_bid + hl_ask) / 2.0
            prix = hl_ask if sens > 0 else hl_bid                  # côté agressif (taker)
            hl_spread_bps = (hl_ask - hl_bid) / mid * 1e4
            src_prix = "bbo"
        elif best_coin in allmids:
            mid = allmids[best_coin]
            hl_spread_bps = SPREAD_ESTIME_ALT_BPS * 2.0            # spread plein estimé (conservateur, pas de carnet)
            prix = mid * (1.0 + SPREAD_ESTIME_ALT_BPS / 1e4) if sens > 0 else mid * (1.0 - SPREAD_ESTIME_ALT_BPS / 1e4)
            src_prix = "allmids"
        else:
            refus.append({"moteur": "copy_vault", "vault": adr[:10], "motif": "PRIX_NON_EXECUTABLE_HL",
                          "coin": best_coin}); continue
        cout_ar = 2.0 * fhl + hl_spread_bps + LATENCE_COUT_BPS     # A/R : 2× taker HL + spread + latence
        edge = min(move_frac * 1e4 * K_CONVICTION, PLAFOND_EDGE_COPY_BPS) - cout_ar
        if edge <= 0:
            refus.append({"moteur": "copy_vault", "vault": adr[:10], "motif": "EDGE_NEGATIF_APRES_COUTS",
                          "coin": best_coin, "move_frac": round(move_frac, 3)}); continue
        notional = LIMITES["copy_vault"]["notional_usd"]
        lag_ms = max(0.0, now - float(ap.get("ts_ms") or now))    # retard d'observation (snapshot vault ~300 s cadencé)
        sigs.append(Signal(
            moteur="copy_vault", coin=best_coin, sens=sens, type_pnl="directional",
            notional_usd=notional, prix_entree=prix, cout_entree_bps=round(cout_ar / 2.0, 4),
            edge_estime_bps=round(edge, 4), pnl_attendu_usd=round(edge / 1e4 * notional, 4),
            ts_signal_ms=now, frais_bps=fhl, spread_bps=round(hl_spread_bps, 4), latence_ms=LATENCE_MS,
            meta={"vault": adr, "coin": best_coin, "move_frac": round(move_frac, 3), "src_prix": src_prix,
                  "observation_lag_ms": round(lag_ms), "szi_avant": round(p0.get(best_coin, (0.0, 0.0))[0], 6),
                  "szi_apres": round(p1.get(best_coin, (0.0, 0.0))[0], 6),
                  "edge_est_note": "proxy conviction (move×K, plafonné) — le forward MESURE le vrai PnL de copie ; "
                                   "entrée au prix HL FRAIS (ts=now), retard d'observation copié dans observation_lag_ms"}))
    return sigs, refus


COLLECTEURS = {"cross_venue": signaux_cross_venue, "lead_lag": signaux_lead_lag, "copy_vault": signaux_vaults}

__all__ = ["signaux_cross_venue", "signaux_lead_lag", "signaux_vaults", "COLLECTEURS"]
