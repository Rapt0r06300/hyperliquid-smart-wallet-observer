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
import os
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from hl_observer.funding.delta_neutral_carry import evaluer_carry_neutre  # noqa: E402
from hl_observer.funding.funding_persistence import estimer_persistance  # noqa: E402
from hl_observer.funding.funding_zscore import zscore_funding  # noqa: E402
from hl_observer.funding.carry_optimizer import facteur_zscore as _fzs  # noqa: E402  Y4 sizing

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
# On garde le plus HAUT levier qui reste VIABLE (survit a securite x pire-hausse). Le plancher a
# 1x/1.5x DEBLOQUE les coins volatils : HYPE (pire-h 29%) est liquide a >=2x mais VIABLE a 1x/1.5x
# (prouve). Baisser le levier = MOINS de risque, pas plus ; le carry reste funding-positif, juste
# sur plus de capital immobilise. Un carry sur DES coins a 1x bat un carry sur AUCUN coin a 2x.
LEVIERS_A_ESSAYER = (1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 7.0, 10.0)
# PLANCHER DE BREAK-EVEN — calibre sur une MESURE, pas sur une intuition (18/07).
# MESURE : le break-even d'un carry HL est ~76-88 h QUEL QUE SOIT le funding courant, parce que la
# PRIME decroit vers le plancher protocolaire (0,125 bps/h) : seul le plancher persiste. Un pic de
# funding 4x ne donne que 76 h au lieu de 88 h. Donc un plancher a 24 h aurait tue TOUS les carrys.
# On calibre a 120 h : ca laisse passer les carrys normaux (~88 h) et ecarte les ABSURDES (base tres
# negative -> cout d'entree enorme -> jamais rembourse). Reglable :
# HYPERSMART_CARRY_MAX_BREAK_EVEN_H. *** CONSEQUENCE HONNETE : un carry est NEGATIF ~3-4 jours
# (le temps de rembourser l'entree), PUIS il monte. Il faut le TENIR, pas le churner. ***
try:
    MAX_BREAK_EVEN_H = float(os.environ.get("HYPERSMART_CARRY_MAX_BREAK_EVEN_H", "120") or 120.0)
except (TypeError, ValueError):
    MAX_BREAK_EVEN_H = 120.0

PLAFOND_SHORTLIST = 12   # top-K carrys viables : on ouvre TOUS les viables (plus d'ouvertures =
#                        # plus de funding capté + plus de données pour le replay). Toujours filtré
#                        # sur l'edge NET positif : on élargit le panier, on ne baisse pas la barre.
SECURITE_LIQUIDATION = 1.5   # A3 : tampon = 1.5x la pire hausse -> risque de liquidation UNIFORME entre coins


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


def _carnet_spot(pair: str, *, impact_max: float = 0.02,
                 notional_cible: float = 0.0) -> tuple[float, float, float | None] | None:
    """LE VRAI CARNET (l2Book) -> (mid, profondeur ACHETABLE en $ sous `impact_max`, VWAP d'achat
    de `notional_cible`). Le VWAP est le VRAI prix de fill de la jambe longue pour NOTRE taille
    (slippage inclus) -> base honnete, pas le mid optimiste. Memoire : « lire le CARNET, pas le
    volume »."""
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
    reste, cout, qty = float(notional_cible), 0.0, 0.0     # pour le VWAP d'achat de notional_cible
    for niveau in lv[1]:                     # cote ASK : ce qu'on doit ACHETER pour la jambe longue
        try:
            px, sz = float(niveau["px"]), float(niveau["sz"])
        except (KeyError, TypeError, ValueError):
            continue
        if px > best_ask * (1.0 + impact_max):
            break
        val = px * sz
        profondeur += val
        if reste > 0.0:                      # on remplit notre taille niveau par niveau -> VWAP reel
            prendre = min(val, reste)
            qty += prendre / px
            cout += prendre
            reste -= prendre
    vwap = (cout / qty) if qty > 0.0 else None
    return mid, round(profondeur, 2), vwap


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


def _funding_history(coin: str, *, heures: int = 48) -> list[float]:
    """A1 : historique du funding (bps/h) sur `heures` via l'endpoint public fundingHistory.
    Le funding HL est HORAIRE (fundingRate = fraction/heure). On ne devine rien : liste vide si absent."""
    fin = int(time.time() * 1000)
    deb = fin - int(heures) * 3600 * 1000
    try:
        arr = _post({"type": "fundingHistory", "coin": coin, "startTime": deb, "endTime": fin})
    except Exception:  # noqa: BLE001
        return []
    out: list[float] = []
    for r in arr if isinstance(arr, list) else []:
        try:
            out.append(float(r["fundingRate"]) * 10_000.0)   # fraction/h -> bps/h
        except (KeyError, TypeError, ValueError):
            continue
    return out


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


