"""COLLECTEUR DE DISPERSION DE FUNDING ENTRE VENUES — la dernière piste ouverte.

Protocole et critères de rejet : `docs/audit/PROTOCOLE_CROSS_VENUE.md`, écrit AVANT la première
donnée. Ce collecteur ne juge rien : il OBSERVE et ENREGISTRE. Le verdict est rendu par
`tools/mesurer_dispersion_venues.py`, contre des barres fixées à l'avance.

CE QU'IL FAIT
-------------
Toutes les N secondes, il lit le funding de chaque coin sur les deux venues et écrit une ligne
horodatée dans `runtime/data/dispersion_venues.jsonl` :

    {"ts": ..., "coin": "BTC", "hl_bps_h": 0.125, "bin_bps_h": 0.42, "dispersion_bps_h": 0.295}

PIÈGE D'UNITÉ, DÉJÀ PAYÉ ICI (13/07 : « 38 % APR qui étaient l'intervalle de funding »)
--------------------------------------------------------------------------------------
**Hyperliquid paie le funding PAR HEURE. Binance le paie PAR 8 HEURES.** Comparer les deux taux
bruts, c'est se tromper d'un facteur 8 — et 8× sur un funding, ça transforme une piste morte en
pépite imaginaire. La conversion est faite ICI, une seule fois, et elle est testée.

CE QU'IL N'INVENTE PAS
----------------------
Un funding illisible sur une venue -> la ligne n'est PAS écrite. Pas de zéro de remplissage, pas
de report de la valeur précédente : un trou honnête vaut mieux qu'une donnée fabriquée, parce
qu'une dispersion calculée contre un zéro inventé serait énorme et fausse.

READ-ONLY : deux endpoints publics. Aucune clé, aucune signature, aucun ordre. Binance n'est
qu'une SOURCE DE PRIX — Hyperliquid reste la seule venue des décisions paper.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

URL_HL = "https://api.hyperliquid.xyz/info"
URL_BINANCE = "https://fapi.binance.com/fapi/v1/premiumIndex"

#: 🔴 Binance publie un funding par 8 h. HL paie par heure. Facteur 8, une seule fois, ici.
HEURES_PAR_PERIODE_BINANCE = 8.0

SORTIE = Path("runtime") / "data" / "dispersion_venues.jsonl"
# 21/07 — LE BLOCAGE DE L'ARBITRAGE : on ne surveillait que 10 MAJORS, c'est-a-dire
# precisement les marches les PLUS efficients (ecart max mesure : 8,9 bps sur 30 h, seuil
# d'ouverture 35). Les dislocations vivent sur les alts moins suivis. Univers x4 : meme
# cout reseau (2 appels globaux, les deux venues renvoient TOUT), 4x plus de chances.
COINS_DEFAUT = ("BTC,ETH,SOL,HYPE,AVAX,LINK,DOGE,SUI,ARB,OP,"
                "APT,ATOM,BNB,NEAR,LTC,XRP,ADA,TRX,DOT,FIL,"
                "INJ,TIA,SEI,STX,RUNE,AAVE,MKR,CRV,LDO,ENA,"
                "WIF,PEPE,BONK,ORDI,JUP,PYTH,BLUR,GMX,SNX,COMP")
# 21/07 — CADENCE x5 (300 -> 60 s). Mesure du jour : sur 874 ecarts enregistres, la
# convergence se joue en MOINS D'UNE HEURE (|ecart| -2,26 bps a 30 min). A 5 min
# d'echantillonnage, une dislocation de 20 bps qui dure 3 minutes est purement INVISIBLE —
# or c'est exactement celle qu'un arbitrage capture. Le cout reseau ne bouge presque pas :
# une passe = 2 appels publics, quel que soit le nombre de coins.
INTERVALLE_S_DEFAUT = 60.0


def _get(url: str, *, timeout_s: float = 12.0):
    with urllib.request.urlopen(url, timeout=timeout_s) as rep:      # noqa: S310 (URL constante)
        return json.loads(rep.read().decode("utf-8"))


def _post(url: str, charge: dict, *, timeout_s: float = 12.0):
    corps = json.dumps(charge).encode("utf-8")
    req = urllib.request.Request(url, data=corps,
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout_s) as rep:      # noqa: S310
        return json.loads(rep.read().decode("utf-8"))


def donnees_hyperliquid() -> dict[str, dict]:
    """{coin: {"f": funding bps/h, "px": mark}}. Le MEME appel portait deja le prix — le
    mecanisme d'arbitrage (21/07) le lit sans un octet reseau de plus."""
    data = _post(URL_HL, {"type": "metaAndAssetCtxs"})
    if not isinstance(data, list) or len(data) < 2:
        return {}
    univers = (data[0] or {}).get("universe") or []
    ctxs = data[1] or []
    out: dict[str, dict] = {}
    for meta, ctx in zip(univers, ctxs):
        try:
            coin = str(meta.get("name") or "").upper()
            f = float((ctx or {}).get("funding"))
            px = float((ctx or {}).get("markPx") or 0.0)
        except (TypeError, ValueError, AttributeError):
            continue
        if coin and f == f:                       # NaN écarté
            out[coin] = {"f": f * 1e4, "px": px if px > 0 else None}
    return out


