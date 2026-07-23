"""PROMOTION DES CANDIDATS OBSERVÉS (rectif Flo 23/07) — augmenter les occasions sans contaminer ALPHA.

Les 6 vaults CANDIDAT_OBSERVE reçoivent leurs fills en WS mais ne TRADENT pas. Ce module les note depuis
le journal de fills (`fills_journal.jsonl`) : FRÉQUENCE (OPEN/h), COPYABILITÉ (part de leurs OPEN sur des
coins de la table PROBE) et RÉSULTAT SHADOW (rendement forward moyen de leurs OPEN, mesuré sur la tape de
prix — sans trader). On PROMEUT les 2 meilleurs qui passent les gates minimums en **mini-PROBE (5-10 $)**.

PUR (lecture de journaux + tape). Écrit `candidats_promus.json`. Aucun ordre, aucune exécution.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

JOURNAL = Path("runtime") / "data" / "fills_journal.jsonl"
PROMUS = Path("runtime") / "data" / "candidats_promus.json"
MIN_OPEN = 5                      # au moins 5 OPEN observés pour juger
MIN_COPYABILITE = 0.5            # au moins 50 % des OPEN sur des coins PROBE (pricables)
MIN_SHADOW_NET_BPS = 0.0        # rendement shadow net > 0 pour promouvoir
NOTIONAL_MINI_USD = 7.5         # mini-PROBE : 5-10 $
N_PROMUS = 2


def scorer_candidats(root: str | Path, *, coins_probe: set[str], tape: dict | None = None,
                     candidats_observes: set[str], frais_bps: float = 12.0) -> list[dict]:
    """Note chaque vault CANDIDAT_OBSERVE depuis le journal : n_open, fréquence, copyabilité, shadow net.
    `tape` = {coin: [(ts,px)]} pour le shadow (optionnel). Rend la liste triée par score décroissant."""
    from hl_observer.experimental.copy_edge_forward import rendement_forward
    root = Path(root)
    try:
        lignes = (root / JOURNAL).read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return []
    par: dict[str, dict] = {}
    for l in lignes:
        try:
            d = json.loads(l)
        except ValueError:
            continue
        v = d.get("vault")
        if not v or v not in candidats_observes or "open" not in str(d.get("dir") or "").lower():
            continue
        e = par.setdefault(v, {"vault": v, "n_open": 0, "n_copyables": 0, "shadow": [], "t0": None, "t1": None})
        e["n_open"] += 1
        coin = str(d.get("coin") or "").upper()
        if coin in coins_probe:
            e["n_copyables"] += 1
            serie = (tape or {}).get(coin)
            if serie:
                r = rendement_forward({"ts_ms": d.get("fill_ts_ms") or 0, "direction": 1}, serie, 3_600_000.0)
                if r is not None:
                    e["shadow"].append(r - frais_bps)
        ts = d.get("fill_ts_ms") or d.get("recu_ms")
        if ts:
            e["t0"] = ts if e["t0"] is None else min(e["t0"], ts)
            e["t1"] = ts if e["t1"] is None else max(e["t1"], ts)
    out = []
    for e in par.values():
        span_h = max(1e-6, ((e["t1"] or 0) - (e["t0"] or 0)) / 3_600_000.0)
        copy = e["n_copyables"] / e["n_open"] if e["n_open"] else 0.0
        shadow = sum(e["shadow"]) / len(e["shadow"]) if e["shadow"] else None
        freq = e["n_open"] / span_h
        out.append({"vault": e["vault"], "n_open": e["n_open"], "frequence_open_par_h": round(freq, 3),
                    "copyabilite": round(copy, 3), "shadow_net_bps": round(shadow, 2) if shadow is not None else None,
                    "score": round(freq * copy, 4)})
    out.sort(key=lambda x: -x["score"])
    return out


def promouvoir(candidats_scores: list[dict], *, n: int = N_PROMUS) -> dict[str, dict]:
    """Sélectionne les n meilleurs qui passent les gates min (n_open, copyabilité, shadow>0 si mesuré).
    Rend {vault: {notional_usd, raison}} — mini-PROBE. Un candidat sans shadow mesuré n'est PAS promu
    (deny-by-default : on ne promeut que ce qui montre un rendement shadow positif)."""
    promus: dict[str, dict] = {}
    for c in candidats_scores:
        if len(promus) >= n:
            break
        if (c["n_open"] >= MIN_OPEN and c["copyabilite"] >= MIN_COPYABILITE
                and c["shadow_net_bps"] is not None and c["shadow_net_bps"] > MIN_SHADOW_NET_BPS):
            promus[c["vault"]] = {"notional_usd": NOTIONAL_MINI_USD, "shadow_net_bps": c["shadow_net_bps"],
                                  "frequence_open_par_h": c["frequence_open_par_h"], "copyabilite": c["copyabilite"],
                                  "raison": "promu mini-PROBE : fréquence+copyabilité+shadow net>0"}
    return promus


def construire(root: str | Path, *, coins_probe: set[str], tape: dict, candidats_observes: set[str]) -> dict:
    scores = scorer_candidats(root, coins_probe=coins_probe, tape=tape, candidats_observes=candidats_observes)
    promus = promouvoir(scores)
    payload = {"n_candidats": len(scores), "n_promus": len(promus), "promus": promus, "classement": scores}
    (Path(root) / PROMUS).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    return payload


def charger_promus(root: str | Path) -> dict[str, dict]:
    try:
        d = json.loads((Path(root) / PROMUS).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {str(k): v for k, v in (d.get("promus") or {}).items()}


__all__ = ["scorer_candidats", "promouvoir", "construire", "charger_promus", "NOTIONAL_MINI_USD"]
