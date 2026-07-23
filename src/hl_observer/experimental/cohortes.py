"""MOTEUR INLINE DEUX-COHORTES (rectif Flo 23/07) — le WS userFills ouvre dans le MÊME flux.

Chaque fill reçu appelle `traiter_fill` : dédup (isSnapshot/hash), agrégation des OPEN/ADD EN DOLLARS
sur quelques secondes (plus de ΔNAV 2 % obligatoire), puis DÈS que le cumulé est significatif →
admission → L2 <1 s → VWAP/coûts complets → edge net positif → OUVERTURE paper INLINE, en mesurant la
LATENCE fill leader → décision. Les REDUCE/CLOSE du leader sortent la position inline.

DEUX cohortes ISOLÉES (stores/budgets/ledgers séparés — les PnL ne se mélangent jamais) :
  • ALPHA  : SOL/ADA (table GELÉE stricte, risque KILL appliqué), notional normal, budget $300, max 3 ;
  • DISCOVERY_PROBE : 2 CORE + 6 CHALLENGERS, table LARGE, tout petits notionals ($10-20), max 4, pertes
    très plafonnées — pour OBSERVER vite les autres coins liquides sans polluer le PnL ALPHA.

Auto-KILL : toute cohorte dont l'expectancy LIVE devient négative se met en pause (KILL). Aucun signal
synthétique, aucun trade forcé, aucune exécution réelle.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from hl_observer.experimental import moteur_paper as MP
from hl_observer.experimental.signaux import (_l2_pour_coin, _snapshots_bbo, _carnet_l2_frais, _allmids,
                                              _vaults_retenus)

FENETRE_AGG_MS = 5_000.0          # on agrège les OPEN/ADD d'un (vault,coin) sur 5 s
NOTIONAL_MIN_USD = 8.0
SLIPPAGE_BASE_BPS = 1.0
SLIPPAGE_IMPACT_COEF = 8.0
LATENCE_COUT_BPS = 1.0


@dataclass(frozen=True)
class Cohorte:
    nom: str
    prefixe: str                  # préfixe des fichiers (ledger/positions/status)
    budget_usd: float
    max_positions: int
    notional_usd: float
    stop_bps_defaut: float
    seuil_open_usd: float         # cumulé $ d'OPEN/ADD du leader qui déclenche une copie
    tables: tuple                 # tables prélim à essayer (ordre de priorité)


ALPHA = Cohorte("ALPHA_PAPER", "exploratory_paper", 300.0, 3, 60.0, 20.0, 2000.0,
                ("copy_prelim_gele_v1.json", "copy_prelim_edge.json"))
PROBE = Cohorte("DISCOVERY_PROBE", "discovery_probe", 100.0, 4, 15.0, 30.0, 500.0,
                ("copy_prelim_probe.json",))
COHORTES = {"ALPHA": ALPHA, "PROBE": PROBE}


def _p(coh: Cohorte, root: Path, quoi: str) -> Path:
    return root / "runtime" / "data" / ("%s_%s" % (coh.prefixe, quoi))


def charger_store(coh: Cohorte, root: Path) -> dict:
    try:
        return json.loads(_p(coh, root, "positions.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"cash": coh.budget_usd, "ouvertes": {}, "realise_total_usd": 0.0}


def _sauver(coh: Cohorte, root: Path, store: dict) -> None:
    p = _p(coh, root, "positions.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _ledger(coh: Cohorte, root: Path, evt: dict) -> None:
    p = _p(coh, root, "ledger.jsonl")
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({**evt, "cohorte": coh.nom, "real_execution": False}, ensure_ascii=False) + "\n")


def charger_table(coh: Cohorte, root: Path) -> dict[str, dict]:
    t: dict[str, dict] = {}
    for rel in coh.tables:
        try:
            d = json.loads((root / "runtime" / "data" / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        t = {str(k).upper(): v for k, v in (d.get("table") or d).items() if isinstance(v, dict)}
        if t:
            break
    if coh is PROBE and t:
        # ANTI-DOUBLE-COMPTAGE : PROBE ne trade JAMAIS un coin déjà géré par ALPHA (ex. ADA/SOL).
        # ALPHA a la priorité ; PROBE se réserve les AUTRES coins liquides.
        coins_alpha = set(charger_table(ALPHA, root))
        t = {c: v for c, v in t.items() if c not in coins_alpha}
    return t


def _mark(coin: str, root: Path, now_ms: float, lecteur_l2) -> float | None:
    l2 = _l2_pour_coin(coin, lecteur_l2=lecteur_l2, bbo=_snapshots_bbo(root),
                       carnet=_carnet_l2_frais(root, now_ms=now_ms), now_ms=now_ms)
    if l2:
        return (l2["hl_bid"] + l2["hl_ask"]) / 2.0
    return _allmids(root, now_ms=now_ms).get(coin)


def etat_initial(coh: Cohorte, root: Path) -> dict:
    return {"store": charger_store(coh, root), "agg": {}, "vus": set()}


def _expectancy(coh: Cohorte, root: Path) -> dict:
    try:
        closes = [json.loads(l) for l in _p(coh, root, "ledger.jsonl").read_text(encoding="utf-8", errors="ignore").splitlines() if l.strip()]
    except OSError:
        return {"n_trades": 0}
    closes = [c for c in closes if c.get("evt") == "CLOSE"]
    if not closes:
        return {"n_trades": 0}
    pnls = [float(c.get("realized_usd") or 0.0) for c in closes]
    lat = [float(c["latence_ms"]) for c in closes if c.get("latence_ms") is not None]
    n = len(pnls)
    return {"n_trades": n, "winrate_pct": round(sum(1 for p in pnls if p > 0) / n * 100, 1),
            "expectancy_usd_par_trade": round(sum(pnls) / n, 4),
            "latence_moyenne_ms": round(sum(lat) / len(lat)) if lat else None}


def cohorte_active(coh: Cohorte, root: Path) -> bool:
    """AUTO-KILL : une cohorte dont l'expectancy LIVE est négative (sur assez de trades) se met en pause."""
    ex = _expectancy(coh, root)
    return not (ex.get("n_trades", 0) >= 10 and ex.get("expectancy_usd_par_trade", 0.0) < 0)