#: cache derniere-valeur-connue de la pire-hausse. 24 h : tres court devant les 200 jours de la
#: statistique, tres long devant un hoquet reseau. Au-dela -> exclusion honnete (pas d'invention).
PIRE_HAUSSE_CACHE = Path("runtime") / "data" / "pire_hausse_cache.json"
PIRE_HAUSSE_CACHE_MAX_AGE_S = 24 * 3600.0


def _pire_avec_cache(root: Path, coin: str, valeur_fraiche: float | None) -> float | None:
    """Succes -> memorise et retourne. Echec -> reutilise le cache s'il a < 24 h (TRACE au log).
    Echec + cache perime/absent -> None (l'exclusion honnete d'avant). Jamais d'exception."""
    chemin = Path(root) / PIRE_HAUSSE_CACHE
    try:
        cache = json.loads(chemin.read_text(encoding="utf-8"))
        if not isinstance(cache, dict):
            cache = {}
    except (OSError, ValueError):
        cache = {}
    now = time.time()
    if valeur_fraiche is not None:
        cache[coin] = {"pire": float(valeur_fraiche), "ts": now}
        try:
            chemin.parent.mkdir(parents=True, exist_ok=True)
            chemin.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        except OSError:
            print("  (cache pire-hausse inecrivable — la mesure fraiche reste utilisee)")
        return float(valeur_fraiche)
    entree = cache.get(coin)
    if isinstance(entree, dict) and isinstance(entree.get("pire"), (int, float)):
        age = now - float(entree.get("ts") or 0.0)
        if 0 <= age <= PIRE_HAUSSE_CACHE_MAX_AGE_S:
            print("  %s : bougies ratees ce tick -> pire-hausse du CACHE (age %.1f h) — un "
                  "hoquet reseau n'ampute plus une statistique de 200 jours" % (coin, age / 3600))
            return float(entree["pire"])
    return None


def _meilleur_levier(coin, funding, base, liq, levier_max, pire, *, securite=SECURITE_LIQUIDATION):
    """A3 — LEVIER en RISK-PARITY : le plus haut levier qui survit a `securite` x la pire hausse
    observee. Exiger le MEME multiple de securite pour tous les coins egalise le risque de
    liquidation (un coin volatil recoit MOINS de levier). On ne maximise plus le levier a nu."""
    pire_stresse = max(0.0, float(pire)) * float(securite)
    best = None
    for lev in LEVIERS_A_ESSAYER:
        if levier_max and lev > levier_max:
            continue
        mr = round(1.0 / lev, 6)
        v = evaluer_carry_neutre(coin=coin, funding_bps_h=funding, base_bps=base, liquidite_spot_usd=liq,
                                 maker=True, levier_max=levier_max, marge_ratio=mr,
                                 pire_hausse_observee=pire_stresse)
        if v.viable:
            best = (lev, mr, v)
    return best


