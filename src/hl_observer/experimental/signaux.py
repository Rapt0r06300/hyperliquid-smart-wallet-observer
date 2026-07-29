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

from hl_observer.arbitrage.cross_venue_contract import select_executable_direction
from hl_observer.experimental.moteur_paper import LIMITES, Signal
from hl_observer.experimental.roi_estimateur import roi_depuis_signal

#: P8 — fraîcheur des ÉVÉNEMENTS-source (trade Binance / snapshot leader) : au-delà = STALE ; dans le futur = skew.
STALE_SIGNAL_MS = 30_000.0
SKEW_TOL_MS = 2_000.0


def _fraicheur_evenement(
    event_ms, now_ms, *, stale_ms: float = STALE_SIGNAL_MS, skew_ms: float = SKEW_TOL_MS
) -> str | None:
    """P8 — None si l'événement est frais ; sinon le motif : TS_ABSENT / STALE_SIGNAL / CLOCK_SKEW_FUTURE_DATA.
    Le signal doit porter l'horodatage RÉEL de l'événement (pas `now`) pour que ce contrôle ait un sens."""
    if event_ms is None:
        return "TS_ABSENT"
    age = float(now_ms) - float(event_ms)
    if age > stale_ms:
        return "STALE_SIGNAL"
    if age < -skew_ms:
        return "CLOCK_SKEW_FUTURE_DATA"
    return None


# ─────────────────────────────── 1) CROSS-VENUE (survivants gelés) ───────────────────────────────

BASELINE_RELPATH = Path("runtime") / "data" / "cross_venue_juge_baseline.json"
#: frais all-in aller-retour des DEUX jambes perp (approx conservatrice), en plus du spread du carnet.
FRAIS_AR_BPS = 6.6
HOLD_H = 168.0


HOLD_MAX_H = 0.5  # dislocation = COURT TERME (30 min max), JAMAIS 168 h ni funding
SYNCHRO_RELPATH = Path("runtime") / "data" / "bbo_synchro.jsonl"
AGE_MAX_MS_DISLOC = 1000.0  # < 1 s (Flo) : snapshot plus vieux -> périmé
DESYNC_MAX_MS = 250.0  # HL/Binance alignés à moins de ça, sinon skew -> rejet


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
ALLMIDS_AGE_MAX_MS = 60_000.0  # cache allMids > 60 s = plus assez frais -> ignoré


def _allmids(root: str | Path, *, now_ms: float | None = None) -> dict[str, float]:
    """{coin: mid} depuis le cache allMids (tous-coins HL) SI frais (< 60 s). Sinon {}. Rôle : DÉTECTION
    et prix GROSSIER (monitoring) — JAMAIS un prix d'exécution (l'admission exige un L2 frais, cf. signaux_vaults)."""
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


