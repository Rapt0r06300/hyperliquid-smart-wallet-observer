"""COLLECTEUR DE CARNET (bid/ask + profondeur) — LA donnée qui manquait à l'arbitrage.

POURQUOI (Levier 3, 22/07)
--------------------------
Le +0,54 $ d'arbitrage était mesuré au MID ; au prix EXÉCUTABLE il perd (−2,7 $). La cause : on
n'a jamais capturé le CARNET (meilleur bid, meilleur ask, tailles). Sans lui, tout « écart » est
théorique. Ce collecteur capture le haut de carnet des DEUX venues pour les coins réellement
dislocés, et calcule l'écart EXÉCUTABLE (acheter à l'ask d'une venue, vendre au bid de l'autre).
C'est exactement ce que `arb_executable` réclame pour être une mesure, plus un modèle.

RELIABLE, PAS DU HAMMERING
--------------------------
`l2Book` est PAR coin : capturer 206 coins par tick ferait bannir. On borne aux N coins les plus
dislocés (lus de `dispersion_venues.jsonl`), avec limiteur de débit + backoff+jitter (socle
`collecte_fiable`). Se faire couper = MOINS de données ; on préfère durer. Chaque ligne est
estampillée (provenance) et passe la porte de qualité (prix > 0, écart plausible). Dédup incluse.

READ-ONLY / PAPER-ONLY : lire un carnet public n'est pas passer un ordre.
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

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import collecte_fiable as CF  # noqa: E402

URL_HL = "https://api.hyperliquid.xyz/info"
URL_BIN_DEPTH = "https://fapi.binance.com/fapi/v1/depth"

SORTIE = Path("runtime") / "data" / "carnet_venues.jsonl"
DISPERSION = Path("runtime") / "data" / "dispersion_venues.jsonl"
N_COINS_PRIORITAIRES = 15        # borné : on capture le carnet là où l'écart est le plus vif
N_COINS_PREMIUM_FUNDING = 18     # 23/07 : + les cibles du carry cross-venue (premium de funding)
PREMIUM_PLAUSIBLE_MAX_BPS_H = 5.0  # |hl−bin| > 5 bps/h (~438 %/an) = artefact probable, ignoré
#: 🟢 23/07 (nouveau cap) — MID-CAPS À CARRY PROPRE ET PERSISTANT, mesurés par le juge signé
#: (17-23 %/an, persist 96-100 %, base < 2,5 bps) MAIS ratés par la sélection au |premium| (leur
#: premium ~0,2 bph est plus PETIT que les spikes d'alts type GAS -> jamais dans le top-N). Or ce
#: sont les SEULS costables-manquants qui comptent. On les capte TOUJOURS, en plus de l'union.
CIBLES_CARRY_PERSISTANT = ("DASH", "INJ", "VIRTUAL", "NEO", "RUNE", "FET", "AR", "GMT", "YGG", "KAS")
ECART_PLAUSIBLE_MAX_BPS = 500.0  # au-delà = mauvais appariement (cf. arb_executable)
INTERVALLE_S_DEFAUT = 60.0


# ─────────────────────────────── priorité : où l'écart est vif ───────────────────────────────

def coins_prioritaires(lignes: list[dict], *, n: int = N_COINS_PRIORITAIRES) -> list[str]:
    """Les N coins au plus gros |écart de prix| PLAUSIBLE (les autres n'ont rien à arbitrer).
    On lit les lignes de dispersion récentes ; un écart aberrant est ignoré (pas d'appariement fou)."""
    pire: dict[str, float] = {}
    for r in lignes or ():
        c = str(r.get("coin") or "").upper()
        e = r.get("ecart_prix_bps")
        if c and isinstance(e, (int, float)) and abs(float(e)) <= ECART_PLAUSIBLE_MAX_BPS:
            pire[c] = max(pire.get(c, 0.0), abs(float(e)))
    return [c for c, _ in sorted(pire.items(), key=lambda kv: -kv[1])[: int(n)]]


def coins_premium_funding(lignes: list[dict], *, n: int = N_COINS_PREMIUM_FUNDING) -> list[str]:
    """🟠 23/07 — Les N coins au plus fort |premium de funding| (hl_bps_h − bin_bps_h) : les cibles
    du CARRY cross-venue. Le carnet ne suivait que la dislocation de PRIX (arb) → il RATAIT les coins
    rentables en carry (DASH/NEO/INJ : premium de funding fort mais prix peu disloqué), donc on ne
    pouvait pas les COSTER, donc le backtest carry les excluait. On les ajoute ici. Premium aberrant
    (> plafond ≈ artefact d'unité) ignoré : deny-by-default."""
    prem: dict[str, float] = {}
    for r in lignes or ():
        c = str(r.get("coin") or "").upper()
        try:
            p = abs(float(r["hl_bps_h"]) - float(r["bin_bps_h"]))
        except (KeyError, TypeError, ValueError):
            continue
        if c and p <= PREMIUM_PLAUSIBLE_MAX_BPS_H:
            prem[c] = max(prem.get(c, 0.0), p)
    return [c for c, _ in sorted(prem.items(), key=lambda kv: -kv[1])[: int(n)]]


# ─────────────────────────────── parseurs de carnet (tolérants) ───────────────────────────────

def parser_book_hl(rep: Any) -> tuple[float, float, float, float] | None:
    """(bid, ask, taille_bid, taille_ask) depuis `l2Book`. Format : {'levels': [bids, asks]},
    chaque niveau {'px','sz'}. Illisible / vide -> None (jamais un prix inventé)."""
    try:
        niveaux = rep.get("levels") if isinstance(rep, dict) else None
        bids, asks = niveaux[0], niveaux[1]
        bid, bsz = float(bids[0]["px"]), float(bids[0]["sz"])
        ask, asz = float(asks[0]["px"]), float(asks[0]["sz"])
    except (TypeError, ValueError, KeyError, IndexError):
        return None
    if bid > 0 and ask > 0 and ask >= bid:
        return bid, ask, bsz, asz
    return None


def parser_depth_binance(rep: Any) -> tuple[float, float, float, float] | None:
    """(bid, ask, taille_bid, taille_ask) depuis /fapi/v1/depth : {'bids':[[px,sz]],'asks':[...]}."""
    try:
        bid, bsz = float(rep["bids"][0][0]), float(rep["bids"][0][1])
        ask, asz = float(rep["asks"][0][0]), float(rep["asks"][0][1])
    except (TypeError, ValueError, KeyError, IndexError):
        return None
    if bid > 0 and ask > 0 and ask >= bid:
        return bid, ask, bsz, asz
    return None


def demi_spread_bps(bid: float, ask: float) -> float:
    """Le demi-spread en bps : (ask − bid) / 2 / mid × 1e4. C'est le coût RÉEL de franchissement."""
    mid = (bid + ask) / 2.0
    return round((ask - bid) / 2.0 / mid * 1e4, 4) if mid > 0 else 0.0


def ligne_carnet(coin: str, hl: tuple, binance: tuple) -> dict:
    """Une observation de carnet des DEUX venues + l'écart EXÉCUTABLE (pas le mid) dans les deux
    sens : acheter HL / vendre Binance, et l'inverse. C'est la vraie matière de calibration arb."""
    hb, ha, hbz, haz = hl
    bb, ba, bbz, baz = binance
    hmid, bmid = (hb + ha) / 2.0, (bb + ba) / 2.0
    ref = (hmid + bmid) / 2.0 or 1.0
    # acheter au plus bas ask, vendre au plus haut bid : l'écart EXÉCUTABLE réel
    achat_hl = round((bb - ha) / ref * 1e4, 4)      # long HL (ask), short BIN (bid)
    achat_bin = round((hb - ba) / ref * 1e4, 4)     # long BIN (ask), short HL (bid)
    return {"coin": coin, "hl_bid": hb, "hl_ask": ha, "bin_bid": bb, "bin_ask": ba,
            "hl_demi_spread_bps": demi_spread_bps(hb, ha),
            "bin_demi_spread_bps": demi_spread_bps(bb, ba),
            "taille_min_usd": round(min(hbz * hmid, haz * hmid, bbz * bmid, baz * bmid), 2),
            "ecart_executable_max_bps": round(max(achat_hl, achat_bin), 4)}


# ─────────────────────────────── réseau (borné, poli) ───────────────────────────────

def _post_hl(coin: str, *, timeout_s: float = 8.0) -> Any:
    corps = json.dumps({"type": "l2Book", "coin": coin}).encode("utf-8")
    req = urllib.request.Request(URL_HL, data=corps, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:      # noqa: S310 (URL constante)
        return json.loads(rep.read().decode("utf-8"))


def _get_binance(coin: str, *, timeout_s: float = 8.0) -> Any:
    url = "%s?symbol=%sUSDT&limit=5" % (URL_BIN_DEPTH, coin)
    with urllib.request.urlopen(url, timeout=timeout_s) as rep:      # noqa: S310
        return json.loads(rep.read().decode("utf-8"))


def une_passe(root: Path, coins: list[str], *, limiteur: CF.Limiteur | None = None,
              cache: CF.CacheDedup | None = None,
              post_hl=_post_hl, get_binance=_get_binance) -> int:
    """Capture le carnet des `coins` sur les deux venues, écrit les lignes PROPRES. Rend le
    nombre écrit. `post_hl`/`get_binance` injectables (tests). Un coin illisible est sauté."""
    limiteur = limiteur if limiteur is not None else CF.Limiteur(0.15)
    brutes: list[dict] = []
    for coin in coins:
        limiteur.attente()
        try:
            hl = parser_book_hl(post_hl(coin))
            bn = parser_depth_binance(get_binance(coin))
        except (urllib.error.URLError, OSError, ValueError, TimeoutError):
            continue                              # réseau : on saute, backoff géré par l'appelant
        if hl and bn:
            brutes.append(ligne_carnet(coin, hl, bn))
    propres = CF.collecter_proprement(
        brutes, source="carnet_hl_bin", champs_cle=("coin", "hl_bid", "bin_bid"),
        cache=cache, champs_prix=("hl_bid", "hl_ask", "bin_bid", "bin_ask"),
        ecart_bps_max=ECART_PLAUSIBLE_MAX_BPS, champ_ecart="ecart_executable_max_bps")
    if propres:
        CF.append_jsonl(root / SORTIE, propres)
    return len(propres)


def _lire_dispersion_recente(root: Path, *, max_lignes: int = 5000) -> list[dict]:
    p = root / DISPERSION
    try:
        lignes = p.read_text(encoding="utf-8", errors="ignore").splitlines()[-max_lignes:]
    except OSError:
        return []
    out = []
    for l in lignes:
        l = l.strip()
        if l:
            try:
                d = json.loads(l)
                if isinstance(d, dict):
                    out.append(d)
            except ValueError:
                continue
    return out


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collecteur de carnet bid/ask (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    p.add_argument("--n-coins", type=int, default=N_COINS_PRIORITAIRES)
    p.add_argument("--n-premium", type=int, default=N_COINS_PREMIUM_FUNDING)
    p.add_argument("--intervalle", type=float, default=INTERVALLE_S_DEFAUT)
    p.add_argument("--une-fois", action="store_true")
    a = p.parse_args(argv)
    root = Path(a.root)
    limiteur, cache = CF.Limiteur(0.15), CF.CacheDedup()
    total, echecs = 0, 0
    while True:
        lignes = _lire_dispersion_recente(root)
        # UNION arb (dislocation de prix) + carry (premium de funding) — dédupliquée, ordre stable.
        vus: dict[str, None] = {}
        # UNION : dislocation de prix (arb) + premium de funding (carry) + les mid-caps à carry
        # PERSISTANT qu'on veut TOUJOURS coster (sinon les meilleurs profils restent incostables).
        for c in (coins_prioritaires(lignes, n=a.n_coins)
                  + coins_premium_funding(lignes, n=a.n_premium)
                  + list(CIBLES_CARRY_PERSISTANT)):
            vus.setdefault(c, None)
        coins = list(vus)
        if not coins:
            print("[carnet] aucun coin disloque a suivre ce tour (dispersion vide/plate)", flush=True)
        else:
            try:
                n = une_passe(root, coins, limiteur=limiteur, cache=cache)
                total += n
                echecs = 0
                print("[carnet] %s  ecrits=%d  cumul=%d  (%d coins prioritaires)"
                      % (time.strftime("%H:%M:%S"), n, total, len(coins)), flush=True)
            except Exception as exc:  # noqa: BLE001 — on ne meurt pas, on recule
                echecs += 1
                d = CF.backoff_jitter(echecs)
                print("[carnet] erreur (%s) — backoff %.1fs" % (str(exc)[:60], d), flush=True)
                time.sleep(d)
        if a.une_fois:
            return 0
        time.sleep(max(30.0, float(a.intervalle)))


if __name__ == "__main__":
    raise SystemExit(main())
