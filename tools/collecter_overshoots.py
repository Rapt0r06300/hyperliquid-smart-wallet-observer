"""COLLECTEUR D'ÉVÉNEMENTS DE LIQUIDATION (overshoot mark/oracle) — l'infra n°1 (23/07).

POURQUOI (diagnostic du 23/07). La meilleure piste — le FADE de cascades de liquidations (le liquidé
est VENDU au marché, il ne choisit pas) — était bloquée par la DONNÉE : `liquidation_map` ne contient
que des snapshots « à risque » (distance 708 bps, PAS liquidés), et le firehose ne capte pas
`is_liquidation`. Preuve externe walk-forward (Curupira/0xArchive) : PF~2,9 sur ETH/SOL après frais,
**BTC mort** (book trop profond).

L'IDÉE QUI REND ÇA CAPTURABLE SANS FLAG. Sur Hyperliquid, le déclencheur de liquidation est le **mark**
(= `oracle + EMA_150s(mid − oracle)`). Pendant une purge, le forced-flow pousse le **mid** loin de
l'**oracle** (le prix « juste », médiane pondérée de CEX), puis ça revient au mark. Donc
`overshoot = (mid − oracle) / oracle` CAPTURE l'événement — que HL le flague ou non (robuste au schéma).
On enregistre l'overshoot PUIS le chemin de prix FORWARD (15/30/60/120 s) : la réversion mesurée est la
matière exacte du fade. Aucune donnée inventée : sans oracle ou sans mid frais, on n'écrit rien.

CE QUI EST MESURÉ (pas promis). Ce collecteur produit la DONNÉE ; le verdict (le fade bat-il ses coûts,
par coin, en OOS + PBO ?) est l'expérience #2, jugée séparément quand les événements se seront accumulés.
BTC est exclu par défaut (mort). On garde tout le reste ; le backtest filtrera par coin.

READ-ONLY / PAPER-ONLY : deux endpoints `/info` publics en lecture. Aucun ordre, aucune clé, aucune
signature, aucune monnaie. Collecter n'est pas trader.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from hl_observer.collection import collecte_fiable as CF  # noqa: E402

URL_INFO = "https://api.hyperliquid.xyz/info"
SORTIE = Path("runtime") / "data" / "overshoots_liquidation.jsonl"
#: état des événements EN COURS (chemins forward pas encore échus) — persisté pour survivre aux
#: relances `--une-fois` de `boucle_collecteur.cmd` (sinon un événement ouvert serait perdu à chaque
#: relance et n'arriverait jamais à terme).
ETAT = Path("runtime") / "data" / "overshoots_etat.json"

#: au-delà de ce |overshoot|, le mid a franchement débordé de l'oracle -> forced-flow candidat.
#: 30 bps = bien au-delà du bruit de base normal (mid ≈ oracle hors stress).
SEUIL_OVERSHOOT_BPS = 30.0
#: horizons de mesure de la réversion (s). Le fade revient vite -> on veut du court.
HORIZONS_S = (15.0, 30.0, 60.0, 120.0)
#: BTC exclu : book trop profond, overshoot < spread, DD 8× (mesure externe). Le backtest le
#: rejetterait de toute façon ; on économise le bruit.
COINS_EXCLUS = frozenset({"BTC"})
POLL_S_DEFAUT = 5.0
INTERVALLE_MAX_S = 90.0     # au-delà, une donnée est trop vieille pour situer un overshoot


# ─────────────────────────────── réseau (borné, poli) ───────────────────────────────

def _post_info(charge: dict[str, Any], *, timeout_s: float = 10.0) -> Any:
    corps = json.dumps(charge).encode("utf-8")
    req = urllib.request.Request(URL_INFO, data=corps,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:      # noqa: S310 (URL constante)
        return json.loads(rep.read().decode("utf-8"))


def lire_all_mids(*, timeout_s: float = 10.0) -> dict[str, float]:
    data = _post_info({"type": "allMids"}, timeout_s=timeout_s)
    out: dict[str, float] = {}
    if isinstance(data, dict):
        for k, v in data.items():
            try:
                out[str(k).upper()] = float(v)
            except (TypeError, ValueError):
                continue
    return out


def parser_ctxs(payload: Any) -> dict[str, dict]:
    """`metaAndAssetCtxs` renvoie [meta, contextes] où meta.universe[i] correspond à contextes[i].
    -> {COIN: {oracle, mark}}. Illisible / incomplet -> écarté (jamais un prix inventé)."""
    out: dict[str, dict] = {}
    try:
        meta, ctxs = payload[0], payload[1]
        univers = meta["universe"]
    except (TypeError, KeyError, IndexError):
        return out
    if not isinstance(ctxs, list):
        return out
    for i, actif in enumerate(univers if isinstance(univers, list) else []):
        if i >= len(ctxs) or not isinstance(actif, dict) or not isinstance(ctxs[i], dict):
            continue
        nom = str(actif.get("name") or "").upper()
        try:
            oracle = float(ctxs[i]["oraclePx"])
            mark = float(ctxs[i].get("markPx") or oracle)
        except (KeyError, TypeError, ValueError):
            continue
        if nom and oracle > 0:
            out[nom] = {"oracle": oracle, "mark": mark}
    return out


def lire_ctxs(*, timeout_s: float = 10.0) -> dict[str, dict]:
    return parser_ctxs(_post_info({"type": "metaAndAssetCtxs"}, timeout_s=timeout_s))


# ─────────────────────────────── cœur PUR (aucune I/O) ───────────────────────────────

def overshoot_bps(mid: float, oracle: float) -> float | None:
    """(mid − oracle)/oracle en bps. Négatif = le mid déborde SOUS l'oracle (forced SELLING)."""
    if oracle <= 0 or mid <= 0:
        return None
    return (mid - oracle) / oracle * 1e4