def signaux_cross_venue(
    root: str | Path = ".", *, now_ms: float | None = None
) -> tuple[list[Signal], list[dict]]:
    """CROSS-VENUE COURT TERME (v2b, rectif Flo) : source = flux WS BBO SYNCHRONISÉ (HL bbo + Binance
    bookTicker, horloge MONOTONE). REFUSE tout snapshot > 1 s (`SNAPSHOT_PERIME_1S`) ou désaligné
    (`SKEW_DESALIGNE`). Capture un ÉCART DE PRIX EXÉCUTABLE, entrée/sortie rapide, ZÉRO funding. Frais
    SOURCÉS (config). La v1 carry est en quarantaine — ce moteur ne la lit plus."""
    from hl_observer.experimental.carry_deux_jambes import (
        construire_jambes,
        dimensionner_notional,
        frais_venues,
        LATENCE_MS,
        LATENCE_COUT_BPS,
    )

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
            refus.append(
                {"moteur": "cross_venue", "coin": coin, "motif": "SNAPSHOT_PERIME_1S", "age_ms": round(age)}
            )
            continue
        if desync > DESYNC_MAX_MS:
            refus.append(
                {
                    "moteur": "cross_venue",
                    "coin": coin,
                    "motif": "SKEW_DESALIGNE",
                    "desync_ms": round(desync, 1),
                }
            )
            continue
        hl_bid, hl_ask = float(d["hl_bid"]), float(d["hl_ask"])
        bin_bid, bin_ask = float(d["bin_bid"]), float(d["bin_ask"])
        hl_mid, bin_mid = (hl_bid + hl_ask) / 2, (bin_bid + bin_ask) / 2
        if hl_mid <= 0 or bin_mid <= 0:
            continue
        direction, gap, gap_components = select_executable_direction(
            hl_bid=hl_bid,
            hl_ask=hl_ask,
            binance_bid=bin_bid,
            binance_ask=bin_ask,
        )
        sens = direction.hyperliquid_sens
        depth = float(d.get("taille_top_usd") or 0.0)
        notional = dimensionner_notional(depth, cible)
        if notional <= 0:
            refus.append(
                {
                    "moteur": "cross_venue",
                    "coin": coin,
                    "motif": "LIQUIDITE_INSUFFISANTE",
                    "profondeur_usd": depth,
                }
            )
            continue
        car = {
            "hl_bid": hl_bid,
            "hl_ask": hl_ask,
            "bin_bid": bin_bid,
            "bin_ask": bin_ask,
            "hl_demi_spread_bps": (hl_ask - hl_bid) / 2 / hl_mid * 1e4,
            "bin_demi_spread_bps": (bin_ask - bin_bid) / 2 / bin_mid * 1e4,
            "taille_min_usd": depth,
            "collecte_ts": d.get("collecte_ts") or now / 1000,
        }
        cout_ar = car["hl_demi_spread_bps"] + car["bin_demi_spread_bps"] + 2 * (fhl + fbin) + LATENCE_COUT_BPS
        edge_net = gap - cout_ar
        if edge_net <= 0:
            refus.append(
                {
                    "moteur": "cross_venue",
                    "coin": coin,
                    "motif": "ECART_SOUS_LES_COUTS",
                    "gap_bps": round(gap, 2),
                    "cout_bps": round(cout_ar, 2),
                }
            )
            continue
        aud = construire_jambes(coin, direction, notional, car, frais_hl=fhl, frais_bin=fbin)
        j = aud["jambes"]
        event_ms = now - age  # 🔴 P8 : horodatage RÉEL du snapshot (pas `now`)
        s = Signal(
            moteur="cross_venue",
            coin=coin,
            sens=sens,
            type_pnl="dislocation",
            notional_usd=notional,
            prix_entree=j["hl"]["prix_exec"],
            cout_entree_bps=cout_ar / 2.0,
            edge_estime_bps=round(edge_net, 4),
            pnl_attendu_usd=round(edge_net / 1e4 * notional, 4),
            ts_signal_ms=event_ms,
            frais_bps=fhl + fbin,
            spread_bps=j["hl"]["demi_spread_bps"] + j["bin"]["demi_spread_bps"],
            slippage_bps=j["hl"]["slippage_bps"] + j["bin"]["slippage_bps"],
            latence_ms=LATENCE_MS,
            base_entree_bps=round(gap, 3),
            hold_h=HOLD_MAX_H,
            meta={
                "jambes": j,
                "direction": direction.as_dict(),
                "gap_components": gap_components,
                "hedge_ratio": aud["hedge_ratio"],
                "gap_entree_bps": round(gap, 3),
                "cout_ar_bps": cout_ar,
                "profondeur_usd": depth,
                "desync_ms": round(desync, 1),
            },
        )
        # ROI mesurable seulement si une fréquence d'événements est mesurée ; ici cross-venue n'en fournit pas
        # -> None (la voie experimental_paper admet quand même ; la voie stricte refuserait ROI_NON_MESURABLE).
        s.roi_annuel_pct = roi_depuis_signal(s, freq_evenements_par_jour=None)
        sigs.append(s)
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
            bruts.append(
                {
                    "coin": coin,
                    "gap_brut_bps": round(gap, 2),
                    "cout_bps": round(cout, 2),
                    "net_bps": round(gap - cout, 2),
                    "depth_usd": round(float(d.get("taille_top_usd") or 0.0), 1),
                }
            )
    bruts.sort(key=lambda x: -x["net_bps"])
    q = lambda a, p: sorted(a)[min(len(a) - 1, int(len(a) * p))] if a else 0.0
    return {
        "coins_bbo": len(snaps),
        "coins_frais_1s": fresh,
        "frais_source": src,
        "frais_hl_bps": fhl,
        "frais_bin_bps": fbin,
        "skew_p50_ms": round(st.median(skews), 1) if skews else 0.0,
        "skew_p95_ms": round(q(skews, 0.95), 1),
        "meilleur_net_bps": bruts[0]["net_bps"] if bruts else None,
        "top": bruts[:6],
    }


