"""EDGE DE COPIE MESURÉ (rectif Flo 23/07) — on ne FIXE jamais l'edge, on le MESURE.

PRINCIPE
--------
Copier un vault n'a d'edge que si, APRÈS qu'il a changé son exposition sur un coin, le prix de ce coin
part RÉELLEMENT dans le sens du changement — assez pour battre les coûts ET un placebo (le même coin,
la même direction, mais à un instant ALÉATOIRE, pour neutraliser la dérive du coin). Ce module :

  1. détecte les ÉVÉNEMENTS de changement d'expo (Δszi par coin) dans l'historique des snapshots ;
  2. mesure le rendement FORWARD du coin dans le sens du move, sur plusieurs horizons, net de coûts ;
  3. compare au PLACEBO (mêmes coins/directions, instants aléatoires) ;
  4. refuse de conclure si trop peu d'événements (NEED_MORE_DATA) — jamais un edge sorti de rien.

C'est l'exact pendant de `lead_lag_shadow` pour la copie. Aucune exécution : lecture d'historique.
"""
from __future__ import annotations

import bisect
import json
import random
from pathlib import Path
from typing import Any

VAULTS_SNAP_RELPATH = Path("runtime") / "data" / "vault_snapshots.jsonl"
PRIX_TAPE_RELPATH = Path("runtime") / "data" / "hl_allmids_tape.jsonl"
CONFIG_GELE_RELPATH = Path("runtime") / "data" / "copy_edge_config_gele.json"

SEUIL_MOVE_FRAC_NAV = 0.05         # même seuil que le signal : un move < 5 % du NAV n'est pas une décision
HORIZONS_MS = (60_000.0, 300_000.0, 900_000.0, 3_600_000.0)   # 1 min, 5 min, 15 min, 1 h
TOL_LOOKUP_MS = 90_000.0          # on n'apparie un prix que si un point de tape est à < 90 s de la cible
FRAIS_SLIPPAGE_BPS = 12.0         # coût A/R conservateur (2× taker HL + spread alt + latence) — voir signaux
MIN_EVENTS = 30                   # en-dessous : NEED_MORE_DATA (comme le lead-lag)


# ─────────────────────────────── chargement ───────────────────────────────

def charger_evenements(root: str | Path, *, seuil: float = SEUIL_MOVE_FRAC_NAV) -> list[dict]:
    """Événements de changement d'expo PAR COIN : {ts_ms, vault, coin, direction, move_frac}.
    Direction = signe(Δszi). Un seul événement (le plus gros coin) par transition de snapshot."""
    from hl_observer.experimental.signaux import _positions_par_coin  # réutilise la même lecture
    p = Path(root) / VAULTS_SNAP_RELPATH
    try:
        lignes = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    par_vault: dict[str, list[dict]] = {}
    for l in lignes:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        a = str(d.get("vault") or "")
        if a:
            par_vault.setdefault(a, []).append(d)
    ev: list[dict] = []
    for adr, snaps in par_vault.items():
        snaps.sort(key=lambda s: int(s.get("ts_ms") or 0))
        for av, ap in zip(snaps, snaps[1:]):
            nav = float(ap.get("nav_usd") or 0.0)
            if nav <= 0:
                continue
            p0, p1 = _positions_par_coin(av), _positions_par_coin(ap)
            best_c, best_dnot, best_dszi = "", 0.0, 0.0
            for c in set(p0) | set(p1):
                dszi = p1.get(c, (0.0, 0.0))[0] - p0.get(c, (0.0, 0.0))[0]
                px = p1.get(c, (0.0, 0.0))[1] or p0.get(c, (0.0, 0.0))[1]
                if abs(dszi) * px > abs(best_dnot):
                    best_c, best_dnot, best_dszi = c, dszi * px, dszi
            move_frac = abs(best_dnot) / nav
            if best_c and move_frac >= seuil:
                ev.append({"ts_ms": int(ap.get("ts_ms") or 0), "vault": adr, "coin": best_c,
                           "direction": 1 if best_dszi > 0 else -1, "move_frac": round(move_frac, 4)})
    return ev


def charger_prix_tape(root: str | Path) -> dict[str, list[tuple[int, float]]]:
    """{coin: [(ts_ms, px)] trié} depuis la tape allMids historique. ⚠️ Cette tape commence AUJOURD'HUI
    (le collecteur allMids vient d'être créé) : pour la RECHERCHE historique, préférer
    `charger_prix_tape_candles` (candleSnapshot backfillé, remonte loin). L'allMids reste utile pour un
    contrôle récent."""
    p = Path(root) / PRIX_TAPE_RELPATH
    try:
        lignes = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return {}
    tape: dict[str, list[tuple[int, float]]] = {}
    for l in lignes:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        ts = int(d.get("ts_ms") or 0)
        for c, px in (d.get("mids") or {}).items():
            try:
                tape.setdefault(str(c).upper(), []).append((ts, float(px)))
            except (TypeError, ValueError):
                continue
    for c in tape:
        tape[c].sort()
    return tape


CANDLES_HISTORY_DIR = Path("runtime") / "history"


def charger_prix_tape_candles(root: str | Path, *, intervalle: str = "1m") -> dict[str, list[tuple[int, float]]]:
    """{coin: [(t_ms, close)] trié} depuis les candles BACKFILLÉES (`runtime/history/candles_<i>.jsonl`).
    C'EST LA MATIÈRE DE LA RECHERCHE HISTORIQUE — séparée du forward exécutable (rectif Flo 23/07) :
    ici on ne mesure QUE l'historique ; le forward temps réel utilise le L2 local < 1 s, jamais ceci."""
    p = Path(root) / CANDLES_HISTORY_DIR / ("candles_%s.jsonl" % intervalle)
    try:
        lignes = p.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return {}
    tape: dict[str, list[tuple[int, float]]] = {}
    for l in lignes:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        try:
            c = str(d.get("coin") or "").upper()
            t = int(d.get("t_ms"))
            px = float(d.get("c"))
        except (TypeError, ValueError):
            continue
        if c and px > 0:
            tape.setdefault(c, []).append((t, px))
    for c in tape:
        tape[c].sort()
    return tape