def _ouvrir(coh: Cohorte, store: dict, root: Path, *, coin, sens, notional, prix, cfg, cout_ar,
            spread, slippage, fhl, vault, now_ms, fill_ts, latence_ms) -> dict:
    edge_net = float(cfg.get("edge_brut_bps") or 0.0) - cout_ar
    pos = {"coin": coin, "moteur": "copy_" + coh.nom, "sens": sens, "type_pnl": "directional",
           "notional_usd": round(notional, 2), "prix_entree": prix, "ts_ouverture_ms": now_ms,
           "cout_entree_bps": round(cout_ar / 2.0, 4), "edge_estime_bps": round(edge_net, 4),
           "spread_bps": round(spread, 4), "frais_bps": fhl, "slippage_bps": round(slippage, 4),
           "hold_h": float(cfg.get("horizon_ms") or 0.0) / 3_600_000.0,
           "meta": {"vault": vault, "coin": coin, "stop_bps": cfg.get("stop_bps"),
                    "take_profit_bps": cfg.get("take_profit_bps"), "latence_fill_copie_ms": round(latence_ms),
                    "fill_leader_ts_ms": int(fill_ts)}}
    store["ouvertes"][coin] = pos
    store["cash"] = round(store["cash"] - notional, 6)
    _ledger(coh, root, {"evt": "OPEN", "ts_ms": now_ms, "coin": coin, "sens": sens, "notional_usd": pos["notional_usd"],
                        "prix_entree": prix, "edge_net_bps": pos["edge_estime_bps"], "latence_ms": round(latence_ms),
                        "vault": vault, "motif": "copy OPEN/ADD agrégé $ + L2<1s + edge net>0"})
    _sauver(coh, root, store)
    return pos


def _sortir(coh: Cohorte, pos: dict, store: dict, root: Path, *, prix_sortie, cout_sortie_bps, raison,
            now_ms, mae_bps=None, mfe_bps=None) -> dict:
    realized = round(MP.pnl_courant_usd(pos, mark=prix_sortie, now_ms=now_ms) - cout_sortie_bps / 1e4 * pos["notional_usd"], 6)
    store["ouvertes"].pop(pos["coin"], None)
    store["cash"] = round(store["cash"] + pos["notional_usd"] + realized, 6)
    store["realise_total_usd"] = round(store.get("realise_total_usd", 0.0) + realized, 6)
    _ledger(coh, root, {"evt": "CLOSE", "ts_ms": now_ms, "coin": pos["coin"], "sens": pos["sens"],
                        "notional_usd": pos["notional_usd"], "prix_entree": pos["prix_entree"], "prix_sortie": prix_sortie,
                        "realized_usd": realized, "raison": raison, "mae_bps": mae_bps, "mfe_bps": mfe_bps,
                        "latence_ms": pos.get("meta", {}).get("latence_fill_copie_ms"), "vault": pos.get("meta", {}).get("vault")})
    _sauver(coh, root, store)
    return {"coin": pos["coin"], "realized_usd": realized, "raison": raison}


