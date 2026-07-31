"""ALPHA — édredon HONNÊTE de l'edge COPYABLE d'un wallet (forward post-freeze), et classement de population.

Réutilise la machinerie de la maison (`following/scoring_robuste`) : grappes indépendantes
(`wallet:coin:jour`), borne basse bootstrap, critères CORE (≥ votes indépendants, jours, régimes,
concentration ≤ 0.35, LCB > 0). On NE réinvente pas la discipline : on la branche sur les fills du wallet.

Entrée : `leader_fills_forward.jsonl` — un enregistrement par fill copié : `{adresse, coin, side, ts_ms,
mid_at_fill, mid_forward, ecart_fill_s, ecart_forward_s}`. Le markout copyable signé = la variation de mid
entre l'instant d'action (fill + `ecart_fill_s`, l'âge du signal) et l'horizon forward, dans le sens du
trade. Coût déduit.

**Vérité des données — ce que ce tape NE permet PAS de mesurer** (jamais 0, toujours UNMEASURABLE) :
  * l'ACTION (OPEN/ADD/REDUCE/CLOSE/FLIP) : le fill brut n'a ni taille ni position courante ;
  * la CAPACITÉ : pas de taille ni de profondeur au moment du fill ;
  * le FILL RATIO / prix EXÉCUTABLE : pas de BBO/L2 du coin à l'instant d'action (surtout memecoins) ;
  * les markouts sous la seconde (100/250/500 ms) : le tape n'a qu'un seul point forward (~11 s).
Ces champs sortent en `UNMEASURABLE`, pas en valeur inventée. Ce qui EST mesurable : le markout mid-à-mid
signé, le coût, la concentration, les votes indépendants et la LCB — donc un verdict honnête.

Pur, 0 réseau, 0 ordre réel.
"""
from __future__ import annotations

import json
import statistics
from collections.abc import Mapping, Sequence
from typing import Any

from hl_observer.following.scoring_robuste import (
    CONCENTRATION_MAX,
    MIN_VOTES_INDEPENDANTS,
    agreger_en_grappes,
    borne_basse_confiance,
    critere_core,
)

FRAIS_TAKER_ROUNDTRIP_BPS = 9.0  # frais HL taker aller-retour (source unique config/frais_venues)

#: Coût round-trip réaliste par coin quand connu (frais + spread + impact typiques). Memecoins ≫ 9 bps.
#: Absent ⇒ on utilise le coût par défaut MAIS on marque le coût "OPTIMISTE_SI_ILLIQUIDE".
COUT_ROUNDTRIP_PAR_COIN_BPS: dict[str, float] = {}

UNMEASURABLE = "UNMEASURABLE"


def charger_forward(path: str, adresse: str | None = None) -> list[dict[str, Any]]:
    """Charge les enregistrements forward ; filtre sur `adresse` (préfixe insensible à la casse) si fourni."""
    a = adresse.lower() if adresse else None
    out: list[dict[str, Any]] = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            adr = str(r.get("adresse", "")).lower()
            if a and a not in adr:
                continue
            if r.get("mid_at_fill") and r.get("mid_forward") and r.get("coin") and r.get("side"):
                out.append(r)
    out.sort(key=lambda r: r.get("ts_ms", 0))
    return out


def markout_bps(rec: Mapping[str, Any]) -> float | None:
    """Markout copyable signé (mid à l'action → mid forward), en bps. `None` si non calculable."""
    m0, m1 = rec.get("mid_at_fill"), rec.get("mid_forward")
    if not (isinstance(m0, (int, float)) and isinstance(m1, (int, float)) and m0 > 0):
        return None
    sens = 1.0 if str(rec.get("side")).upper() == "LONG" else -1.0
    return sens * (m1 / m0 - 1.0) * 1e4


def _episodes(recs: Sequence[Mapping[str, Any]], *, cout_bps: float,
              cout_par_coin: Mapping[str, float] | None) -> list[dict[str, Any]]:
    """Transforme les fills en épisodes {wallet, coin, ts_ms, gross_bps, net_bps} pour la machinerie maison."""
    eps: list[dict[str, Any]] = []
    for r in recs:
        g = markout_bps(r)
        if g is None:
            continue
        coin = str(r.get("coin"))
        c = float((cout_par_coin or {}).get(coin, cout_bps))
        eps.append({
            "wallet": str(r.get("adresse")), "coin": coin, "ts_ms": r.get("ts_ms"),
            "gross_bps": round(g, 4), "net_bps": round(g - c, 4), "cout_bps": c,
        })
    return eps


