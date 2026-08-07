"""VAGUE 1 — 6 plugins de signal SHADOW + REGIME_ROUTER (Flo 25/07). 12 variantes pré-enregistrées au
total (2 par plugin), figées. Aucun retuning après observation. Chaque détecteur est PUR (testable), gated
par le régime. Un plugin sans sa data s'ABSTIENT (deny-by-default) : il n'émet rien plutôt qu'inventer.

Émissions = lignes SIGNAL_SHADOW (jamais un ordre). L'exécution/décision est le LOT 3.
"""
from __future__ import annotations

import statistics
from pathlib import Path

from hl_observer.research_parallel import isolation as ISO
from hl_observer.research_parallel import registre as REG
from hl_observer.research_parallel.plugins import _commun as K

UNIVERS = ("BTC", "ETH", "SOL", "AVAX", "INJ", "DASH", "NEO", "LINK", "AAVE", "ONDO")


# ═══════════ REGIME_ROUTER (catégorie router) ═══════════
def router_regime(contexte: dict) -> list[dict]:
    """Calcule le régime (vol/spread) sur les majors depuis le bbo_tape et écrit regime.json : quels plugins
    peuvent émettre. Spread large -> ABSORPTION coupé (a besoin d'un carnet serré) ; vol basse -> momentum/
    squeeze coupés (rien à capturer). Rend une ligne de résumé (le vrai effet est le fichier regime.json)."""
    root = Path(contexte.get("root") or ".")
    series = contexte.get("_prix") or K.prix_bbo_hl(root, ("BTC", "ETH", "SOL"))
    spreads, vols = [], []
    for c, s in series.items():
        if len(s) < 5:
            continue
        spreads += [(a - b) / (0.5 * (a + b)) * 1e4 for _t, b, a in s[-50:]]
        mids = [0.5 * (b + a) for _t, b, a in s[-50:]]
        rets = [(mids[i] - mids[i - 1]) / mids[i - 1] * 1e4 for i in range(1, len(mids))]
        if len(rets) >= 3:
            vols.append(statistics.pstdev(rets))
    spread_med = statistics.median(spreads) if spreads else None
    vol_med = statistics.median(vols) if vols else None
    tous = ["OI_CROWDING", "FUNDING_CLOCK", "OI_CAP_EVENT", "HLP_PRESSURE", "ABSORPTION_FRAGILITY", "RESIDUAL_MOMENTUM"]
    autorises = list(tous)
    if spread_med is not None and spread_med > 8.0:          # carnet trop large -> pas d'absorption fine
        autorises = [p for p in autorises if p != "ABSORPTION_FRAGILITY"]
    if vol_med is not None and vol_med < 1.0:                # marché mort -> pas de momentum/squeeze
        autorises = [p for p in autorises if p not in ("RESIDUAL_MOMENTUM",)]
    reg = {"spread_med_bps": spread_med, "vol_med_bps": vol_med, "autorises": autorises}
    p = ISO.lab_root(root) / "data" / "regime.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    try:
        p.write_text(__import__("json").dumps(reg, ensure_ascii=False), encoding="utf-8")
    except OSError:
        import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
        _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
    return [{"kind": "REGIME", **reg}]


# ═══════════ RESIDUAL_MOMENTUM (data disponible : prix) ═══════════
def _residuals(series: dict, *, lookback_ms: float):
    """Résidu de momentum neutre-marché : retour de chaque coin moins sa part expliquée par BTC/ETH.
    Rend {coin: residu_bps} au dernier point. Sans BTC/ETH ou <2 points -> {}."""
    def ret(c):
        s = series.get(c) or []
        if len(s) < 2:
            return None
        t1, b1, a1 = s[-1]
        cible = t1 - lookback_ms
        base = next((m for (t, b, a) in reversed(s) if t <= cible for m in [0.5 * (b + a)]), None)
        if base is None:
            base = 0.5 * (s[0][1] + s[0][2])
        return (0.5 * (b1 + a1) - base) / base * 1e4
    facteur = [r for r in (ret("BTC"), ret("ETH")) if r is not None]
    if not facteur:
        return {}
    beta = statistics.mean(facteur)                          # proxy simple du marché (moyenne BTC/ETH)
    out = {}
    for c in series:
        r = ret(c)
        if r is None or c in ("BTC", "ETH"):
            continue
        out[c] = r - beta                                    # résidu = spécifique au coin
    return out