def _reduire(coh: Cohorte, pos: dict, store: dict, root: Path, *, fraction: float, prix: float,
             cout_sortie_bps: float, now_ms: float) -> dict:
    """REDUCE : réduit la copie de `fraction` (0<f<1) proportionnellement au leader — réalise le PnL sur
    la part fermée, garde le reste ouvert."""
    frac = max(0.0, min(1.0, fraction))
    part = round(pos["notional_usd"] * frac, 2)
    realized = round(MP.pnl_courant_usd(pos, mark=prix, now_ms=now_ms) * frac - cout_sortie_bps / 1e4 * part, 6)
    pos["notional_usd"] = round(pos["notional_usd"] - part, 2)
    store["cash"] = round(store["cash"] + part + realized, 6)
    store["realise_total_usd"] = round(store.get("realise_total_usd", 0.0) + realized, 6)
    _ledger(coh, root, {"evt": "REDUCE", "ts_ms": now_ms, "coin": pos["coin"], "fraction": round(frac, 3),
                        "part_notional_usd": part, "realized_usd": realized, "prix_sortie": prix,
                        "vault": pos.get("meta", {}).get("vault")})
    _sauver(coh, root, store)
    return {"coin": pos["coin"], "realized_usd": realized, "raison": "LEADER_A_REDUIT", "fraction": round(frac, 3)}


