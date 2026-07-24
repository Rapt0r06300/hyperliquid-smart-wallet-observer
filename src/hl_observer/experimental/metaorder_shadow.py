"""METAORDER_SHADOW_V1 — détection de métaordres en SHADOW (rectif Flo 24/07).

Objectif : sans TOUCHER aux entrées RAW, étiqueter les fills des vaults suivis et mesurer, PAR STADE de
métaordre, l'edge forward NET après coûts. On ne prend AUCUNE position : c'est une mesure pure, écrite dans
un ledger SÉPARÉ (`metaorder_shadow_ledger.jsonl`), jamais mélangée au PnL live.

Pipeline :
  1. TWAP : étiqueté DIRECTEMENT via `userTwapSliceFills` / `userTwapHistory` (index tid|hash -> twapId).
  2. Métaordre caché : on agrège les autres fills par (vault, coin, sens) contigus dans le temps (intervalle).
  3. Stade : FIRST_SLICE / CONTINUATION / LATE_STAGE / REVERSAL.
  4. Mesure par stade : PnL forward NET après coûts, taille relative, crossed maker/taker, âge, + en shadow :
     OFI top-5 du carnet (confirmation) et placebo même coin/même instant (vs dérive marché BTC).

TROIS ÂGES bien SÉPARÉS (réconciliation demandée) :
  • `age_fill_hl_ms`    = âge/skew de l'ÉVÉNEMENT HL (fill.time vs horloge) — staleness du signal côté source.
  • `latence_locale_ms` = latence de NOTRE pipeline WS→décision→open (~382 ms médian en live ; hors shadow).
  • `age_stade_ms`      = âge du STADE = temps écoulé depuis le FIRST_SLICE du métaordre parent (secondes→min).
Le « price-in ~60 s » évoqué avant était une propriété du SIGNAL de copie mesurée offline (décroissance de
l'edge), PAS la latence locale (382 ms). Ces trois axes sont distincts et mesurés séparément.

Lecture seule ; 0 ordre, 0 clé, 0 signature. `real_execution=false`, `shadow=true` sur chaque ligne.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

VERSION = "metaorder_shadow_v1"
LEDGER_RELPATH = Path("runtime") / "data" / "metaorder_shadow_ledger.jsonl"
STATS_RELPATH = Path("runtime") / "data" / "metaorder_shadow_stats.json"

INTERVALLE_METAORDRE_MS = 60_000.0     # 2 fills same-side espacés de ≤ 60 s = même métaordre parent (défaut)
HORIZON_FWD_MS = 300_000.0             # horizon forward de mesure de l'edge (5 min)
COUT_AR_DEFAUT_BPS = 16.0             # coût aller-retour ESTIMÉ par défaut (2×taker+spread+2×slippage+latence)
LATE_FRAC = 0.66                       # part du métaordre à partir de laquelle un slice est LATE_STAGE


# ─────────────────────────────── cœur PUR (testable sans réseau) ───────────────────────────────

def sens_fill(f) -> int:
    """+1 achat (side B), -1 vente (side A), 0 inconnu."""
    s = str((f or {}).get("side") or "").upper()
    return 1 if s == "B" else (-1 if s == "A" else 0)


def maker_taker(f) -> str:
    """`crossed`=true ⇒ l'ordre a traversé le spread = TAKER ; sinon MAKER (au repos)."""
    return "taker" if bool((f or {}).get("crossed")) else "maker"


def index_twap(twap_slice_fills) -> dict:
    """De `userTwapSliceFills` [{fill:{tid,hash,...}, twapId}] → index {tid|hash -> twapId} pour étiqueter."""
    idx: dict = {}
    for s in (twap_slice_fills or []):
        f = (s or {}).get("fill") or {}
        tw = (s or {}).get("twapId")
        for k in (f.get("tid"), f.get("hash")):
            if k is not None:
                idx[k] = tw
    return idx


def est_twap(f, idx_twap: dict) -> bool:
    """Un fill est TWAP s'il apparaît dans l'index TWAP (par tid ou hash)."""
    return bool(idx_twap) and ((f or {}).get("tid") in idx_twap or (f or {}).get("hash") in idx_twap)