# ─────────────────────────────── 2) LEAD-LAG (choc Binance → réaction HL) ───────────────────────────────

TAPE_RELPATH = Path("runtime") / "data" / "bbo_tape.jsonl"
CONFIG_GELE_RELPATH = Path("runtime") / "data" / "lead_lag_config_gele.json"


def signaux_lead_lag(
    root: str | Path = ".", *, now_ms: float | None = None, max_lignes: int = 40000
) -> tuple[list[Signal], list[dict]]:
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
    lignes = (
        (root / TAPE_RELPATH).read_text(encoding="utf-8", errors="ignore").splitlines()[-max_lignes:]
        if (root / TAPE_RELPATH).exists()
        else []
    )
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
    freq_jour = cfg.get("freq_evenements_par_jour")  # fréquence MESURÉE causalement (ou None)
    for c, (t_ns, px, side) in dernier_trade.items():
        q = hl_quote.get(c)
        if not q:
            refus.append({"moteur": "lead_lag", "coin": c, "motif": "PAS_DE_QUOTE_HL"})
            continue
        # 🔴 P8 : horodatage RÉEL de l'événement = le trade Binance (recu_ns), PAS `now`. Fraîcheur d'abord.
        event_ms = float(t_ns) / 1e6
        motif_frais = _fraicheur_evenement(event_ms, now)
        if motif_frais:
            refus.append(
                {"moteur": "lead_lag", "coin": c, "motif": motif_frais, "age_ms": round(now - event_ms)}
            )
            continue
        mid = (q["bid"] + q["ask"]) / 2.0  # choc = trade agressif vs mid HL > seuil
        choc_bps = 1e4 * (px - mid) / mid if mid else 0.0
        if abs(choc_bps) < seuil:
            refus.append(
                {"moteur": "lead_lag", "coin": c, "motif": "CHOC_TROP_FAIBLE", "choc_bps": round(choc_bps, 2)}
            )
            continue
        sens = 1 if choc_bps > 0 else -1  # Binance mène : on suit le sens du choc
        prix = q["ask"] if sens > 0 else q["bid"]  # entrée EXÉCUTABLE (on paie le spread)
        demi_spread_bps = 1e4 * (q["ask"] - q["bid"]) / (2 * mid) if mid else 0.0
        edge_net = float(edge_par_h[meilleur_h]) - demi_spread_bps  # edge validé − demi-spread payé
        if edge_net <= 0:
            refus.append({"moteur": "lead_lag", "coin": c, "motif": "EDGE_NEGATIF_APRES_SPREAD"})
            continue
        notional = LIMITES["lead_lag"]["notional_usd"]
        s = Signal(
            moteur="lead_lag",
            coin=c,
            sens=sens,
            type_pnl="directional",
            notional_usd=notional,
            prix_entree=prix,
            cout_entree_bps=demi_spread_bps + frais / 2.0,
            edge_estime_bps=round(edge_net, 4),
            pnl_attendu_usd=round(edge_net / 1e4 * notional, 4),
            ts_signal_ms=event_ms,
            frais_bps=frais / 2.0,
            spread_bps=demi_spread_bps,
            latence_ms=meilleur_h,
            hold_h=float(meilleur_h) / 3_600_000.0,
            meta={"choc_bps": round(choc_bps, 2), "horizon_ms": meilleur_h, "event_ms": event_ms},
        )
        s.roi_annuel_pct = roi_depuis_signal(
            s, freq_evenements_par_jour=freq_jour
        )  # P0 : mesuré si freq connue, sinon None
        sigs.append(s)
    return sigs, refus


# ─────────────────────────────── 3) COPY-VAULTS (changement d'exposition PAR COIN, edge MESURÉ) ───────────────────────────────