def traiter_fill(coh: Cohorte, etat: dict, fill: dict, root: Path, *, now_ms: float | None = None,
                 lecteur_l2=None, table: dict | None = None) -> dict | None:
    """INLINE : traite UN fill leader. Dédup (hash/isSnapshot) ; REDUCE/CLOSE → sortie ; OPEN/ADD agrégés
    en $ → admission → L2<1s → coûts → edge net>0 → OUVERTURE. Rend {ouverture|fermeture|refus, latence_ms}."""
    now = float(now_ms if now_ms is not None else time.time() * 1000)
    if fill.get("isSnapshot"):
        return None                                               # snapshot initial : on ne trade pas dessus
    h = fill.get("hash")
    if h:
        if h in etat["vus"]:
            return None                                           # dédup
        etat["vus"].add(h)
    store = etat["store"]
    coin = str(fill.get("coin") or "").upper()
    vault = fill.get("vault")
    sens = int(fill.get("signe") or 0)
    dir_bas = str(fill.get("dir") or "").lower()
    if not coin or sens == 0:
        return None
    table = table if table is not None else charger_table(coh, root)
    # LEADER REDUCE / CLOSE / FLIP -> on suit proportionnellement (via startPosition du fill)
    if "close" in dir_bas:
        pos = store["ouvertes"].get(coin)
        if not (pos and pos.get("meta", {}).get("vault") == vault):
            return None
        mark = _mark(coin, root, now, lecteur_l2) or pos["prix_entree"]
        cout = float(pos.get("spread_bps") or 0.0) / 2.0 + float(pos.get("frais_bps") or 0.0) + float(pos.get("slippage_bps") or 0.0)
        start = fill.get("start_position")
        sz = abs(float(fill.get("sz") or 0.0))
        if start is None or abs(start) < 1e-9:                     # info absente -> fermeture prudente complète
            return {"fermeture": _sortir(coh, pos, store, root, prix_sortie=mark, cout_sortie_bps=cout,
                                         raison="LEADER_A_CLOS", now_ms=now)}
        pos_after = start + sens * sz
        if abs(pos_after) < 1e-9:                                  # CLOSE : le leader ferme entièrement -> on ferme tout
            return {"fermeture": _sortir(coh, pos, store, root, prix_sortie=mark, cout_sortie_bps=cout,
                                         raison="LEADER_A_CLOS", now_ms=now)}
        if (start > 0) != (pos_after > 0):                        # FLIP : fermer puis REPASSER l'admission (résidu = nouvel OPEN)
            ferm = _sortir(coh, pos, store, root, prix_sortie=mark, cout_sortie_bps=cout, raison="LEADER_A_FLIP", now_ms=now)
            etat["agg"][(vault, coin)] = {"sens": 1 if pos_after > 0 else -1, "notional": abs(pos_after) * float(fill.get("px") or 0.0),
                                          "t0": now, "fill_ts": int(fill.get("ts_ms") or now)}
            return {"fermeture": ferm, "flip": True}
        fraction = min(1.0, sz / abs(start))                      # REDUCE : réduire la copie de la même fraction
        if fraction >= 0.999:
            return {"fermeture": _sortir(coh, pos, store, root, prix_sortie=mark, cout_sortie_bps=cout,
                                         raison="LEADER_A_CLOS", now_ms=now)}
        return {"reduction": _reduire(coh, pos, store, root, fraction=fraction, prix=mark, cout_sortie_bps=cout, now_ms=now)}
    if "open" not in dir_bas:
        return None
    # OPEN/ADD : agrégation EN DOLLARS sur quelques secondes (plus de ΔNAV 2 % obligatoire)
    key = (vault, coin)
    ag = etat["agg"].get(key)
    notional_fill = abs(float(fill.get("sz") or 0.0)) * float(fill.get("px") or 0.0)
    if ag and ag["sens"] == sens and (now - ag["t0"]) <= FENETRE_AGG_MS:
        ag["notional"] += notional_fill
    else:
        ag = {"sens": sens, "notional": notional_fill, "t0": now, "fill_ts": int(fill.get("ts_ms") or now)}
        etat["agg"][key] = ag
    if ag["notional"] < coh.seuil_open_usd:
        return None                                               # pas encore un OPEN/ADD significatif
    etat["agg"].pop(key, None)
    if not cohorte_active(coh, root):                             # AUTO-KILL : cohorte en pause (expectancy live < 0)
        return {"refus": "COHORTE_EN_PAUSE_AUTO_KILL", "coin": coin}
    # deny-by-default : le vault doit être suivi par la cohorte
    if vault not in _vaults_cohorte(coh, root):
        return {"refus": "VAULT_NON_SUIVI", "coin": coin}
    cfg = table.get(coin)
    if not cfg:
        return {"refus": "EDGE_PRELIM_ABSENT", "coin": coin}
    if coin in store["ouvertes"]:
        return {"refus": "DEJA_OUVERT", "coin": coin}
    if len(store["ouvertes"]) >= coh.max_positions:
        return {"refus": "LIMITE_POSITIONS", "coin": coin}
    if store["cash"] < NOTIONAL_MIN_USD:
        return {"refus": "BUDGET_EPUISE", "coin": coin}
    l2 = _l2_pour_coin(coin, lecteur_l2=lecteur_l2, bbo=_snapshots_bbo(root),
                       carnet=_carnet_l2_frais(root, now_ms=now), now_ms=now)
    if not l2:
        return {"refus": "L2_INDISPONIBLE_1S", "coin": coin}
    from hl_observer.experimental.carry_deux_jambes import frais_venues
    fhl = frais_venues(root)[0]
    hl_bid, hl_ask = l2["hl_bid"], l2["hl_ask"]
    mid = (hl_bid + hl_ask) / 2.0
    ref = _allmids(root, now_ms=now).get(coin)                    # garde-fou : prix L2 plausible vs allMids
    if ref and ref > 0 and abs(mid - ref) / ref > 0.10:           # >10 % d'écart = L2 aberrant/injecté -> refus
        return {"refus": "L2_ABERRANT", "coin": coin, "mid": round(mid, 6), "ref": round(ref, 6)}
    spread = (hl_ask - hl_bid) / mid * 1e4
    depth = float(l2.get("depth_usd") or 0.0)
    notional = min(coh.notional_usd, min(depth, store["cash"]))
    if notional < NOTIONAL_MIN_USD:
        return {"refus": "LIQUIDITE_INSUFFISANTE", "coin": coin}
    slippage = SLIPPAGE_BASE_BPS + SLIPPAGE_IMPACT_COEF * (notional / depth if depth else 1.0)
    cout_ar = 2.0 * fhl + spread + 2.0 * slippage + LATENCE_COUT_BPS
    if float(cfg.get("edge_brut_bps") or 0.0) - cout_ar <= 0:
        return {"refus": "EDGE_NEGATIF_APRES_COUTS", "coin": coin}
    prix = hl_ask if sens > 0 else hl_bid
    latence = max(0.0, now - ag["fill_ts"])                       # fill leader -> décision/ouverture
    pos = _ouvrir(coh, store, root, coin=coin, sens=sens, notional=notional, prix=prix, cfg=cfg, cout_ar=cout_ar,
                  spread=spread, slippage=slippage, fhl=fhl, vault=vault, now_ms=now, fill_ts=ag["fill_ts"],
                  latence_ms=latence)
    return {"ouverture": pos, "latence_ms": round(latence)}