def evaluer_wallet(recs: Sequence[Mapping[str, Any]], *, adresse: str = "?",
                   cout_bps: float = FRAIS_TAKER_ROUNDTRIP_BPS,
                   cout_par_coin: Mapping[str, float] | None = None) -> dict[str, Any]:
    """Ligne canonique HONNÊTE pour un wallet : votes indépendants, gross/net agrégés, LCB, concentration,
    verdict — plus les champs UNMEASURABLE que ce tape ne permet pas de mesurer."""
    cout_par_coin = cout_par_coin or COUT_ROUNDTRIP_PAR_COIN_BPS
    eps = _episodes(recs, cout_bps=cout_bps, cout_par_coin=cout_par_coin)
    if not eps:
        return {"wallet": adresse, "verdict": "MORE_DATA", "raison": "aucun markout calculable", "n_raw": 0}

    core = critere_core(eps)                                  # votes, jours, regimes, coins, LCB, concentration
    agg_g = agreger_en_grappes(eps, cle_valeur="gross_bps")   # votes gross indépendants
    agg_n = agreger_en_grappes(eps, cle_valeur="net_bps")     # votes net indépendants
    votes_net = agg_n["votes_bps"]
    net_mean = round(statistics.mean(votes_net), 4) if votes_net else None
    net_med = round(statistics.median(votes_net), 4) if votes_net else None
    gross_mean = round(statistics.mean(agg_g["votes_bps"]), 4) if agg_g["votes_bps"] else None
    lcb_net = core["borne_basse_bps"]

    par_coin: dict[str, dict[str, Any]] = {}
    for coin in {e["coin"] for e in eps}:
        v = [e["gross_bps"] for e in eps if e["coin"] == coin]
        par_coin[coin] = {"n_fills": len(v), "gross_med_bps": round(statistics.median(v), 2)}

    n_votes = core["n_votes_independants"]
    conc = core["concentration"]
    illiquide = any(c not in cout_par_coin for c in par_coin)   # coût par défaut appliqué à un coin sans source

    if n_votes < 8 or lcb_net is None:
        verdict = "MORE_DATA"
    elif lcb_net <= 0:
        verdict = "KILL"
    elif conc is not None and conc > CONCENTRATION_MAX:
        verdict = "KILL_CONCENTRE"
    elif not core["eligible_core"]:
        verdict = "FORWARD_REQUIS"        # LCB>0 mais CORE incomplet (jours/régimes/votes) — jamais promu ici
    else:
        verdict = "CANDIDAT"

    return {
        "wallet": adresse,
        "n_raw": len(eps), "n_independent": n_votes, "facteur_replication": agg_n["facteur_replication"],
        "gross_bps": gross_mean, "cout_bps": cout_bps, "net_bps_mean": net_mean, "net_bps_median": net_med,
        "lcb_net_bps": lcb_net, "concentration": conc,
        "n_jours": core["n_jours"], "n_regimes_mesures": core["n_regimes"], "n_coins": core["n_coins"],
        "par_coin": par_coin, "raisons_core": core["raisons"],
        "cout_optimiste_si_illiquide": illiquide,
        # ── champs exigés par le suivi forward mais NON mesurables sur ce tape ──
        "action_OPEN_ADD_REDUCE_CLOSE_FLIP": UNMEASURABLE,   # pas de taille/position dans le fill brut
        "capacity_usd": UNMEASURABLE,                        # pas de taille ni de profondeur
        "fill_ratio": UNMEASURABLE,                          # pas de BBO/L2 exécutable à l'instant d'action
        "markouts_sous_seconde": UNMEASURABLE,               # tape à un seul point forward (~11 s)
        "verdict": verdict, "real_execution": False,
    }


def classer_population(path: str, *, cout_bps: float = FRAIS_TAKER_ROUNDTRIP_BPS,
                       min_fills: int = 5, cout_par_coin: Mapping[str, float] | None = None) -> list[dict[str, Any]]:
    """Priorité 6 — classe TOUS les wallets du tape par NOTRE edge net copyable (pas leur PnL brut).

    Tri : d'abord ceux qui passent le plus de critères (LCB>0, votes, concentration), puis par LCB net.
    """
    par_wallet: dict[str, list[dict[str, Any]]] = {}
    for r in charger_forward(path):
        par_wallet.setdefault(str(r.get("adresse")), []).append(r)
    lignes: list[dict[str, Any]] = []
    for adr, recs in par_wallet.items():
        if len(recs) < min_fills:
            continue
        lignes.append(evaluer_wallet(recs, adresse=adr, cout_bps=cout_bps, cout_par_coin=cout_par_coin))
    rang = {"CANDIDAT": 0, "FORWARD_REQUIS": 1, "KILL_CONCENTRE": 2, "KILL": 3, "MORE_DATA": 4}

    def cle(l: dict[str, Any]) -> tuple:
        return (rang.get(l.get("verdict"), 9), -(l.get("lcb_net_bps") or -1e9))
    lignes.sort(key=cle)
    return lignes


__all__ = ["charger_forward", "markout_bps", "evaluer_wallet", "classer_population",
           "FRAIS_TAKER_ROUNDTRIP_BPS", "UNMEASURABLE"]