def classer_viables(viables, *, top_k: int = PLAFOND_SHORTLIST):
    """A2 : classe les viables par carry NET (gain_net_24h_bps) DECROISSANT, coupe au top-K.
    Tie-break : break-even le plus court. viables = [(coin, inp, heures, gain_net_24h_bps), ...].
    Moins de trades, plus propres : on n'ouvre que le HAUT du panier, pas tout ce qui est eligible."""
    def _cle(x):
        gain = x[3] if len(x) > 3 and x[3] is not None else -9e9
        z = x[4] if len(x) > 4 and x[4] is not None else 0.0     # A4 : a net ~egal, preferer le SPIKE
        heures = x[2] if x[2] is not None else 9e9
        return (-gain, -z, heures)
    return sorted(viables, key=_cle)[:max(1, int(top_k))]


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
        carnet = _carnet_spot(s["pair"], notional_cible=NOTIONNEL_MAX_USD)   # mid + profondeur + VWAP d'achat
        if carnet is None:
            spot_px, liq = s["mark"], 0.0             # carnet illisible -> profondeur 0 -> exclu
        else:
            mid, liq, vwap = carnet
            spot_px = vwap if (vwap and vwap > 0) else mid   # base au VRAI prix de fill (VWAP), sinon mid
        base = (p["mark"] - spot_px) / spot_px * 10_000.0 if spot_px > 0 else 9e9
        pire = pires.get(c)
        if pire is None:                       # pas de bougie locale -> on FETCH (plus de coins)
            pire = _pire_via_api(c)
        # 🔴 NUIT 19-20/07 (-0,49 $) : UN rate reseau sur candleSnapshot -> pire=None -> coin
        # declare non viable -> hors shortlist -> 45 min plus tard le store fermait une position
        # non amortie. Or la pire-hausse est une statistique sur 200 JOURS : elle ne bouge pas en
        # une heure. Un rate de fetch n'a pas le droit d'amputer une mesure quasi statique ->
        # cache derniere-valeur-connue (24 h max, trace). Echec + cache perime = exclusion
        # honnete, comme avant.
        pire = _pire_avec_cache(ROOT, c, pire)
        raison, inp = "", None
        if abs(base) > BASE_ABERRANTE_BPS:
            # AUDITABLE : on montre CE qui a été matché et POURQUOI c'est absurde (pas un bug caché,
            # mais l'absence d'un vrai spot jumelable : le plus proche reste à des ordres de grandeur).
            ratio = (max(p["mark"], spot_px) / min(p["mark"], spot_px)) if (spot_px > 0 and p["mark"] > 0) else 9e9
            raison = ("base aberrante: perp %.4g$ vs spot %s %.4g$ (x%.0f -> pas de vrai spot jumelable)"
                      % (p["mark"], s["pair"], spot_px, ratio))
        elif liq < LIQUIDITE_MIN_USD:
            raison = "spot HL trop mince (< 5k$)"
        elif p["levier_max"] <= 0:
            raison = "levier max inconnu"
        elif pire is None:
            raison = "pas de bougies -> pire-hausse non mesurable"
        else:
            # A1 : decider sur le funding PERSISTANT (resistant aux spikes) ; A4 : z-score de timing.
            hist = _funding_history(c)
            fp = estimer_persistance(c, hist)
            zf = zscore_funding(c, hist, p["funding_bps_h"])   # courant = snapshot
            funding_decision = fp.funding_persistant_bps_h if fp.fiable else p["funding_bps_h"]
            best = _meilleur_levier(c, funding_decision, base, liq, p["levier_max"], pire)
            if best is None:
                raison = "jambe perp liquidee meme a 2x (funding persistant<=cout / trop volatil)"
            else:
                lev, mr, v = best
                # PLANCHER DE BREAK-EVEN (18/07) : un carry qui met des JOURS a rembourser son cout
                # d'entree fait SAIGNER le PnL. On paie ~11 bps a l'ouverture ; au funding plancher
                # (0,125 bps/h) il faut ~88 h pour les recuperer -> on reste dans le rouge des jours.
                # On n'ouvre QUE si ca rembourse vite. Ne PAS ouvrir coute 0 ; ouvrir pour rien
                # coute 11 bps. Moins d'ouvertures, mais chacune rentable pour de vrai.
                be = v.heures_pour_rentabiliser
                if be is None or float(be) > MAX_BREAK_EVEN_H:
                    raison = ("break-even trop lent (%s h > %.0f h) : le funding ne rembourse pas le "
                              "cout d'entree assez vite -> on ATTEND (aucune saignee de couts)"
                              % (("?" if be is None else "%.0f" % float(be)), MAX_BREAK_EVEN_H))
                else:
                    inp = {"ts_ms": int(time.time() * 1000), "coin": c,
                           "funding_bps_h": round(funding_decision, 6),
                           "funding_snapshot_bps_h": round(p["funding_bps_h"], 6),
                           "funding_persistant_bps_h": round(fp.funding_persistant_bps_h, 6),
                           "funding_fiable": fp.fiable,
                           "funding_zscore": zf.zscore, "funding_regime": zf.regime,
                           "facteur_taille": round(_fzs(zf.zscore), 4),   # Y4 : + gros si funding spike
                           "base_bps": round(base, 4),
                           "break_even_h": round(float(be), 2),
                           "liquidite_spot_usd": round(liq, 2), "maker": True,
                           "levier_max": p["levier_max"], "marge_ratio": mr,
                           "pire_hausse_observee": pire, "securite_liquidation": SECURITE_LIQUIDATION,
                           "levier_utilise": lev,
                           "perp_px": round(p["mark"], 8),   # prix perp COURANT -> suivi liquidation live
                           "gain_net_24h_bps": (round(v.gain_net_24h_bps, 4)
                                                if v.gain_net_24h_bps is not None else None),
                           "source": "hyperliquid public API (perp+spot) + bougies 1h", "real_execution": False}
                    viables.append((c, inp, v.heures_pour_rentabiliser, v.gain_net_24h_bps, zf.zscore))
        rapport.append((c, p["funding_bps_h"], liq, pire, "VIABLE" if inp else raison))
    viables = classer_viables(viables)          # A2 : classe par carry NET, coupe au top-K
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
    n_viables = sum(1 for r in rapport if r[4] == "VIABLE")
    print("  %d coin(s) perp∩spot, %d VIABLE(S) (top-%d retenus par carry net)."
          % (len(rapport), n_viables, len(viables)))

    if not viables:
        print("\n  >>> Aucun carry viable maintenant (funding bas / spot mince / trop volatil). "
              "Reponse HONNETE -- le carry attend un meilleur funding.")
        return 0
    c, inp, h, gain, _z = viables[0]
    print("\n  >>> MEILLEUR : %s (net ~%+.2f bps/24h, funding %s, break-even ~%.0f h, levier %gx)"
          % (c, (gain or 0.0), inp.get("funding_regime", "?"), h or 0.0, inp["levier_utilise"]))
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