def _vaults_cohorte(coh: Cohorte, root: Path) -> set[str]:
    """Vaults suivis par la cohorte (deny-by-default). ALPHA = retenus stricts ; PROBE = CORE+CHALLENGERS."""
    from hl_observer.experimental.exploratoire import tiers
    if coh is ALPHA:
        return _vaults_retenus(root)
    core, chal = tiers(root)
    return core | chal


def gerer_exits(coh: Cohorte, root: Path, *, now_ms: float | None = None, lecteur_l2=None) -> list[dict]:
    """Sorties par PRIX/TEMPS (stop calibré / take-profit / horizon) — complète les sorties leader inline.
    MAE/MFE suivis en continu."""
    now = float(now_ms if now_ms is not None else time.time() * 1000)
    store = charger_store(coh, root)
    fermetures = []
    for pos in list(store["ouvertes"].values()):
        mark = _mark(pos["coin"], root, now, lecteur_l2)
        if mark is None or not pos.get("prix_entree"):
            continue
        exc = pos["sens"] * (mark - pos["prix_entree"]) / pos["prix_entree"] * 1e4
        pos["mae_bps"] = round(min(pos.get("mae_bps", 0.0), exc), 3)
        pos["mfe_bps"] = round(max(pos.get("mfe_bps", 0.0), exc), 3)
        meta = pos.get("meta", {})
        stop = float(meta.get("stop_bps") or coh.stop_bps_defaut)
        tp = meta.get("take_profit_bps")
        cout = float(pos.get("spread_bps") or 0.0) / 2.0 + float(pos.get("frais_bps") or 0.0) + float(pos.get("slippage_bps") or 0.0)
        raison = None
        if exc <= -stop:
            raison = "STOP_PERTE"
        elif tp and exc >= float(tp):
            raison = "TAKE_PROFIT"
        elif (now - float(pos.get("ts_ouverture_ms") or now)) >= float(pos.get("hold_h") or 1.0) * 3_600_000.0:
            raison = "HORIZON_ATTEINT"
        if raison:
            fermetures.append(_sortir(coh, pos, store, root, prix_sortie=mark, cout_sortie_bps=cout,
                                      raison=raison, now_ms=now, mae_bps=pos.get("mae_bps"), mfe_bps=pos.get("mfe_bps")))
    _sauver(coh, root, store)
    return fermetures


def statut(coh: Cohorte, root: Path, *, now_ms: float | None = None, lecteur_l2=None) -> dict:
    now = float(now_ms if now_ms is not None else time.time() * 1000)
    store = charger_store(coh, root)
    non_realise = 0.0
    for pos in store["ouvertes"].values():
        mark = _mark(pos["coin"], root, now, lecteur_l2)
        if mark is not None:
            non_realise += MP.pnl_courant_usd(pos, mark=mark, now_ms=now)
    equity = round(store["cash"] + sum(p["notional_usd"] for p in store["ouvertes"].values()) + non_realise, 4)
    st = {"cohorte": coh.nom, "real_execution": False, "ts_ms": int(now), "active": cohorte_active(coh, root),
          "budget_usd": coh.budget_usd, "cash": store["cash"], "positions_ouvertes": len(store["ouvertes"]),
          "realise_total_usd": store.get("realise_total_usd", 0.0), "non_realise_usd": round(non_realise, 4),
          "equity_usd": equity, "roi_cumulatif_pct": round((equity - coh.budget_usd) / coh.budget_usd * 100, 3),
          "expectancy": _expectancy(coh, root),
          "positions": [{"coin": p["coin"], "sens": p["sens"], "notional_usd": p["notional_usd"],
                         "prix_entree": p["prix_entree"], "vault": p.get("meta", {}).get("vault"),
                         "edge_net_bps": p["edge_estime_bps"], "mae_bps": p.get("mae_bps"), "mfe_bps": p.get("mfe_bps"),
                         "latence_fill_copie_ms": p.get("meta", {}).get("latence_fill_copie_ms")}
                        for p in store["ouvertes"].values()]}
    p = _p(coh, root, "status.json")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return st


__all__ = ["Cohorte", "ALPHA", "PROBE", "COHORTES", "traiter_fill", "gerer_exits", "statut",
           "charger_store", "charger_table", "etat_initial", "cohorte_active", "FENETRE_AGG_MS"]