VAULTS_SNAP_RELPATH = Path("runtime") / "data" / "vault_snapshots.jsonl"
CARNET_RELPATH = Path("runtime") / "data" / "carnet_venues.jsonl"  # L2 top-of-book HL (bid/ask/profondeur)
COINS_BOUGES_RELPATH = (
    Path("runtime") / "data" / "coins_bouges_par_vaults.json"
)  # abonnement dynamique du carnet
SEUIL_MOVE_FRAC_NAV = 0.05  # le vault doit bouger >= 5 % de son NAV sur UN coin = décision copiable
AGE_L2_MAX_MS = 1000.0  # rectif Flo : un L2 > 1 s est INUTILISABLE pour ADMETTRE (on veut <1 s)
NOTIONAL_MIN_UTILE_USD = 20.0  # sous ce notional dimensionnable par la profondeur : illiquide -> NO_TRADE
SLIPPAGE_BASE_BPS = 1.0  # slippage plancher (traverser le meilleur niveau)
SLIPPAGE_IMPACT_COEF = 8.0  # impact ~ (notional/profondeur) × ce coef (bps) — conservateur


def _positions_par_coin(snap: dict) -> dict[str, tuple[float, float]]:
    """{coin: (szi signé, entryPx)} depuis un snapshot de vault."""
    out: dict[str, tuple[float, float]] = {}
    for p in snap.get("positions") or []:
        c = str(p.get("coin") or "").upper()
        if c:
            out[c] = (float(p.get("szi") or 0.0), float(p.get("entryPx") or 0.0))
    return out


def _carnet_l2_frais(root: Path, *, now_ms: float, age_max_ms: float = AGE_L2_MAX_MS) -> dict[str, dict]:
    """{COIN: dernière ligne de carnet HL FRAÎCHE (< age_max_ms)} depuis carnet_venues.jsonl."""
    p = root / CARNET_RELPATH
    if not p.exists():
        return {}
    out: dict[str, dict] = {}
    for l in p.read_text(encoding="utf-8", errors="ignore").splitlines()[-20000:]:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        c = str(d.get("coin") or "").upper()
        ts = float(d.get("collecte_ts") or 0.0) * 1000.0
        if (
            c
            and float(d.get("hl_bid") or 0) > 0
            and float(d.get("hl_ask") or 0) > 0
            and (now_ms - ts) <= age_max_ms
        ):
            out[c] = d
    return out


def _l2_pour_coin(coin: str, *, lecteur_l2, bbo: dict, carnet: dict, now_ms: float) -> dict | None:
    """L2 HL FRAIS (< 1 s) pour un coin, par ordre de fraîcheur : (1) lecture À LA DEMANDE (WS/REST au
    signal, fournie en live) ; (2) flux BBO synchro (<1 s) ; (3) carnet <1 s. Rend {hl_bid, hl_ask,
    depth_usd, src, age_ms} ou None si aucune source < 1 s (rectif Flo : 120 s était trop vieux)."""
    if lecteur_l2 is not None:
        try:
            d = lecteur_l2(coin)  # lecture on-demand (réseau chez Flo)
        except Exception:  # noqa: BLE001 — le réseau ne doit jamais faire crasher le tick
            d = None
        if d and float(d.get("hl_bid") or 0) > 0 and float(d.get("hl_ask") or 0) > 0:
            return {
                "hl_bid": float(d["hl_bid"]),
                "hl_ask": float(d["hl_ask"]),
                "depth_usd": float(d.get("depth_usd") or d.get("taille_min_usd") or 0.0),
                "src": "on_demand",
                "age_ms": float(d.get("age_ms") or 0.0),
            }
    b = bbo.get(coin)
    if b:
        ts = float(b.get("collecte_ts") or 0.0) * 1000.0
        age = now_ms - ts if ts else 1e9
        if float(b.get("hl_bid") or 0) > 0 and float(b.get("hl_ask") or 0) > 0 and age <= AGE_L2_MAX_MS:
            return {
                "hl_bid": float(b["hl_bid"]),
                "hl_ask": float(b["hl_ask"]),
                "depth_usd": float(b.get("taille_top_usd") or b.get("taille_min_usd") or 0.0),
                "src": "bbo_ws",
                "age_ms": age,
            }
    c = carnet.get(coin)
    if c:
        ts = float(c.get("collecte_ts") or 0.0) * 1000.0
        return {
            "hl_bid": float(c["hl_bid"]),
            "hl_ask": float(c["hl_ask"]),
            "depth_usd": float(c.get("taille_min_usd") or 0.0),
            "src": "carnet",
            "age_ms": now_ms - ts,
        }
    return None