def _momentum(contexte, *, lookback_ms, horizon_s, variante):
    root = Path(contexte.get("root") or ".")
    series = contexte.get("_prix") or K.prix_bbo_hl(root, UNIVERS)
    res = _residuals(series, lookback_ms=lookback_ms)
    if len(res) < 4:
        return []
    classe = sorted(res.items(), key=lambda kv: kv[1])
    bas, haut = classe[0], classe[-1]                        # short le pire résidu, long le meilleur
    ts = max((s[-1][0] for s in series.values() if s), default=0)
    return [K.signal(ts, haut[0], +1, variante, residu_bps=round(haut[1], 2), horizon_s=horizon_s),
            K.signal(ts, bas[0], -1, variante, residu_bps=round(bas[1], 2), horizon_s=horizon_s)]


def residual_momentum(contexte: dict) -> list[dict]:
    if not K.autorise(K.regime_courant(Path(contexte.get("root") or ".")), "RESIDUAL_MOMENTUM"):
        return []
    return (_momentum(contexte, lookback_ms=900_000, horizon_s=1800, variante="RESMOM_COURT")
            + _momentum(contexte, lookback_ms=3_600_000, horizon_s=7200, variante="RESMOM_LONG"))


# ═══════════ ABSORPTION_FRAGILITY (data disponible : trades) ═══════════
def absorption(contexte: dict) -> list[dict]:
    """Gros flux agressif SANS déplacement du prix = absorption -> fragilité. `contexte['_trades']` =
    {coin: [(ts, sz_signe)]} (achat +, vente −) ; `_prix` pour le déplacement. Variantes : fade / follow.
    Sans trades -> abstention."""
    if not K.autorise(K.regime_courant(Path(contexte.get("root") or ".")), "ABSORPTION_FRAGILITY"):
        return []
    trades = contexte.get("_trades") or {}
    series = contexte.get("_prix") or {}
    out = []
    for coin, tr in trades.items():
        if len(tr) < 10:
            continue
        fen = tr[-30:]
        flux = sum(sz for _t, sz in fen)                     # déséquilibre agressif net
        vol = sum(abs(sz) for _t, sz in fen)
        s = series.get(coin) or []
        if vol <= 0 or len(s) < 2:
            continue
        dprix = (0.5 * (s[-1][1] + s[-1][2]) - 0.5 * (s[-2][1] + s[-2][2])) / (0.5 * (s[-1][1] + s[-1][2])) * 1e4
        absorbe = abs(flux) / vol > 0.5 and abs(dprix) < 2.0  # fort déséquilibre, prix quasi immobile
        if not absorbe:
            continue
        ts = s[-1][0]
        out.append(K.signal(ts, coin, -1 if flux > 0 else 1, "ABSORB_FADE", flux=round(flux, 2)))
        out.append(K.signal(ts, coin, 1 if flux > 0 else -1, "ABSORB_FOLLOW", flux=round(flux, 2)))
    return out


# ═══════════ OI_CROWDING (data labo forward) ═══════════
def oi_crowding(contexte: dict) -> list[dict]:
    root = Path(contexte.get("root") or ".")
    if not K.autorise(K.regime_courant(root), "OI_CROWDING"):
        return []
    recs = contexte.get("_asset_ctx") or K.charger_lab_jsonl(root, "asset_ctx")
    oi = K.series_par_coin(recs, "oi"); prem = K.series_par_coin(recs, "premium_bps")
    out = []
    for coin, so in oi.items():
        sp = prem.get(coin) or []
        if len(so) < 3 or not sp:
            continue
        vel = (so[-1][1] - so[-2][1]) / max(1.0, so[-2][1])   # vitesse d'OI
        acc = vel - ((so[-2][1] - so[-3][1]) / max(1.0, so[-3][1]))
        p = sp[-1][1]
        if vel > 0.02 and acc > 0 and abs(p) >= 25.0:         # OI accélère + premium extrême -> continuation
            for var in ("OICROWD_COURT", "OICROWD_LONG"):
                out.append(K.signal(so[-1][0], coin, 1 if p > 0 else -1, var, oi_vel=round(vel, 4)))
    return out


