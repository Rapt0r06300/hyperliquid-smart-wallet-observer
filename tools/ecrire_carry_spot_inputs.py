"""ECRIRE LES INPUTS SPOT DU CARRY — le chainon manquant qui affamait le carry.

═══════════════════════════════════════════════════════════════════════════════════════════════
LE PROBLEME (18/07) : le carry ne prenait AUCUNE position. `funding/carry_paper_runtime.py` lit ses
entrees dans `runtime/data/carry_spot_inputs.json` -- et **PERSONNE ne l'ecrivait** -> chaque poll
`INPUTS_SPOT_ABSENTS_NO_TRADE`. Un garde-fou AFFAME refuse tout. *Chainon manquant, personne qui se plaint.*
═══════════════════════════════════════════════════════════════════════════════════════════════

Cet outil MESURE tout et ECRIT `runtime/data/carry_spot_inputs.json` pour le MEILLEUR carry :
  * base_bps, liquidite_spot_usd, funding_bps_h  -> API publique Hyperliquid (perp + spot)
  * levier_max                                    -> meta perp (maxLeverage)
  * marge_ratio                                   -> LEVIER MAX SUR (le plus haut ou la jambe perp
                                                     survit a la pire hausse mesuree) = plus gros
                                                     notionnel => PLUS de $ de funding, sans risque en +
  * pire_hausse_observee                          -> bougies 1h (locales, ou fetchees via l'API si absentes)

🔑 AUTO (defaut) : scanne TOUS les coins perp∩spot, affiche l'univers complet (funding, liquidite,
break-even, raison d'exclusion) et ecrit celui au break-even le plus RAPIDE. break-even = cout/funding.

🔒 On ne devine RIEN (valeur non mesurable -> pas ecrite). READ-ONLY marche : aucun ordre, aucune
signature. Le carry reste PAPER (le noyau garde l'autorite).

Usage :  python tools/ecrire_carry_spot_inputs.py            (AUTO : univers + meilleur coin)
         python tools/ecrire_carry_spot_inputs.py --diagnostic   (n'ecrit rien, montre juste l'univers)
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hl_observer.funding.delta_neutral_carry import evaluer_carry_neutre  # noqa: E402

API = "https://api.hyperliquid.xyz/info"
INPUTS_PATH = ROOT / "runtime" / "data" / "carry_spot_inputs.json"
SHORTLIST_PATH = ROOT / "runtime" / "data" / "carry_spot_shortlist.json"   # TOUS les viables (parallele)
CANDLES_1H = ROOT / "runtime" / "history" / "candles_1h.jsonl"

BASE_ABERRANTE_BPS = 100_000.0
FENETRE_H = 720
# PLANCHER DE LIQUIDITE, principiel (plus de nombre arbitraire) : notre notionnel MAX est
# marge $50 x levier 10 = $500. On exige 5x ce notionnel en profondeur REELLE (l2Book, sous 2%
# d'impact) pour construire les 2 jambes sans se pousser soi-meme. -> 2500$ = le plancher du
# MODELE lui-meme (delta_neutral_carry.LIQUIDITE_SPOT_MIN_USD), donc AUCUN double standard.
NOTIONNEL_MAX_USD = 500.0
SECURITE_PROFONDEUR = 5.0
LIQUIDITE_MIN_USD = NOTIONNEL_MAX_USD * SECURITE_PROFONDEUR   # 2500$ (au lieu d'un 5000 arbitraire)
LEVIERS_A_ESSAYER = (2.0, 3.0, 4.0, 5.0, 7.0, 10.0)   # on garde le plus HAUT qui reste viable


def _post(payload: dict, *, timeout: float = 15.0):
    req = urllib.request.Request(API, data=json.dumps(payload).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def _perps() -> dict[str, dict]:
    meta, ctx = _post({"type": "metaAndAssetCtxs"})
    out: dict[str, dict] = {}
    for a, c in zip(meta.get("universe") or [], ctx or []):
        nom = str(a.get("name") or "").upper()
        if nom and isinstance(c, dict):
            try:
                out[nom] = {"funding_bps_h": float(c.get("funding") or 0.0) * 10_000.0,
                            "mark": float(c.get("markPx") or 0.0),
                            "levier_max": float(a.get("maxLeverage") or 0.0)}
            except (TypeError, ValueError):
                pass
    return out


def _spots() -> dict[str, list[dict]]:
    """base -> [{mark(du ctx), vol24, pair(nom de paire pour le l2Book)}, ...]. Join par NOM.
    On garde TOUTES les paires candidates du meme ticker (le scanner choisira ensuite celle dont
    le prix colle au perp -> tue les 'base aberrante' dues a une collision de nom / paire stale)."""
    spot = _post({"type": "spotMetaAndAssetCtxs"})
    sm, sc = (spot[0], spot[1]) if isinstance(spot, list) and len(spot) == 2 else ({}, [])
    tok = {int(t["index"]): str(t.get("name") or "").upper() for t in (sm.get("tokens") or []) if "index" in t}
    p2b = {}
    for pr in sm.get("universe") or []:
        idx = pr.get("tokens") or []
        b = tok.get(idx[0]) if idx else None
        if pr.get("name") and b:
            p2b[str(pr["name"])] = b
    out: dict[str, list[dict]] = {}
    for c in sc or []:
        if not isinstance(c, dict):
            continue
        pair = str(c.get("coin") or "")
        b = p2b.get(pair)
        if not b:
            continue
        try:
            px, vol = float(c.get("markPx") or c.get("midPx") or 0.0), float(c.get("dayNtlVlm") or 0.0)
        except (TypeError, ValueError):
            continue
        if px > 0:
            out.setdefault(b, []).append({"mark": px, "vol24": vol, "pair": pair})
    return out


def _carnet_spot(pair: str, *, impact_max: float = 0.02) -> tuple[float, float] | None:
    """LE VRAI CARNET (l2Book) -> (mid, profondeur ACHETABLE en $ sous `impact_max`).
    On mesure ce qu'on peut REELLEMENT acheter, pas un proxy de volume 24h. Memoire : « lire le
    CARNET, pas le volume »."""
    try:
        book = _post({"type": "l2Book", "coin": pair})
    except Exception:  # noqa: BLE001
        return None
    lv = book.get("levels") if isinstance(book, dict) else None
    if not lv or len(lv) < 2 or not lv[0] or not lv[1]:
        return None
    try:
        best_bid = float(lv[0][0]["px"]); best_ask = float(lv[1][0]["px"])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if best_bid <= 0 or best_ask <= 0:
        return None
    mid = (best_bid + best_ask) / 2.0
    profondeur = 0.0
    for niveau in lv[1]:                     # cote ASK : ce qu'on doit ACHETER pour la jambe longue
        try:
            px, sz = float(niveau["px"]), float(niveau["sz"])
        except (KeyError, TypeError, ValueError):
            continue
        if px > best_ask * (1.0 + impact_max):
            break
        profondeur += px * sz
    return mid, round(profondeur, 2)


def _pire_hausse(highs: list[float], lows: list[float]) -> float | None:
    if len(lows) < 24:
        return None
    lo, hi = lows[-FENETRE_H:], highs[-FENETRE_H:]
    pire, mn = 0.0, lo[0]
    for i in range(len(hi)):
        mn = min(mn, lo[i])
        if mn > 0:
            pire = max(pire, (hi[i] - mn) / mn)
    return round(pire, 6)


def _pires_locales() -> dict[str, float]:
    if not CANDLES_1H.exists():
        return {}
    lo: dict[str, list] = {}
    hi: dict[str, list] = {}
    for l in CANDLES_1H.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            d = json.loads(l); co = str(d.get("coin") or "").upper()
            lo.setdefault(co, []).append(float(d["l"])); hi.setdefault(co, []).append(float(d["h"]))
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
    return {co: v for co in lo if (v := _pire_hausse(hi[co], lo[co])) is not None}


def _pire_via_api(coin: str) -> float | None:
    """Bougies 1h fetchees pour un coin SANS bougie locale -> plus de coins evaluables."""
    fin = int(time.time() * 1000)
    deb = fin - FENETRE_H * 3600 * 1000
    try:
        arr = _post({"type": "candleSnapshot",
                     "req": {"coin": coin, "interval": "1h", "startTime": deb, "endTime": fin}})
    except Exception:  # noqa: BLE001
        return None
    hi = [float(c["h"]) for c in arr if isinstance(c, dict) and "h" in c]
    lo = [float(c["l"]) for c in arr if isinstance(c, dict) and "l" in c]
    return _pire_hausse(hi, lo)


def _meilleur_levier(coin, funding, base, liq, levier_max, pire):
    """Le LEVIER MAX SUR : le plus haut ou la jambe perp survit encore a la pire hausse.
    Plus gros notionnel = plus de $ de funding, sans ajouter de risque de liquidation."""
    best = None
    for lev in LEVIERS_A_ESSAYER:
        if levier_max and lev > levier_max:
            continue
        mr = round(1.0 / lev, 6)
        v = evaluer_carry_neutre(coin=coin, funding_bps_h=funding, base_bps=base, liquidite_spot_usd=liq,
                                 maker=True, levier_max=levier_max, marge_ratio=mr, pire_hausse_observee=pire)
        if v.viable:
            best = (lev, mr, v)
    return best


def scanner(diagnostic: bool):
    perps, spots, pires = _perps(), _spots(), _pires_locales()
    communs = sorted(set(perps) & set(spots))
    rapport, viables = [], []
    for c in communs:
        p = perps[c]
        cands = [x for x in spots.get(c, []) if x["mark"] > 0]
        if p["mark"] <= 0 or not cands:
            continue
        # MAPPING PAR PRIX : parmi les paires spot du meme ticker, prendre celle dont le prix
        # colle au perp (tue les "base aberrante" dues a une collision de nom / paire stale).
        s = min(cands, key=lambda x: abs(x["mark"] - p["mark"]) / p["mark"])
        carnet = _carnet_spot(s["pair"])              # LE VRAI CARNET spot (mid + profondeur reelle)
        if carnet is None:
            spot_px, liq = s["mark"], 0.0             # carnet illisible -> profondeur 0 -> exclu
        else:
            spot_px, liq = carnet
        base = (p["mark"] - spot_px) / spot_px * 10_000.0 if spot_px > 0 else 9e9
        pire = pires.get(c)
        if pire is None:                       # pas de bougie locale -> on FETCH (plus de coins)
            pire = _pire_via_api(c)
        raison, inp = "", None
        if abs(base) > BASE_ABERRANTE_BPS:
            raison = "base aberrante (mapping casse)"
        elif liq < LIQUIDITE_MIN_USD:
            raison = "spot HL trop mince (< 5k$)"
        elif p["levier_max"] <= 0:
            raison = "levier max inconnu"
        elif pire is None:
            raison = "pas de bougies -> pire-hausse non mesurable"
        else:
            best = _meilleur_levier(c, p["funding_bps_h"], base, liq, p["levier_max"], pire)
            if best is None:
                raison = "jambe perp liquidee meme a 2x (trop volatil / funding<=cout)"
            else:
                lev, mr, v = best
                inp = {"ts_ms": int(time.time() * 1000), "coin": c,
                       "funding_bps_h": round(p["funding_bps_h"], 6), "base_bps": round(base, 4),
                       "liquidite_spot_usd": round(liq, 2), "maker": True,
                       "levier_max": p["levier_max"], "marge_ratio": mr,
                       "pire_hausse_observee": pire, "levier_utilise": lev,
                       "source": "hyperliquid public API (perp+spot) + bougies 1h", "real_execution": False}
                viables.append((c, inp, v.heures_pour_rentabiliser))
        rapport.append((c, p["funding_bps_h"], liq, pire, "VIABLE" if inp else raison))
    viables.sort(key=lambda x: (x[2] if x[2] is not None else 9e9))
    return rapport, viables


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--diagnostic", action="store_true", help="montre l'univers, n'ecrit rien")
    a = ap.parse_args()
    try:
        rapport, viables = scanner(a.diagnostic)
    except Exception as exc:  # noqa: BLE001
        print(f"  ECHEC : {exc}")
        return 1

    print("  === UNIVERS CARRY (tous les coins perp∩spot Hyperliquid) ===")
    print("    %-8s %10s %12s %9s  %s" % ("coin", "funding/h", "spot liq $", "pire-h", "statut"))
    for c, f, liq, pire, st in sorted(rapport, key=lambda x: -x[1]):
        ph = "--" if pire is None else "%.0f%%" % (pire * 100)
        print("    %-8s %+9.3fb %12s %9s  %s" % (c, f, "%.0fk" % (liq / 1e3), ph, st))
    print("  %d coin(s) perp∩spot, %d VIABLE(S)." % (len(rapport), len(viables)))

    if not viables:
        print("\n  >>> Aucun carry viable maintenant (funding bas / spot mince / trop volatil). "
              "Reponse HONNETE -- le carry attend un meilleur funding.")
        return 0
    c, inp, h = viables[0]
    print("\n  >>> MEILLEUR : %s (break-even ~%.0f h, funding %+.3f bps/h, levier %gx)"
          % (c, h or 0.0, inp["funding_bps_h"], inp["levier_utilise"]))
    if a.diagnostic:
        print("  (--diagnostic : rien ecrit)")
        return 0
    INPUTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    INPUTS_PATH.write_text(json.dumps(inp, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  ECRIT : {INPUTS_PATH.relative_to(ROOT)} -> le carry decide sur du mesure.")
    # SHORTLIST : TOUS les viables (pas juste le #1) -> le carry en ouvre plusieurs EN PARALLELE
    # (plus de funding capture + risque diversifie). Le runtime ouvre une position par coin viable.
    shortlist = [v[1] for v in viables]
    SHORTLIST_PATH.write_text(json.dumps(shortlist, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"  ECRIT : {SHORTLIST_PATH.relative_to(ROOT)} -> {len(shortlist)} carry(s) viable(s) en parallele.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