def funding_hyperliquid() -> dict[str, float]:
    """Compat : {coin: funding bps/h}."""
    return {c: d["f"] for c, d in donnees_hyperliquid().items()}


def donnees_binance() -> dict[str, dict]:
    """{coin: {"f": bps/h, "px": markPrice}}. ⚠️ funding Binance = PAR 8 H -> /8."""
    data = _get(URL_BINANCE)
    if not isinstance(data, list):
        return {}
    out: dict[str, dict] = {}
    for row in data:
        try:
            sym = str(row.get("symbol") or "")
            if not sym.endswith("USDT"):
                continue
            f8 = float(row.get("lastFundingRate"))
            px = float(row.get("markPrice") or 0.0)
        except (TypeError, ValueError, AttributeError):
            continue
        if f8 != f8:
            continue
        out[sym[:-4].upper()] = {"f": (f8 / HEURES_PAR_PERIODE_BINANCE) * 1e4,
                                 "px": px if px > 0 else None}
    return out


def funding_binance() -> dict[str, float]:
    """Compat : {coin: funding bps/h}."""
    return {c: d["f"] for c, d in donnees_binance().items()}


#: ── MÉCANISME D'ARBITRAGE (21/07, demande de Flo — recherche X/GitHub) ──────────────────
#: La littérature des desks : « les spreads normalisés entre le MÊME perp sur deux venues
#: REVIENNENT à leur moyenne » (dislocation de prix). MESURE d'abord : quand l'écart de prix
#: HL↔Binance dépasse le seuil PRÉ-DÉCLARÉ ci-dessous, on émet un CANDIDAT `arbitrage` dans
#: le replay (fade côté HL : short HL si HL est riche, long sinon). Le laboratoire jugera
#: aux mêmes portes (2 moitiés + stress + plateau). Barres AVANT la donnée, jamais après.
SEUIL_CANDIDAT_ARB_BPS = 20.0
#: au-delà, ce n'est pas une dislocation mais un mauvais appariement de paires (cf. arb_executable).
ECART_PLAUSIBLE_MAX_BPS = 500.0
CANDIDATS_ARB_MAX_BYTES = 20_000_000
CANDIDATS_ARB_MAX_LINES = 200_000


