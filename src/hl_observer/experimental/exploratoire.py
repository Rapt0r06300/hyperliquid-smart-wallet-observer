"""COHORTE EXPLORATORY_PAPER (décision Flo 23/07) — apprendre MAINTENANT, sans attendre une validation
OOS parfaite, mais SANS jamais tricher.

Différence avec l'allocateur strict (EXPERIMENTAL_PAPER, qui exige une config MESURÉE+GELÉE en OOS) :
la cohorte exploratoire OUVRE dès qu'un VRAI mouvement LIVE d'un vault RETENU est détecté ET que le coin
a un edge PRÉLIMINAIRE positif (descriptif, mesuré sur candles, PAS OOS), avec L2 <1 s, VWAP/profondeur,
coûts complets et sortie définie. Isolée : petit budget, notionals bornés par la profondeur, MAX 3
positions, PERTES PLAFONNÉES. Aucun signal synthétique, aucun trade forcé, aucune exécution réelle.

Ledger/budget/positions SÉPARÉS de tout le reste. Le PnL exploratoire ne se mélange jamais au live.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hl_observer.experimental import moteur_paper as MP
from hl_observer.experimental.signaux import signaux_vaults, _l2_pour_coin, _snapshots_bbo, _carnet_l2_frais, _allmids

MODE = "EXPLORATORY_PAPER"
VERSION = "v1"
LEDGER_RELPATH = Path("runtime") / "data" / "exploratory_paper_ledger.jsonl"
POSITIONS_RELPATH = Path("runtime") / "data" / "exploratory_paper_positions.json"
STATUS_RELPATH = Path("runtime") / "data" / "exploratory_paper_status.json"
PRELIM_GELE_RELPATH = Path("runtime") / "data" / "copy_prelim_gele_v1.json"   # table GELÉE versionnée (prioritaire)
PRELIM_RELPATH = Path("runtime") / "data" / "copy_prelim_edge.json"          # table live (repli d'amorçage)

BUDGET_TOTAL_USD = 300.0          # PETIT budget isolé
MAX_POSITIONS = 3                 # au plus 3 positions ouvertes
NOTIONAL_CIBLE_USD = 60.0         # cible par position (bornée ensuite par la profondeur du L2)
STOP_BPS_DEFAUT = 20.0            # stop de repli (bps) si le coin n'a pas de risque calibré — JAMAIS 150 bps
HOLD_MAX_H_DEFAUT = 1.0           # sortie au plus tard après l'horizon (défini)
SEUIL_MOVE_EXPLO = 0.02           # exploratoire : seuil NAV plus bas (2 %) pour APPRENDRE de plus de moves live
N_CORE = 2                        # 2 vaults CORE (retenus stricts)
N_CHALLENGERS = 6                 # + jusqu'à 6 CHALLENGERS (bar plus souple, notional réduit)
NOTIONAL_CHALLENGER_FACTOR = 0.5  # les challengers ouvrent en plus PETIT (on apprend en risquant moins)
SCORES_RELPATH = Path("runtime") / "data" / "vaults_scores.json"


def tiers(root: Path) -> tuple[set[str], set[str]]:
    """(CORE, CHALLENGERS) depuis vaults_scores : CORE = retenus stricts (top 2) ; CHALLENGERS = suivants
    par composite passant une barre de SÉCURITÉ (âge/drawdown/copyabilité), jamais tout-venant. DENY-BY-
    DEFAULT reste : sans score, les deux ensembles sont vides."""
    try:
        d = json.loads((root / SCORES_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set(), set()
    classement = d.get("classement") or []
    core = [c["vault"] for c in classement if c.get("retenu")][:N_CORE]
    challengers: list[str] = []
    for c in classement:
        if c["vault"] in core:
            continue
        f = c.get("facteurs", {})
        if (float(f.get("anciennete_j") or 0) >= 45 and float(f.get("drawdown_pct") or 100) <= 45
                and float(f.get("copyabilite") or 0) >= 0.5):     # sécurité minimale (deny-by-default conservé)
            challengers.append(c["vault"])
        if len(challengers) >= N_CHALLENGERS:
            break
    return set(core), set(challengers)


def charger_table_prelim(root: Path) -> dict[str, dict]:
    """{coin: {edge_brut_bps, horizon_ms, net_bps, stop_bps, take_profit_bps}} — edge PRÉLIMINAIRE positif
    par coin, avec risque calibré. Priorité à la table GELÉE VERSIONNÉE (anti-réoptimisation : le forward
    ne se réoptimise jamais après coup) ; repli sur la table live seulement pour l'amorçage. Vide → la
    cohorte n'ouvre RIEN (deny-by-default, jamais forcé)."""
    for rel in (PRELIM_GELE_RELPATH, PRELIM_RELPATH):
        try:
            d = json.loads((root / rel).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        t = {str(k).upper(): v for k, v in (d.get("table") or d).items() if isinstance(v, dict)}
        if t:
            return t
    return {}


def charger_store(root: Path) -> dict:
    try:
        return json.loads((root / POSITIONS_RELPATH).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"cash": BUDGET_TOTAL_USD, "ouvertes": {}, "realise_total_usd": 0.0}


def _sauver(root: Path, store: dict) -> None:
    p = root / POSITIONS_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
    tmp.replace(p)


def _ledger(root: Path, evt: dict) -> None:
    p = root / LEDGER_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as f:
        f.write(json.dumps({**evt, "mode": MODE, "real_execution": False}, ensure_ascii=False) + "\n")


def admettre(sig: MP.Signal, store: dict) -> tuple[bool, str | None]:
    """Barème EXPLORATOIRE (apprendre) : edge net PRÉLIMINAIRE > 0, notional utile, 1 marché = 1 position,
    MAX 3 positions, budget. Pas de barre MIN_EDGE stricte (on apprend), mais JAMAIS un edge négatif."""
    if sig.edge_estime_bps <= 0:
        return False, "EDGE_PRELIM_NON_POSITIF"
    if sig.notional_usd < 20.0:
        return False, "LIQUIDITE_INSUFFISANTE"
    if sig.coin in store["ouvertes"]:
        return False, "DEJA_OUVERT"
    if len(store["ouvertes"]) >= MAX_POSITIONS:
        return False, "LIMITE_3_POSITIONS"
    if store["cash"] < sig.notional_usd:
        return False, "BUDGET_EPUISE"
    return True, None


def ouvrir(sig: MP.Signal, store: dict, root: Path, *, now_ms: float) -> dict:
    pos = {"coin": sig.coin, "moteur": "copy_vault_explo", "sens": sig.sens, "type_pnl": "directional",
           "notional_usd": sig.notional_usd, "prix_entree": sig.prix_entree, "ts_ouverture_ms": now_ms,
           "cout_entree_bps": sig.cout_entree_bps, "edge_estime_bps": sig.edge_estime_bps,
           "spread_bps": sig.spread_bps, "frais_bps": sig.frais_bps, "slippage_bps": sig.slippage_bps,
           "hold_h": sig.hold_h or HOLD_MAX_H_DEFAUT, "meta": dict(sig.meta)}
    store["ouvertes"][sig.coin] = pos
    store["cash"] = round(store["cash"] - sig.notional_usd, 6)
    _ledger(root, {"evt": "OPEN", "ts_ms": now_ms, **{k: pos[k] for k in
            ("coin", "sens", "notional_usd", "prix_entree", "cout_entree_bps", "edge_estime_bps")},
            "motif": sig.meta.get("note", "copy_vault_exploratoire"), "vault": sig.meta.get("vault")})
    _sauver(root, store)
    return pos


def sortir(pos: dict, store: dict, root: Path, *, prix_sortie: float, cout_sortie_bps: float,
           raison: str, now_ms: float, mae_bps: float | None = None, mfe_bps: float | None = None) -> dict:
    realized = MP.pnl_courant_usd(pos, mark=prix_sortie, now_ms=now_ms) - cout_sortie_bps / 1e4 * pos["notional_usd"]
    realized = round(realized, 6)
    duree_ms = now_ms - float(pos.get("ts_ouverture_ms") or now_ms)
    store["ouvertes"].pop(pos["coin"], None)
    store["cash"] = round(store["cash"] + pos["notional_usd"] + realized, 6)
    store["realise_total_usd"] = round(store.get("realise_total_usd", 0.0) + realized, 6)
    _ledger(root, {"evt": "CLOSE", "ts_ms": now_ms, "coin": pos["coin"], "sens": pos["sens"],
                   "notional_usd": pos["notional_usd"], "prix_entree": pos["prix_entree"],
                   "prix_sortie": prix_sortie, "realized_usd": realized, "raison": raison,
                   "duree_ms": round(duree_ms), "mae_bps": mae_bps, "mfe_bps": mfe_bps,
                   "delai_detection_ms": pos.get("meta", {}).get("delai_detection_ms"),
                   "vault": pos.get("meta", {}).get("vault")})
    _sauver(root, store)
    return {"coin": pos["coin"], "realized_usd": realized, "raison": raison, "mae_bps": mae_bps, "mfe_bps": mfe_bps}


def _mark(root: Path, coin: str, *, now_ms: float, lecteur_l2=None) -> float | None:
    """Prix courant pour marquer/sortir : L2 <1 s (mid) prioritaire, sinon allMids frais."""
    l2 = _l2_pour_coin(coin, lecteur_l2=lecteur_l2, bbo=_snapshots_bbo(root),
                       carnet=_carnet_l2_frais(root, now_ms=now_ms), now_ms=now_ms)
    if l2:
        return (l2["hl_bid"] + l2["hl_ask"]) / 2.0
    return _allmids(root, now_ms=now_ms).get(coin)


def _raison_sortie(pos: dict, root: Path, *, now_ms: float, mark: float | None) -> tuple[str | None, float]:
    """Sortie DÉFINIE avec risque CALIBRÉ (rectif Flo : plus de stop fixe démesuré). (1) le LEADER a
    réduit/clos ; (2) STOP calibré = MAE_p75 du coin (excursion adverse en bps) ; (3) TAKE-PROFIT calibré
    = MFE_p50 ; (4) horizon. Le stop/TP sont en bps (proportionnés à l'edge), jamais un forfait absurde."""
    from hl_observer.experimental.runner import _etat_leader
    meta = pos.get("meta") or {}
    cout_sortie = float(pos.get("spread_bps") or 0.0) / 2.0 + float(pos.get("frais_bps") or 0.0) + float(pos.get("slippage_bps") or 0.0)
    # LOT14 P1/P2/P3 : _etat_leader classe le changement du leader depuis un snapshot COMPLET/FRAIS/postérieur.
    et = _etat_leader(pos, root, now_ms=now_ms)
    if et["action"] in ("REDUCE", "CLOSE", "FLIP_LONG_SHORT", "FLIP_SHORT_LONG"):
        return "LEADER_%s" % et["action"], cout_sortie
    if mark is not None and pos.get("prix_entree"):
        # excursion BRUTE courante dans le sens de la position (bps)
        excursion_bps = pos["sens"] * (mark - pos["prix_entree"]) / pos["prix_entree"] * 1e4
        stop_bps = float(meta.get("stop_bps") or STOP_BPS_DEFAUT)
        tp_bps = meta.get("take_profit_bps")
        if excursion_bps <= -stop_bps:
            return "STOP_PERTE", cout_sortie
        if tp_bps and excursion_bps >= float(tp_bps):
            return "TAKE_PROFIT", cout_sortie
    horizon_ms = float(pos.get("hold_h") or HOLD_MAX_H_DEFAUT) * 3_600_000.0
    if (now_ms - float(pos.get("ts_ouverture_ms") or now_ms)) >= horizon_ms:
        return "HORIZON_ATTEINT", cout_sortie
    return None, cout_sortie


def _expectancy(root: Path) -> dict:
    """Expectancy des trades CLÔTURÉS (depuis le ledger) : n, winrate, gain/perte moyens, expectancy $ par
    trade, MAE/MFE moyens, délai fill→copie moyen. Vide si aucun trade clos."""
    try:
        closes = [json.loads(l) for l in (root / LEDGER_RELPATH).read_text(encoding="utf-8", errors="ignore").splitlines()
                  if l.strip()]
    except OSError:
        return {"n_trades": 0}
    closes = [c for c in closes if c.get("evt") == "CLOSE"]
    if not closes:
        return {"n_trades": 0}
    pnls = [float(c.get("realized_usd") or 0.0) for c in closes]
    gains = [p for p in pnls if p > 0]
    pertes = [p for p in pnls if p < 0]
    maes = [float(c["mae_bps"]) for c in closes if c.get("mae_bps") is not None]
    mfes = [float(c["mfe_bps"]) for c in closes if c.get("mfe_bps") is not None]
    delais = [float(c["delai_detection_ms"]) for c in closes if c.get("delai_detection_ms") is not None]
    n = len(pnls)
    return {"n_trades": n, "winrate_pct": round(len(gains) / n * 100, 1),
            "gain_moyen_usd": round(sum(gains) / len(gains), 4) if gains else 0.0,
            "perte_moyenne_usd": round(sum(pertes) / len(pertes), 4) if pertes else 0.0,
            "expectancy_usd_par_trade": round(sum(pnls) / n, 4),
            "mae_moyen_bps": round(sum(maes) / len(maes), 2) if maes else None,
            "mfe_moyen_bps": round(sum(mfes) / len(mfes), 2) if mfes else None,
            "delai_fill_copie_moyen_ms": round(sum(delais) / len(delais)) if delais else None}


def tick(root: str | Path = ".", *, now_ms: float | None = None, lecteur_l2=None) -> dict[str, Any]:
    """Un cycle EXPLORATOIRE : gère les sorties (leader/stop/horizon), détecte les mouvements LIVE des
    vaults retenus avec edge préliminaire positif, admet sous les limites (max 3, budget, stop) et OUVRE."""
    import time
    root = Path(root)
    now = float(now_ms if now_ms is not None else time.time() * 1000)
    store = charger_store(root)
    table = charger_table_prelim(root)
    fermetures: list[dict] = []
    for pos in list(store["ouvertes"].values()):
        mark = _mark(root, pos["coin"], now_ms=now, lecteur_l2=lecteur_l2)
        if mark is not None and pos.get("prix_entree"):           # MAE/MFE suivis en continu (rectif Flo)
            exc = pos["sens"] * (mark - pos["prix_entree"]) / pos["prix_entree"] * 1e4
            pos["mae_bps"] = round(min(pos.get("mae_bps", 0.0), exc), 3)
            pos["mfe_bps"] = round(max(pos.get("mfe_bps", 0.0), exc), 3)
        raison, cout = _raison_sortie(pos, root, now_ms=now, mark=mark)
        if raison:
            fermetures.append(sortir(pos, store, root, prix_sortie=(mark or pos["prix_entree"]),
                                     cout_sortie_bps=cout, raison=raison, now_ms=now,
                                     mae_bps=pos.get("mae_bps"), mfe_bps=pos.get("mfe_bps")))
    _sauver(root, store)                                           # persiste les MAE/MFE mis à jour
    core, challengers = tiers(root)                               # CORE (2) + CHALLENGERS (≤6)
    sigs, refus = signaux_vaults(root, now_ms=now, lecteur_l2=lecteur_l2, edge_par_coin=table,
                                 seuil_move=SEUIL_MOVE_EXPLO, retenus=core | challengers)
    ouvertures: list[dict] = []
    from collections import Counter
    motifs = Counter(r["motif"] for r in refus)
    for sig in sigs:
        vault = sig.meta.get("vault")
        tier = "CORE" if vault in core else ("CHALLENGER" if vault in challengers else "?")
        if tier == "CHALLENGER":                                  # challengers : notional PLUS PETIT (on apprend)
            sig.notional_usd = round(sig.notional_usd * NOTIONAL_CHALLENGER_FACTOR, 2)
            sig.pnl_attendu_usd = round(sig.pnl_attendu_usd * NOTIONAL_CHALLENGER_FACTOR, 4)
        sig.meta["tier"] = tier
        ok, motif = admettre(sig, store)
        if ok:
            ouvertures.append(ouvrir(sig, store, root, now_ms=now))
        else:
            motifs[motif] += 1
    # PnL/equity liquidable maintenant
    non_realise = 0.0
    for pos in store["ouvertes"].values():
        mark = _mark(root, pos["coin"], now_ms=now, lecteur_l2=lecteur_l2)
        if mark is not None:
            non_realise += MP.pnl_courant_usd(pos, mark=mark, now_ms=now)
    equity = round(store["cash"] + sum(p["notional_usd"] for p in store["ouvertes"].values()) + non_realise, 4)
    st = {"mode": MODE, "version": VERSION, "real_execution": False, "ts_ms": int(now),
          "budget_total_usd": BUDGET_TOTAL_USD, "cash": store["cash"], "positions_ouvertes": len(store["ouvertes"]),
          "realise_total_usd": store.get("realise_total_usd", 0.0), "non_realise_usd": round(non_realise, 4),
          "equity_usd": equity, "roi_cumulatif_pct": round((equity - BUDGET_TOTAL_USD) / BUDGET_TOTAL_USD * 100, 3),
          "ouvertures_ce_tick": len(ouvertures), "n_coins_prelim_positifs": len(table),
          "expectancy": _expectancy(root), "refus_par_motif": dict(motifs),
          "positions": [{"coin": p["coin"], "sens": p["sens"], "notional_usd": p["notional_usd"],
                         "prix_entree": p["prix_entree"], "vault": p.get("meta", {}).get("vault"),
                         "edge_prelim_bps": p["edge_estime_bps"], "mae_bps": p.get("mae_bps"),
                         "mfe_bps": p.get("mfe_bps"), "delai_detection_ms": p.get("meta", {}).get("delai_detection_ms")}
                        for p in store["ouvertes"].values()]}
    p = root / STATUS_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ouvertures": ouvertures, "fermetures": fermetures, "refus_par_motif": dict(motifs), "statut": st}


__all__ = ["tick", "admettre", "ouvrir", "sortir", "charger_store", "charger_table_prelim",
           "BUDGET_TOTAL_USD", "MAX_POSITIONS", "STOP_BPS_DEFAUT", "MODE"]