# ─────────────────────────────── mesure ───────────────────────────────

def _prix_a(serie: list[tuple[int, float]], cible_ms: int, *, tol_ms: float = TOL_LOOKUP_MS) -> float | None:
    """Prix au plus proche de `cible_ms` dans la série, si un point est à < tol_ms. Sinon None."""
    if not serie:
        return None
    ts = [t for t, _ in serie]
    i = bisect.bisect_left(ts, cible_ms)
    best: tuple[float, float] | None = None
    for j in (i - 1, i):
        if 0 <= j < len(serie):
            dt = abs(serie[j][0] - cible_ms)
            if dt <= tol_ms and (best is None or dt < best[0]):
                best = (dt, serie[j][1])
    return best[1] if best else None


def rendement_forward(ev: dict, serie: list[tuple[int, float]], horizon_ms: float) -> float | None:
    """Rendement forward (bps) du coin dans le SENS du changement, entre ts et ts+horizon. None si
    un des deux prix est inintrouvable (trou de tape) — jamais extrapolé."""
    p0 = _prix_a(serie, ev["ts_ms"])
    p1 = _prix_a(serie, int(ev["ts_ms"] + horizon_ms))
    if p0 is None or p1 is None or p0 <= 0:
        return None
    return ev["direction"] * (p1 - p0) / p0 * 1e4


def _placebo_forward(ev: dict, serie: list[tuple[int, float]], horizon_ms: float,
                     rng: random.Random) -> float | None:
    """Même coin/direction mais à un instant ALÉATOIRE de la tape (neutralise la dérive du coin)."""
    if len(serie) < 3:
        return None
    t0 = serie[rng.randrange(len(serie))][0]
    faux = {"ts_ms": t0, "direction": ev["direction"]}
    return rendement_forward(faux, serie, horizon_ms)


def mesurer(root: str | Path, *, horizons_ms=HORIZONS_MS, seuil: float = SEUIL_MOVE_FRAC_NAV,
            frais_bps: float = FRAIS_SLIPPAGE_BPS, min_events: int = MIN_EVENTS,
            graine: int = 12345) -> dict[str, Any]:
    """Mesure l'edge NET de copie par horizon + placebo. Rend un verdict honnête (NEED_MORE_DATA si
    trop peu d'événements appariables). Ne conclut JAMAIS un edge positif sans battre le placebo."""
    ev = charger_evenements(root, seuil=seuil)
    tape = charger_prix_tape(root)
    rng = random.Random(graine)
    par_h: dict[str, dict[str, Any]] = {}
    n_appariables_max = 0
    for h in horizons_ms:
        reels, placebos = [], []
        for e in ev:
            serie = tape.get(e["coin"])
            if not serie:
                continue
            r = rendement_forward(e, serie, h)
            if r is not None:
                reels.append(r)
                pb = _placebo_forward(e, serie, h, rng)
                if pb is not None:
                    placebos.append(pb)
        n = len(reels)
        n_appariables_max = max(n_appariables_max, n)
        if n:
            brut = sum(reels) / n
            net = brut - frais_bps
            pb_moy = (sum(placebos) / len(placebos)) if placebos else 0.0
            par_h["%d" % int(h)] = {"n": n, "brut_bps": round(brut, 3), "net_bps": round(net, 3),
                                    "placebo_bps": round(pb_moy, 3), "edge_vs_placebo_bps": round(brut - pb_moy, 3),
                                    "bat_placebo_et_couts": bool(net > 0 and (brut - pb_moy) > 0)}
    statut = "MESURE" if n_appariables_max >= min_events else "NEED_MORE_DATA"
    meilleur = max((v for v in par_h.values()), key=lambda v: v["net_bps"], default=None)
    return {"statut": statut, "n_evenements": len(ev), "n_appariables_max": n_appariables_max,
            "min_events": min_events, "seuil_move_frac": seuil, "frais_bps": frais_bps,
            "par_horizon": par_h, "meilleur_horizon": meilleur,
            "note": "Edge MESURÉ sur l'historique forward, jamais fixé. Un edge n'est retenu que si "
                    "net_bps>0 ET edge_vs_placebo_bps>0 sur un horizon, puis validé en forward paper."}


# ─────────────────────────────── gel de config validée ───────────────────────────────

def geler(root: str | Path, horizon_ms: float, edge_brut_bps: float, *, edge_net_mesure_bps: float | None = None,
          source: str = "mesure") -> dict:
    """Gèle la config de copie VALIDÉE. On stocke l'edge BRUT (rendement forward mesuré) : le signal
    recalculera le NET avec le coût L2 RÉEL au moment d'ouvrir (pas de double-comptage des coûts)."""
    cfg = {"horizon_ms": float(horizon_ms), "edge_brut_bps": float(edge_brut_bps),
           "edge_net_mesure_bps": edge_net_mesure_bps, "source": source, "gele": True,
           "note": "Config copie gelée : edge BRUT mesuré sur forward historique (net recalculé au coût L2 réel), "
                   "à re-valider en forward paper causal."}
    dest = Path(root) / CONFIG_GELE_RELPATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    return cfg


def config_gelee(root: str | Path) -> dict | None:
    try:
        return json.loads((Path(root) / CONFIG_GELE_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


__all__ = ["charger_evenements", "charger_prix_tape", "rendement_forward", "mesurer", "geler", "config_gelee"]