def detecter_metaordres(fills: list, *, intervalle_ms: float = INTERVALLE_METAORDRE_MS) -> list:
    """Groupe des fills (triés par temps) en MÉTAORDRES : même sens ET écart ≤ intervalle_ms. Un changement de
    sens (ou un trou) ferme le métaordre courant. `reversal`=True si le nouveau métaordre inverse le précédent
    (sur la même série passée). Rend [{sens, fills:[...], t0, t1, sz_tot, reversal}]."""
    fs = sorted(fills, key=lambda f: int((f or {}).get("time") or 0))
    metas: list = []
    cur = None
    for f in fs:
        s = sens_fill(f)
        if s == 0:
            continue
        t = int(f.get("time") or 0)
        sz = abs(float(f.get("sz") or 0.0))
        if cur and s == cur["sens"] and (t - cur["t1"]) <= intervalle_ms:
            cur["fills"].append(f)
            cur["t1"] = t
            cur["sz_tot"] += sz
        else:
            reversal = bool(cur and s == -cur["sens"])            # inverse le métaordre juste précédent
            if cur:
                metas.append(cur)
            cur = {"sens": s, "fills": [f], "t0": t, "t1": t, "sz_tot": sz, "reversal": reversal}
    if cur:
        metas.append(cur)
    return metas


def classer_stade(i: int, n: int, meta: dict, *, late_frac: float = LATE_FRAC) -> str:
    """Stade du slice i (0-based) parmi n : REVERSAL (1er slice d'un métaordre qui inverse le précédent),
    sinon FIRST_SLICE (i==0), LATE_STAGE (dernier ou i/n ≥ late_frac), CONTINUATION au milieu."""
    if meta.get("reversal") and i == 0:
        return "REVERSAL"
    if i == 0:
        return "FIRST_SLICE"
    if n <= 1 or i >= n - 1 or (i / n) >= late_frac:
        return "LATE_STAGE"
    return "CONTINUATION"


def pnl_forward_net_bps(prix_entree, prix_forward, sens: int, cout_ar_bps: float) -> float | None:
    """Rendement forward NET (bps) dans le sens du signal, moins les coûts aller-retour. None si prix absent."""
    try:
        pe = float(prix_entree)
        if pe <= 0 or prix_forward is None:
            return None
        brut = sens * (float(prix_forward) - pe) / pe * 1e4
        return round(brut - float(cout_ar_bps or 0.0), 3)
    except (TypeError, ValueError):
        return None


def placebo_bps(pe_coin, pf_coin, pe_btc, pf_btc, sens: int) -> dict | None:
    """Placebo même coin/même instant : ret_coin (sens du signal) et ret_marché (BTC, même sens) ; alpha =
    coin − marché. Sépare l'edge propre du signal de la simple dérive de marché. None si le coin est illisible."""
    def r(pe, pf):
        try:
            pe = float(pe)
            return None if pe <= 0 or pf is None else (float(pf) - pe) / pe * 1e4
        except (TypeError, ValueError):
            return None
    rc, rm = r(pe_coin, pf_coin), r(pe_btc, pf_btc)
    if rc is None:
        return None
    rc *= sens
    rm = rm * sens if rm is not None else None
    return {"ret_coin_bps": round(rc, 3), "ret_marche_bps": (round(rm, 3) if rm is not None else None),
            "alpha_vs_marche_bps": (round(rc - rm, 3) if rm is not None else None)}


def ofi_top5(book_avant, book_apres) -> float | None:
    """OFI top-5 (order flow imbalance) SIMPLIFIÉ entre deux snapshots l2Book {'levels':[bids,asks]} : variation
    de la taille bid moins variation de la taille ask sur 5 niveaux. >0 = pression acheteuse. None si illisible."""
    def cotes(b):
        try:
            return (b["levels"][0][:5], b["levels"][1][:5])
        except (KeyError, IndexError, TypeError):
            return None
    a, c = cotes(book_avant), cotes(book_apres)
    if not a or not c:
        return None
    def somme(niv):
        return sum(float(x.get("sz") or 0.0) for x in niv)
    return round((somme(c[0]) - somme(a[0])) - (somme(c[1]) - somme(a[1])), 4)


def ic_pearson(signaux: list, *, cle_force: str = "taille_relative", cle_y: str = "pnl_net_bps") -> float | None:
    """IC = corrélation de Pearson entre une FORCE de signal (défaut : taille relative du slice) et le
    rendement forward NET. Mesure « un slice plus gros prédit-il un meilleur forward ? ». None si < 3 points."""
    xs, ys = [], []
    for s in signaux:
        x, y = s.get(cle_force), s.get(cle_y)
        if x is not None and y is not None:
            xs.append(float(x))
            ys.append(float(y))
    n = len(xs)
    if n < 3:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return round(num / (dx * dy), 4) if dx > 0 and dy > 0 else None


def prix_au(serie: list, ts_ms) -> float | None:
    """Dernier prix de `serie` [(ts, px)] au temps ≤ ts_ms (dérive minimale). None si aucun point antérieur."""
    if not serie or ts_ms is None:
        return None
    best = None
    for t, p in serie:
        if t <= ts_ms:
            best = p
        else:
            break
    return best