def _filer_coins_au_carnet(root: Path, coins: list[str], *, now_ms: float) -> None:
    """Écrit les coins réellement bougés par les vaults dans coins_bouges_par_vaults.json pour que le
    collecteur de carnet les ABONNE (capture leur L2 frais au prochain tour). Borné, horodaté, atomique."""
    if not coins:
        return
    p = root / COINS_BOUGES_RELPATH
    try:
        cur = json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}
    except (OSError, ValueError):
        cur = {}
    vus = dict(cur.get("coins") or {})
    for c in coins:
        vus[str(c).upper()] = int(now_ms)
    # rétention : on garde les coins vus dans les dernières 6 h (au-delà, le vault a sans doute reфermé)
    vus = {c: t for c, t in vus.items() if now_ms - float(t) <= 6 * 3600 * 1000}
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"maj_ms": int(now_ms), "coins": vus}, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


SCORES_RELPATH = Path("runtime") / "data" / "vaults_scores.json"


def _vaults_retenus(root: Path) -> set[str]:
    """Ensemble des vaults RETENUS par le score 8-facteurs (vaults_scores.json). DENY-BY-DEFAULT
    (rectif Flo 23/07) : pas de fichier / illisible / vide → ensemble VIDE → on ne copie AUCUN vault.
    Le scoring doit avoir tourné et retenu explicitement un vault pour qu'il soit copiable."""
    p = root / SCORES_RELPATH
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(a) for a in (d.get("retenus") or [])}