def detecter(mids: dict[str, float], ctxs: dict[str, dict], *,
             seuil_bps: float = SEUIL_OVERSHOOT_BPS,
             exclus: frozenset = COINS_EXCLUS) -> list[dict]:
    """Les coins dont le |overshoot| franchit le seuil, MAINTENANT. Cœur pur, testable sans réseau."""
    out: list[dict] = []
    for coin, c in ctxs.items():
        if coin in exclus:
            continue
        mid = mids.get(coin)
        if mid is None:
            continue
        ov = overshoot_bps(mid, c["oracle"])
        if ov is None or abs(ov) < seuil_bps:
            continue
        out.append({"coin": coin, "oracle_px": c["oracle"], "mark_px": c["mark"],
                    "mid_at_event": mid, "overshoot_bps": round(ov, 3),
                    "sens": "SELL_OVERSHOOT" if ov < 0 else "BUY_OVERSHOOT"})
    return out


def avancer(ouverts: dict[str, dict], mids: dict[str, float], now: float, *,
            horizons_s=HORIZONS_S) -> list[dict]:
    """Remplit les mids FORWARD des événements ouverts ; renvoie ceux ARRIVÉS À TERME (tous horizons
    échus), prêts à écrire. Cœur pur. La réversion se lit ensuite `mid_fwd_*` vs `oracle_px`."""
    finis: list[dict] = []
    hmax = max(horizons_s)
    for coin in list(ouverts):
        ev = ouverts[coin]
        age = now - ev["ts0"]
        for h in horizons_s:
            cle = "mid_fwd_%gs" % h
            if age >= h and cle not in ev and coin in mids:
                ev[cle] = mids[coin]
        if age >= hmax:
            # réversion = mouvement du mid VERS l'oracle, dans le sens du fade (bps du mid initial)
            m0 = ev["mid_at_event"]
            mf = ev.get("mid_fwd_%gs" % hmax) or m0
            signe = 1.0 if ev["overshoot_bps"] < 0 else -1.0   # fade : on parie le retour vers l'oracle
            ev["reversion_bps"] = round(signe * (mf - m0) / m0 * 1e4, 3) if m0 > 0 else 0.0
            ev["ts_fin_ms"] = int(now * 1000)
            finis.append(ev)
            del ouverts[coin]
    return finis