def construire_signaux(fills: list, *, idx_twap: dict, tape_coin: list, tape_btc: list,
                       cout_ar_bps: float = COUT_AR_DEFAUT_BPS, horizon_ms: float = HORIZON_FWD_MS,
                       intervalle_ms: float = INTERVALLE_METAORDRE_MS, taille_ref_usd: float | None = None,
                       maintenant_ms: float | None = None) -> list:
    """CŒUR TESTABLE : à partir des fills BRUTS d'un (vault, coin), construit un signal SHADOW par slice avec
    stade, TWAP, taille relative, maker/taker, les 3 âges, PnL forward net après coûts et placebo. `tape_coin`
    et `tape_btc` = séries [(ts, px)] pour le prix d'entrée (≈ fill.time) et forward (fill.time + horizon).
    N'ouvre RIEN. Un slice sans prix forward (trop récent / tape absente) garde pnl_net_bps=None (jamais inventé)."""
    now = maintenant_ms if maintenant_ms is not None else time.time() * 1000
    metas = detecter_metaordres(fills, intervalle_ms=intervalle_ms)
    out: list = []
    for meta in metas:
        n = len(meta["fills"])
        for i, f in enumerate(meta["fills"]):
            t = int(f.get("time") or 0)
            sens = meta["sens"]
            sz = abs(float(f.get("sz") or 0.0))
            px = f.get("px")
            try:
                taille_usd = sz * float(px) if px is not None else None
            except (TypeError, ValueError):
                taille_usd = None
            pe_coin = prix_au(tape_coin, t) if tape_coin else (float(px) if px is not None else None)
            pf_coin = prix_au(tape_coin, t + horizon_ms) if tape_coin else None
            pe_btc = prix_au(tape_btc, t) if tape_btc else None
            pf_btc = prix_au(tape_btc, t + horizon_ms) if tape_btc else None
            pnl = pnl_forward_net_bps(pe_coin, pf_coin, sens, cout_ar_bps)
            plc = placebo_bps(pe_coin, pf_coin, pe_btc, pf_btc, sens) or {}
            ref = taille_ref_usd if taille_ref_usd else (meta["sz_tot"] * float(px) if px is not None else None)
            sig = {
                "stade": classer_stade(i, n, meta),
                "is_twap": est_twap(f, idx_twap),
                "sens": sens,
                "coin": str(f.get("coin") or "").upper(),
                "slice_i": i, "n_slices": n,
                "taille_usd": round(taille_usd, 2) if taille_usd is not None else None,
                "taille_relative": round(taille_usd / ref, 4) if (taille_usd and ref) else None,
                "maker_taker": maker_taker(f),
                "age_stade_ms": t - meta["t0"],                   # temps depuis le FIRST_SLICE (âge du STADE)
                "age_fill_hl_ms": round(now - t),                 # âge/skew de l'événement HL (staleness signal)
                "latence_locale_ms": None,                        # N/A en shadow (mesuré en live : ~382 ms médian)
                "horizon_ms": horizon_ms, "cout_ar_bps": cout_ar_bps,
                "pnl_net_bps": pnl,
                "ret_coin_bps": plc.get("ret_coin_bps"), "ret_marche_bps": plc.get("ret_marche_bps"),
                "alpha_vs_marche_bps": plc.get("alpha_vs_marche_bps"),
                "fill_time": t, "tid": f.get("tid"), "hash": f.get("hash"),
            }
            out.append(sig)
    return out