def une_passe(root: Path, coins: list[str]) -> tuple[int, int]:
    """(lignes écrites, coins comparables). Une venue muette -> 0 ligne, jamais d'invention."""
    try:
        dhl, dbin = donnees_hyperliquid(), donnees_binance()
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return 0, 0
    if not dhl or not dbin:
        return 0, 0

    maintenant = time.time()
    # 🟢 LEVIER 1 (22/07) — UNIVERS COMPLET, quasi GRATUIT. Les 2 venues renvoient DEJA le funding
    # + le mid de TOUS leurs coins dans les memes 2 appels (cf. `donnees_hyperliquid`). Le filtre a
    # ~38 coins nous cachait exactement les coins CHAUDS ou vit l'edge : vraie demande longue ->
    # funding au-dessus du plancher (le carry n'existe QUE la), et dislocations de prix plus vives.
    # "*" ou liste vide => on ecrit l'INTERSECTION des deux venues (tout ce qui est arbitrable).
    if not coins or "*" in coins:
        cible = sorted(set(dhl) & set(dbin))
    else:
        cible = [c.upper().strip() for c in coins]
    lignes, candidats_arb = [], []
    for coin in cible:
        c = coin.upper().strip()
        da, db = dhl.get(c), dbin.get(c)
        if not da or not db:
            continue                              # coin absent d'une venue -> on n'ecrit RIEN
        a, b = da["f"], db["f"]
        ligne = {"ts": round(maintenant, 3), "coin": c,
                 "hl_bps_h": round(float(a), 6), "bin_bps_h": round(float(b), 6),
                 "dispersion_bps_h": round(abs(float(a) - float(b)), 6),
                 "venue_haute": "BINANCE" if b > a else "HL",
                 "read_only": True, "real_execution": False}
        # dislocation de PRIX du meme perp (les deux mids etaient deja dans les reponses)
        if da.get("px") and db.get("px"):
            ecart = (float(da["px"]) - float(db["px"])) / float(db["px"]) * 1e4
            ligne["hl_px"] = da["px"]
            ligne["bin_px"] = db["px"]
            ligne["ecart_prix_bps"] = round(ecart, 4)
            # 🔴 22/07 — QUALITÉ À LA SOURCE. 35 % des candidats d'arb étaient des appariements
            # ABERRANTS (|écart| jusqu'à 1 670 000 bps : perp HL vs perp Binance mal jumelés). On
            # ne les émet PLUS comme candidats : un calibrage nourri de poubelle ment. La ligne de
            # dispersion, elle, garde l'écart brut (traçable), mais le CANDIDAT exige la plausibilité.
            if SEUIL_CANDIDAT_ARB_BPS <= abs(ecart) <= ECART_PLAUSIBLE_MAX_BPS:
                candidats_arb.append({
                    "recorded_at": round(maintenant, 3), "strategie": "arbitrage",
                    "action_type": "FADE_DISLOCATION_HL",
                    "coin": c, "direction": "SHORT" if ecart > 0 else "LONG",
                    "current_mid": da["px"], "ecart_prix_bps": round(ecart, 4),
                    "venue_riche": "HL" if ecart > 0 else "BINANCE",
                    "note": "jambe HL seule mesuree; la couverture binance est conceptuelle",
                    "real_execution": False})
        lignes.append(ligne)
    if candidats_arb:
        try:
            import sys as _s
            _s.path.insert(0, str(root / "src"))
            from hl_observer.runtime.replay_recorder import append_replay_lines
            append_replay_lines(root / "runtime" / "replay", "candidates.jsonl",
                                candidats_arb, max_bytes=CANDIDATS_ARB_MAX_BYTES,
                                max_lines=CANDIDATS_ARB_MAX_LINES)
            print("[venues] %d candidat(s) ARBITRAGE emis (dislocation >= %.0f bps)"
                  % (len(candidats_arb), SEUIL_CANDIDAT_ARB_BPS))
        except Exception as exc:  # noqa: BLE001 — la mesure funding ne depend pas du replay
            print("[venues] candidats arb non ecrits : %s" % exc)
    if not lignes:
        return 0, 0
    chemin = root / SORTIE
    chemin.parent.mkdir(parents=True, exist_ok=True)
    try:
        with chemin.open("a", encoding="utf-8") as fh:
            for l in lignes:
                fh.write(json.dumps(l, ensure_ascii=False) + "\n")
    except OSError:
        return 0, len(lignes)
    return len(lignes), len(lignes)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Collecteur de dispersion de funding (lecture seule).")
    p.add_argument("--root", default=str(RACINE))
    # LEVIER 1 : par defaut on suit l'UNIVERS COMPLET ("*"). Passer une liste explicite
    # (--coins BTC,ETH) reste possible pour un test cible ; COINS_DEFAUT sert de repli lisible.
    p.add_argument("--coins", default="*")
    p.add_argument("--intervalle", type=float, default=INTERVALLE_S_DEFAUT)
    p.add_argument("--une-fois", action="store_true")
    a = p.parse_args(argv)

    root = Path(a.root)
    coins = [c for c in (a.coins or "").split(",") if c.strip()] or ["*"]
    univers = "UNIVERS COMPLET (intersection HL∩Binance)" if "*" in coins else "%d coin(s)" % len(coins)
    print("[venues] collecteur demarre — %s, toutes les %.0f s"
          % (univers, a.intervalle), flush=True)
    total = 0
    while True:
        n, comparables = une_passe(root, coins)
        total += n
        if comparables:
            print("[venues] %s  ecrits=%d  cumul=%d  (%d coins comparables sur les 2 venues)"
                  % (time.strftime("%H:%M:%S"), n, total, comparables), flush=True)
        else:
            print("[venues] %s  aucune paire comparable ce tick (venue muette ou coin absent) — "
                  "rien ecrit, rien invente" % time.strftime("%H:%M:%S"), flush=True)
        if a.une_fois:
            return 0
        time.sleep(max(30.0, float(a.intervalle)))


if __name__ == "__main__":
    raise SystemExit(main())