# ─────────────────────────────── une passe (I/O bornée) ───────────────────────────────

def une_passe(root: Path, ouverts: dict[str, dict], *, now: float | None = None,
              cache: "CF.CacheDedup | None" = None) -> int:
    """Un cycle : lit ctxs+mids, ouvre les nouveaux overshoots, avance les ouverts, écrit les finis.
    Réseau coupé -> 0 écrit, jamais d'exception qui tue la boucle."""
    t = now if now is not None else time.time()
    try:
        ctxs = lire_ctxs()
        mids = lire_all_mids()
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return 0
    for e in detecter(mids, ctxs):
        ouverts.setdefault(e["coin"], {**e, "ts0": t})     # 1 événement ouvert par coin à la fois
    finis = avancer(ouverts, mids, t)
    if not finis:
        return 0
    propres = CF.collecter_proprement(
        [{**e, "ts_ms": int(e["ts0"] * 1000), "read_only": True, "real_execution": False}
         for e in finis],
        source="overshoots_hl", champs_cle=("coin", "ts_ms"), cache=cache)
    return CF.append_jsonl(root / SORTIE, propres)


def charger_ouverts(root: str | Path) -> dict[str, dict]:
    """L'état des événements en cours, pour survivre à une relance `--une-fois`. Illisible -> {}."""
    p = Path(root) / ETAT
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def sauver_ouverts(root: str | Path, ouverts: dict[str, dict]) -> None:
    CF.ecrire_atomique(Path(root) / ETAT, json.dumps(ouverts, ensure_ascii=False))


def resume(root: str | Path = ".") -> dict[str, Any]:
    """État honnête de la collecte : combien d'événements, sur combien de coins, verdict."""
    p = Path(root) / SORTIE
    if not p.exists():
        return {"evenements": 0, "coins": 0, "verdict": "AUCUN_OVERSHOOT_ENCORE_COLLECTE"}
    coins: set[str] = set()
    n = 0
    for l in p.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            d = json.loads(l)
        except ValueError:
            continue
        n += 1
        coins.add(str(d.get("coin") or ""))
    return {"evenements": n, "coins": len(coins),
            "verdict": ("PRET_POUR_LE_BACKTEST_FADE" if n >= 50
                        else "INSUFFISANT_LAISSER_TOURNER")}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collecteur d'événements de liquidation (overshoot, lecture seule).")
    p.add_argument("--root", default=".")
    p.add_argument("--poll", type=float, default=POLL_S_DEFAUT)
    p.add_argument("--une-fois", action="store_true")
    a = p.parse_args(argv)
    root = Path(a.root)
    ouverts = charger_ouverts(root)                # reprend les événements en cours d'une relance
    cache = CF.CacheDedup()
    total, echecs = 0, 0
    while True:
        try:
            n = une_passe(root, ouverts, cache=cache)
            sauver_ouverts(root, ouverts)          # état persistant -> survit aux relances --une-fois
            total += n
            echecs = 0
            if n:
                print("[overshoots] %s  ecrits=%d  cumul=%d  (ouverts=%d)"
                      % (time.strftime("%H:%M:%S"), n, total, len(ouverts)), flush=True)
        except Exception as exc:  # noqa: BLE001 — on ne meurt jamais, on recule
            echecs += 1
            d = CF.backoff_jitter(echecs)
            print("[overshoots] erreur (%s) — backoff %.1fs" % (str(exc)[:60], d), flush=True)
            time.sleep(d)
            continue
        if a.une_fois:
            return 0
        time.sleep(max(1.0, float(a.poll)))


if __name__ == "__main__":
    raise SystemExit(main())