def stats_par_stade(signaux: list) -> dict:
    """Agrège les signaux par STADE : n, PnL net moyen/médian, part positive, IC, placebo alpha moyen,
    capacité (somme des tailles), % taker. Base de la décision « ce stade devient-il fortement positif ? »."""
    from collections import defaultdict
    g: dict = defaultdict(list)
    for s in signaux:
        g[s.get("stade")].append(s)
    out: dict = {}
    for stade, xs in g.items():
        pnls = [x["pnl_net_bps"] for x in xs if x.get("pnl_net_bps") is not None]
        alphas = [x["alpha_vs_marche_bps"] for x in xs if x.get("alpha_vs_marche_bps") is not None]
        caps = [x["taille_usd"] for x in xs if x.get("taille_usd") is not None]
        takers = sum(1 for x in xs if x.get("maker_taker") == "taker")
        twaps = sum(1 for x in xs if x.get("is_twap"))
        pnls_tries = sorted(pnls)
        out[stade] = {
            "n": len(xs), "n_avec_pnl": len(pnls),
            "pnl_net_bps_moy": round(sum(pnls) / len(pnls), 3) if pnls else None,
            "pnl_net_bps_med": pnls_tries[len(pnls_tries) // 2] if pnls else None,
            "part_positive_pct": round(100 * sum(1 for p in pnls if p > 0) / len(pnls), 1) if pnls else None,
            "ic_taille_vs_pnl": ic_pearson(xs),
            "placebo_alpha_moy_bps": round(sum(alphas) / len(alphas), 3) if alphas else None,
            "capacite_usd": round(sum(caps), 1) if caps else None,
            "taker_pct": round(100 * takers / len(xs), 1) if xs else None,
            "twap_pct": round(100 * twaps / len(xs), 1) if xs else None,
        }
    return out


# ─────────────────────────────── runner SHADOW (réseau, borné, poli) ───────────────────────────────

def _providers_reels():
    """Fournisseurs REST réels (userFillsByTime + userTwapSliceFills), importés paresseusement. Lecture seule."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
    from sonde_confirmation_vaults import userfills_by_time_rest  # réutilise le POST /info borné
    import urllib.request

    def twap_provider(vault, start_ms):
        corps = json.dumps({"type": "userTwapSliceFills", "user": vault}).encode("utf-8")
        req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=corps,
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as rep:      # noqa: S310 (URL publique constante)
            return json.loads(rep.read().decode("utf-8"))
    return userfills_by_time_rest, twap_provider


def executer(root: str | Path, vaults: list, *, fills_provider=None, twap_provider=None, tape=None,
             tape_candles=None, horizon_ms: float = HORIZON_FWD_MS, fenetre_ms: float = 7_200_000.0,
             config_hash: str = "", git_commit: str = "", maintenant_ms: float | None = None) -> dict:
    """Passe SHADOW : pour chaque vault, lit `userFillsByTime` (fenêtre bornée) + TWAP, construit les signaux
    par coin, écrit le ledger + les stats par stade. INJECTABLE (fills_provider/twap_provider/tape) pour test
    sans réseau. N'OUVRE AUCUNE POSITION. Rend {n_signaux, n_appels_rest, stats}."""
    root = Path(root)
    now = maintenant_ms if maintenant_ms is not None else time.time() * 1000
    if fills_provider is None or twap_provider is None:
        fp, tp = _providers_reels()
        fills_provider = fills_provider or fp
        twap_provider = twap_provider or tp
    if tape is None:
        try:
            from hl_observer.experimental.copy_edge_forward import charger_prix_tape
            tape = charger_prix_tape(root)
        except Exception:  # noqa: BLE001
            tape = {}
    tape_btc = tape.get("BTC") or []
    start = int(now - fenetre_ms)
    signaux: list = []
    n_rest = 0
    for v in vaults:
        try:
            fills = fills_provider(v, start)
            n_rest += 1
            twaps = twap_provider(v, start)
            n_rest += 1
        except Exception:  # noqa: BLE001 — le réseau ne fait JAMAIS crasher la passe shadow
            continue
        if not isinstance(fills, list):
            continue
        idx = index_twap(twaps if isinstance(twaps, list) else [])
        par_coin: dict = {}
        for f in fills:
            if int((f or {}).get("time") or 0) <= now - horizon_ms:   # seulement les fills assez vieux (forward dispo)
                par_coin.setdefault(str(f.get("coin") or "").upper(), []).append(f)
        for coin, fs in par_coin.items():
            sigs = construire_signaux(fs, idx_twap=idx, tape_coin=tape.get(coin) or [], tape_btc=tape_btc,
                                      horizon_ms=horizon_ms, maintenant_ms=now)
            for s in sigs:
                s.update({"vault": v, "version": VERSION, "config_hash": config_hash, "git_commit": git_commit,
                          "shadow": True, "real_execution": False, "ts_ms": int(now)})
            signaux.extend(sigs)
    stats = stats_par_stade(signaux)
    _ecrire(root, signaux, stats, now)
    return {"n_signaux": len(signaux), "n_appels_rest": n_rest, "stats": stats}


def _ecrire(root: Path, signaux: list, stats: dict, now: float) -> None:
    """Écrit le ledger shadow (append) + le snapshot de stats (atomique). Jamais mélangé au PnL live."""
    (root / LEDGER_RELPATH).parent.mkdir(parents=True, exist_ok=True)
    with (root / LEDGER_RELPATH).open("a", encoding="utf-8") as fh:
        for s in signaux:
            fh.write(json.dumps(s, ensure_ascii=False) + "\n")
    p = root / STATS_RELPATH
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"ts_ms": int(now), "version": VERSION, "stats_par_stade": stats},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


__all__ = ["VERSION", "sens_fill", "maker_taker", "index_twap", "est_twap", "detecter_metaordres",
           "classer_stade", "pnl_forward_net_bps", "placebo_bps", "ofi_top5", "ic_pearson", "prix_au",
           "construire_signaux", "stats_par_stade", "executer", "LEDGER_RELPATH", "STATS_RELPATH"]