def signaux_vaults(
    root: str | Path = ".",
    *,
    now_ms: float | None = None,
    lecteur_l2=None,
    edge_par_coin: dict | None = None,
    seuil_move: float = SEUIL_MOVE_FRAC_NAV,
    retenus: set | None = None,
) -> tuple[list[Signal], list[dict]]:
    """Copy-Vaults (rectif Flo 23/07) : détecte le CHANGEMENT D'EXPO PAR COIN (Δszi) d'un vault RETENU
    par le score 8-facteurs (DENY-BY-DEFAULT), ABONNE le coin au carnet, puis N'ADMET QUE si (a) un L2 HL
    FRAIS < 1 s existe sur le coin (lecture on-demand `lecteur_l2` ou BBO WS ; profondeur/VWAP/slippage +
    coût de sortie réels) ET (b) un edge de copie POSITIF sur ce coin. Source de l'edge :
      • STRICT (allocateur) : `edge_par_coin=None` → config MESURÉE et GELÉE (OOS validé) ;
      • EXPLORATOIRE (apprendre) : `edge_par_coin={coin: {edge_brut_bps, horizon_ms}}` → edge PRÉLIMINAIRE
        positif par coin (descriptif, PAS OOS). Jamais inventé, jamais forcé. Sinon NO_TRADE."""
    from hl_observer.experimental.carry_deux_jambes import frais_venues, LATENCE_MS, LATENCE_COUT_BPS
    from hl_observer.experimental.copy_edge_forward import config_gelee

    root = Path(root)
    now = float(now_ms if now_ms is not None else time.time() * 1000)
    refus: list[dict] = []
    exploratoire = edge_par_coin is not None
    if retenus is None:  # override possible (tiers CORE+CHALLENGERS)
        retenus = _vaults_retenus(root)  # DENY-BY-DEFAULT : vide = on ne copie rien
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
    bbo = _snapshots_bbo(root)  # flux WS synchro (<1 s) — L2 d'admission
    carnet = _carnet_l2_frais(root, now_ms=now)  # carnet <1 s (repli)
    cfg_global = None if exploratoire else config_gelee(root)  # STRICT : edge MESURÉ + gelé (sinon NO_TRADE)
    fhl, _fbin, _src = frais_venues(root)
    sigs: list[Signal] = []
    coins_bouges: list[str] = []
    for adr, snaps in par_vault.items():
        if adr not in retenus:
            continue  # non retenu (ou pas encore scoré) -> jamais copié
        if len(snaps) < 2:
            refus.append({"moteur": "copy_vault", "vault": adr[:10], "motif": "MOINS_DE_2_SNAPSHOTS"})
            continue
        snaps.sort(key=lambda s: int(s.get("ts_ms") or 0))
        av, ap = snaps[-2], snaps[-1]
        nav = float(ap.get("nav_usd") or 0.0)
        if nav <= 0:
            refus.append({"moteur": "copy_vault", "vault": adr[:10], "motif": "NAV_NULLE"})
            continue
        p0, p1 = _positions_par_coin(av), _positions_par_coin(ap)
        best_coin, best_dnot, best_dszi = "", 0.0, 0.0
        for c in set(p0) | set(p1):
            dszi = p1.get(c, (0.0, 0.0))[0] - p0.get(c, (0.0, 0.0))[0]
            px_ref = p1.get(c, (0.0, 0.0))[1] or p0.get(c, (0.0, 0.0))[1]
            if abs(dszi) * px_ref > abs(best_dnot):
                best_coin, best_dnot, best_dszi = c, dszi * px_ref, dszi
        move_frac = (abs(best_dnot) / nav) if nav else 0.0
        if not best_coin or move_frac < seuil_move:
            refus.append(
                {
                    "moteur": "copy_vault",
                    "vault": adr[:10],
                    "motif": "CHANGEMENT_TROP_FAIBLE",
                    "coin": best_coin,
                    "move_frac": round(move_frac, 3),
                }
            )
            continue
        coins_bouges.append(best_coin)  # → abonnement dynamique du carnet
        sens = 1 if best_dszi > 0 else -1
        # (b) edge POSITIF obligatoire (jamais inventé) : STRICT = gelé OOS ; EXPLORATOIRE = préliminaire par coin
        if exploratoire:
            cfg = edge_par_coin.get(best_coin)
            if not cfg:
                refus.append(
                    {
                        "moteur": "copy_vault",
                        "vault": adr[:10],
                        "motif": "EDGE_PRELIM_ABSENT",
                        "coin": best_coin,
                        "move_frac": round(move_frac, 3),
                    }
                )
                continue
        else:
            cfg = cfg_global
            if not (cfg and cfg.get("gele")):
                refus.append(
                    {
                        "moteur": "copy_vault",
                        "vault": adr[:10],
                        "motif": "EDGE_NON_MESURE",
                        "coin": best_coin,
                        "move_frac": round(move_frac, 3),
                    }
                )
                continue
        # (a) L2 HL frais < 1 s obligatoire (on-demand ou BBO WS) : prix + profondeur + coût de sortie réels
        l2 = _l2_pour_coin(best_coin, lecteur_l2=lecteur_l2, bbo=bbo, carnet=carnet, now_ms=now)
        if not l2:
            refus.append(
                {"moteur": "copy_vault", "vault": adr[:10], "motif": "L2_INDISPONIBLE_1S", "coin": best_coin}
            )
            continue  # coin déjà filé au carnet pour abonnement
        hl_bid, hl_ask = l2["hl_bid"], l2["hl_ask"]
        mid = (hl_bid + hl_ask) / 2.0
        hl_spread_bps = (hl_ask - hl_bid) / mid * 1e4
        depth_usd = float(l2.get("depth_usd") or 0.0)
        cible = float(LIMITES["copy_vault"]["notional_usd"])
        notional = min(cible, depth_usd)  # VWAP top : on ne prend que ce que la profondeur offre
        if notional < NOTIONAL_MIN_UTILE_USD:
            refus.append(
                {
                    "moteur": "copy_vault",
                    "vault": adr[:10],
                    "motif": "LIQUIDITE_INSUFFISANTE",
                    "coin": best_coin,
                    "depth_usd": round(depth_usd, 1),
                }
            )
            continue
        partiel = notional < cible - 1e-9  # fill PARTIEL : la profondeur ne couvre pas la cible
        slippage_bps = SLIPPAGE_BASE_BPS + SLIPPAGE_IMPACT_COEF * (notional / depth_usd if depth_usd else 1.0)
        prix = hl_ask if sens > 0 else hl_bid  # taker, côté agressif (prix L2 réel)
        cout_ar = 2.0 * fhl + hl_spread_bps + 2.0 * slippage_bps + LATENCE_COUT_BPS  # entrée + SORTIE
        edge_brut = float(cfg.get("edge_brut_bps") or 0.0)  # rendement forward MESURÉ (jamais inventé)
        edge_net = edge_brut - cout_ar
        if edge_net <= 0:
            refus.append(
                {
                    "moteur": "copy_vault",
                    "vault": adr[:10],
                    "motif": "EDGE_NEGATIF_APRES_COUTS",
                    "coin": best_coin,
                    "edge_brut_bps": round(edge_brut, 2),
                    "cout_ar_bps": round(cout_ar, 2),
                }
            )
            continue
        # 🔴 P8 : horodatage RÉEL = le snapshot du leader (ap.ts_ms), PAS `now`. Un snapshot trop vieux =
        # copie tardive sans edge -> STALE_SIGNAL (le délai est honnêtement mesuré, jamais masqué).
        snap_ts = float(ap.get("ts_ms") or 0.0)
        lag_ms = max(0.0, now - snap_ts)  # DÉLAI DE DÉTECTION/copie (snapshot vault cadencé)
        motif_frais = _fraicheur_evenement(snap_ts or None, now)
        if motif_frais:
            refus.append(
                {
                    "moteur": "copy_vault",
                    "vault": adr[:10],
                    "coin": best_coin,
                    "motif": motif_frais,
                    "age_ms": round(lag_ms),
                }
            )
            continue
        s = Signal(
            moteur="copy_vault",
            coin=best_coin,
            sens=sens,
            type_pnl="directional",
            notional_usd=round(notional, 2),
            prix_entree=prix,
            cout_entree_bps=round(cout_ar / 2.0, 4),
            edge_estime_bps=round(edge_net, 4),
            pnl_attendu_usd=round(edge_net / 1e4 * notional, 4),
            ts_signal_ms=snap_ts,
            frais_bps=fhl,
            spread_bps=round(hl_spread_bps, 4),
            slippage_bps=round(slippage_bps, 4),
            latence_ms=LATENCE_MS,
            hold_h=max(1e-6, float(cfg.get("horizon_ms") or 0.0) / 3_600_000.0),
            meta={
                "vault": adr,
                "coin": best_coin,
                "move_frac": round(move_frac, 3),
                "src_prix": l2["src"],
                "snapshot_ts_ms": snap_ts,
                "snapshot_id": ap.get("snapshot_id"),
                "l2_age_ms": round(float(l2.get("age_ms") or 0.0)),
                "depth_usd": round(depth_usd, 1),
                "fill_partiel": partiel,
                "cible_notional_usd": round(cible, 2),
                "slippage_bps": round(slippage_bps, 3),
                "delai_detection_ms": round(lag_ms),
                "edge_brut_mesure_bps": round(edge_brut, 3),
                "cout_ar_bps": round(cout_ar, 3),
                "horizon_mesure_ms": cfg.get("horizon_ms"),
                "stop_bps": cfg.get("stop_bps"),
                "take_profit_bps": cfg.get("take_profit_bps"),  # risque calibré MAE/MFE
                "szi_avant": round(p0.get(best_coin, (0.0, 0.0))[0], 6),
                "szi_apres": round(p1.get(best_coin, (0.0, 0.0))[0], 6),
                "note": "edge MESURÉ (config gelée) − coût L2 RÉEL (spread+2×slippage+frais A/R) ; prix/profondeur "
                "= L2 <1 s (%s) ; allMids sert seulement à détecter" % l2["src"],
            },
        )
        s.roi_annuel_pct = roi_depuis_signal(
            s,
            freq_evenements_par_jour=cfg.get("freq_evenements_par_jour"),
            fill_rate=(1.0 if not partiel else notional / max(cible, 1e-9)),
        )
        sigs.append(s)
    _filer_coins_au_carnet(root, coins_bouges, now_ms=now)  # abonne le carnet aux coins réellement bougés
    return sigs, refus


COLLECTEURS = {"cross_venue": signaux_cross_venue, "lead_lag": signaux_lead_lag, "copy_vault": signaux_vaults}

__all__ = ["signaux_cross_venue", "signaux_lead_lag", "signaux_vaults", "COLLECTEURS"]