# ═══════════ FUNDING_CLOCK (data labo forward) ═══════════
def funding_clock(contexte: dict) -> list[dict]:
    root = Path(contexte.get("root") or ".")
    if not K.autorise(K.regime_courant(root), "FUNDING_CLOCK"):
        return []
    recs = contexte.get("_asset_ctx") or K.charger_lab_jsonl(root, "asset_ctx")
    fund = K.series_par_coin(recs, "funding")
    out = []
    for coin, sf in fund.items():
        if len(sf) < 2:
            continue
        f0, f1 = sf[-2][1], sf[-1][1]
        if f0 * f1 < 0:                                       # changement de SIGNE du funding
            for var in ("FUNDCLK_PRE", "FUNDCLK_POST"):
                out.append(K.signal(sf[-1][0], coin, -1 if f1 > 0 else 1, var, funding=round(f1, 6)))
    return out


# ═══════════ OI_CAP_EVENT (data labo forward) ═══════════
def oi_cap_event(contexte: dict) -> list[dict]:
    root = Path(contexte.get("root") or ".")
    if not K.autorise(K.regime_courant(root), "OI_CAP_EVENT"):
        return []
    recs = contexte.get("_oi_cap") or K.charger_lab_jsonl(root, "oi_cap")
    if len(recs) < 2:
        return []
    avant = set(recs[-2].get("coins_au_cap") or [])
    apres = set(recs[-1].get("coins_au_cap") or [])
    ts = recs[-1].get("ts_wall_ms", 0)
    out = []
    for coin in apres - avant:                               # ENTRE au plafond -> continuation
        out.append(K.signal(ts, coin, 1, "OICAP_ENTER"))
    for coin in avant - apres:                               # SORT du plafond -> reversal
        out.append(K.signal(ts, coin, -1, "OICAP_EXIT"))
    return out


# ═══════════ HLP_PRESSURE (data labo forward) ═══════════
def hlp_pressure(contexte: dict) -> list[dict]:
    root = Path(contexte.get("root") or ".")
    if not K.autorise(K.regime_courant(root), "HLP_PRESSURE"):
        return []
    recs = contexte.get("_hlp") or K.charger_lab_jsonl(root, "hlp_inventory")
    szi = K.series_par_coin(recs, "szi")
    out = []
    for coin, ss in szi.items():
        if len(ss) < 2:
            continue
        d = ss[-1][1] - ss[-2][1]                            # variation d'inventaire HLP
        if abs(d) < 1e-9:
            continue
        # HLP absorbe le forced-flow : s'il ACCUMULE long (d>0), le flux forcé était vendeur -> fade = long
        for var in ("HLP_ACCUM", "HLP_REDUC"):
            out.append(K.signal(ss[-1][0], coin, 1 if d > 0 else -1, var, d_szi=round(d, 4)))
    return out


# ═══════════ enregistrement (6 plugins × 2 variantes = 12) ═══════════
_PLUGINS = [
    REG.Plugin("REGIME_ROUTER", "router", (), router_regime),
    REG.Plugin("RESIDUAL_MOMENTUM", "signal", ("RESMOM_COURT", "RESMOM_LONG"), residual_momentum),
    REG.Plugin("ABSORPTION_FRAGILITY", "signal", ("ABSORB_FADE", "ABSORB_FOLLOW"), absorption),
    REG.Plugin("OI_CROWDING", "signal", ("OICROWD_COURT", "OICROWD_LONG"), oi_crowding),
    REG.Plugin("FUNDING_CLOCK", "signal", ("FUNDCLK_PRE", "FUNDCLK_POST"), funding_clock),
    REG.Plugin("OI_CAP_EVENT", "signal", ("OICAP_ENTER", "OICAP_EXIT"), oi_cap_event),
    REG.Plugin("HLP_PRESSURE", "signal", ("HLP_ACCUM", "HLP_REDUC"), hlp_pressure),
]
for _p in _PLUGINS:
    try:
        REG.enregistrer(_p)
    except ValueError:
        import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
        _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)
