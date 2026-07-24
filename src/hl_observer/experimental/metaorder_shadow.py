"""METAORDER_SHADOW_V1 — détection de métaordres en SHADOW (rectif Flo 24/07, révision statistique).

Sans TOUCHER aux entrées RAW, on étiquette les fills des vaults suivis et on mesure, PAR STADE de métaordre,
l'edge forward NET après coûts. AUCUNE position : mesure pure, ledger SÉPARÉ (`metaorder_shadow_ledger.jsonl`),
jamais mélangée au PnL live. `real_execution=false`, `shadow=true`. Lecture seule.

RIGUEUR STATISTIQUE (les slices d'un même métaordre et les fenêtres forward chevauchées NE SONT PAS
indépendantes) :
  • `metaorder_id` STABLE + déduplication de chaque fill (clé composite) ;
  • unité statistique = le MÉTAORDRE (épisode), résultats aussi groupés par vault / coin / jour ;
  • **bootstrap CLUSTERISÉ** par métaordre (IC de la moyenne) + **walk-forward PURGÉ** (embargo = horizon),
    PAS d'IC calculé sur chaque slice ;
  • on rapporte le nombre de MÉTAORDRES UNIQUES derrière FIRST/CONTINUATION/LATE/REVERSAL ;
  • **coûts L2 RÉELS par signal** (spread + slippage par la taille + frais + latence) ; 16 bps = screening ;
  • TWAP vérifié via `userTwapSliceFills`/`userTwapHistory` en distinguant « aucun TWAP observé » (endpoint
    couvert, vide) de « endpoint non couvert » (erreur/indispo).

TROIS ÂGES séparés (réconciliation « 60 s » vs « 382 ms ») : âge du fill HL (skew événement) ≠ latence locale
(pipeline WS→open, ~382 ms médian en live, N/A en shadow) ≠ âge du stade (depuis le FIRST_SLICE). Détail :
`docs/METAORDER_SHADOW_V1.md`. OFI top-5 : fonction pure prête (`ofi_top5`) mais NON branchée par-signal tant
qu'un stade n'est pas mesuré proprement (étape suivante, exige un tape de carnet). 0 ordre, 0 clé, 0 signature.
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from pathlib import Path

VERSION = "metaorder_shadow_v1"
LEDGER_RELPATH = Path("runtime") / "data" / "metaorder_shadow_ledger.jsonl"
STATS_RELPATH = Path("runtime") / "data" / "metaorder_shadow_stats.json"

INTERVALLE_METAORDRE_MS = 60_000.0     # 2 fills same-side espacés de ≤ 60 s = même métaordre parent
HORIZON_FWD_MS = 300_000.0             # horizon forward de mesure (5 min)
COUT_AR_DEFAUT_BPS = 16.0             # coût aller-retour de SCREENING (fallback si L2 indisponible)
COPY_NOTIONAL_USD = 500.0            # TAILLE DE COPIE pour le coût L2 : on tradrait PETIT, PAS la taille du leader
LATE_FRAC = 0.66
JOUR_MS = 86_400_000.0
# coûts L2 réels (mêmes hypothèses que la cohorte RAW)
SLIPPAGE_BASE_BPS = 1.0
SLIPPAGE_IMPACT_COEF = 8.0
LATENCE_COUT_BPS = 1.0
FRAIS_TAKER_BPS = 3.5                  # aller-retour taker HL ≈ 2×1,5 + marge (screening ; L2 affine le spread)


# ─────────────────────────────── cœur PUR (testable sans réseau) ───────────────────────────────

def sens_fill(f) -> int:
    s = str((f or {}).get("side") or "").upper()
    return 1 if s == "B" else (-1 if s == "A" else 0)


def maker_taker(f) -> str:
    return "taker" if bool((f or {}).get("crossed")) else "maker"


def _cle_fill(f) -> tuple:
    """Clé composite d'un fill pour la DÉDUP (time, hash, tid, oid, coin) — robuste aux fills au même ts."""
    coin = (f or {}).get("coin")
    return (int((f or {}).get("time") or 0), (f or {}).get("hash"), (f or {}).get("tid"),
            (f or {}).get("oid"), str(coin).upper() if coin else None)


def dedup_fills(fills: list) -> list:
    """Déduplique par clé composite (garde la 1re occurrence). Un même fill ne compte JAMAIS deux fois."""
    vus, out = set(), []
    for f in fills or []:
        k = _cle_fill(f)
        if k in vus:
            continue
        vus.add(k)
        out.append(f)
    return out


def metaorder_id(vault: str, coin: str, sens: int, t0: int) -> str:
    """ID STABLE et déterministe d'un métaordre = hash court de (vault, coin, sens, t0 du 1er slice)."""
    brut = "%s|%s|%d|%d" % (str(vault).lower(), str(coin).upper(), int(sens), int(t0))
    return "mo-" + hashlib.sha1(brut.encode("utf-8")).hexdigest()[:12]


def index_twap(twap_slice_fills) -> dict:
    idx: dict = {}
    for s in (twap_slice_fills or []):
        f = (s or {}).get("fill") or {}
        tw = (s or {}).get("twapId")
        for k in (f.get("tid"), f.get("hash")):
            if k is not None:
                idx[k] = tw
    return idx


def est_twap(f, idx_twap: dict) -> bool:
    return bool(idx_twap) and ((f or {}).get("tid") in idx_twap or (f or {}).get("hash") in idx_twap)


def detecter_metaordres(fills: list, *, intervalle_ms: float = INTERVALLE_METAORDRE_MS) -> list:
    """Regroupe des fills (DÉDUPLIQUÉS, triés par temps) en métaordres : même sens ET écart ≤ intervalle_ms.
    Changement de sens ou trou ⇒ nouveau métaordre. `reversal`=True s'il inverse le précédent."""
    fs = sorted(dedup_fills(fills), key=lambda f: int((f or {}).get("time") or 0))
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
            reversal = bool(cur and s == -cur["sens"])
            if cur:
                metas.append(cur)
            cur = {"sens": s, "fills": [f], "t0": t, "t1": t, "sz_tot": sz, "reversal": reversal}
    if cur:
        metas.append(cur)
    return metas


def classer_stade(i: int, n: int, meta: dict, *, late_frac: float = LATE_FRAC) -> str:
    if meta.get("reversal") and i == 0:
        return "REVERSAL"
    if i == 0:
        return "FIRST_SLICE"
    if n <= 1 or i >= n - 1 or (i / n) >= late_frac:
        return "LATE_STAGE"
    return "CONTINUATION"


def pnl_forward_net_bps(prix_entree, prix_forward, sens: int, cout_ar_bps: float) -> float | None:
    try:
        pe = float(prix_entree)
        if pe <= 0 or prix_forward is None:
            return None
        return round(sens * (float(prix_forward) - pe) / pe * 1e4 - float(cout_ar_bps or 0.0), 3)
    except (TypeError, ValueError):
        return None


def placebo_bps(pe_coin, pf_coin, pe_btc, pf_btc, sens: int) -> dict | None:
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
    """OFI top-5 SIMPLIFIÉ entre deux snapshots l2Book. Fonction PRÊTE mais non branchée par-signal (étape
    suivante : exige un tape de carnet horodaté autour de chaque fill). >0 = pression acheteuse."""
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


def prix_au(serie: list, ts_ms) -> float | None:
    if not serie or ts_ms is None:
        return None
    best = None
    for t, p in serie:
        if t <= ts_ms:
            best = p
        else:
            break
    return best


def cout_l2_reel_bps(l2: dict | None, taille_usd) -> tuple[float, str]:
    """Coût aller-retour RÉEL depuis le carnet L2 {hl_bid, hl_ask, depth_usd} et la TAILLE : frais taker +
    spread + 2×slippage(taille/profondeur) + latence. Rend (bps, source). Fallback screening 16 si L2 absent."""
    try:
        bid, ask, depth = float(l2["hl_bid"]), float(l2["hl_ask"]), float(l2.get("depth_usd") or 0.0)
        if bid <= 0 or ask <= 0:
            raise ValueError
        mid = 0.5 * (bid + ask)
        spread = (ask - bid) / mid * 1e4
        slip = SLIPPAGE_BASE_BPS + SLIPPAGE_IMPACT_COEF * (float(taille_usd or 0.0) / depth if depth else 1.0)
        return round(FRAIS_TAKER_BPS + spread + 2.0 * slip + LATENCE_COUT_BPS, 3), "l2_courant_par_taille"
    except (TypeError, ValueError, KeyError):
        return COUT_AR_DEFAUT_BPS, "screening_16bps"


def _cout_screening(coin, taille_usd) -> tuple[float, str]:
    return COUT_AR_DEFAUT_BPS, "screening_16bps"


def construire_signaux(fills: list, *, vault: str, idx_twap: dict, tape_coin: list, tape_btc: list,
                       cout_fn=None, horizon_ms: float = HORIZON_FWD_MS, copy_notional_usd: float = COPY_NOTIONAL_USD,
                       intervalle_ms: float = INTERVALLE_METAORDRE_MS, maintenant_ms: float | None = None) -> list:
    """CŒUR TESTABLE : fills BRUTS d'un (vault, coin) → un signal par slice, avec metaorder_id STABLE, stade,
    TWAP, taille rel, maker/taker, les 3 âges, jour, coût L2 réel (via cout_fn) et PnL forward net + placebo.
    IMPORTANT : le coût L2 est calculé pour NOTRE taille de copie (`copy_notional_usd`, petite), PAS pour la
    taille du LEADER (qui sert à la capacité/taille relative) — sinon le slippage du leader fausse tout.
    N'ouvre RIEN ; slice sans forward → pnl_net_bps=None (jamais inventé). Fills dédupliqués en amont."""
    now = maintenant_ms if maintenant_ms is not None else time.time() * 1000
    cfn = cout_fn or _cout_screening
    metas = detecter_metaordres(fills, intervalle_ms=intervalle_ms)
    out: list = []
    for meta in metas:
        n = len(meta["fills"])
        coin0 = str(meta["fills"][0].get("coin") or "").upper()
        mid_id = metaorder_id(vault, coin0, meta["sens"], meta["t0"])
        for i, f in enumerate(meta["fills"]):
            t = int(f.get("time") or 0)
            sens = meta["sens"]
            sz = abs(float(f.get("sz") or 0.0))
            px = f.get("px")
            try:
                taille_usd = sz * float(px) if px is not None else None
            except (TypeError, ValueError):
                taille_usd = None
            cout_bps, cout_src = cfn(coin0, copy_notional_usd)   # coût pour NOTRE taille de copie, pas celle du leader
            pe_coin = prix_au(tape_coin, t) if tape_coin else (float(px) if px is not None else None)
            pf_coin = prix_au(tape_coin, t + horizon_ms) if tape_coin else None
            pe_btc = prix_au(tape_btc, t) if tape_btc else None
            pf_btc = prix_au(tape_btc, t + horizon_ms) if tape_btc else None
            plc = placebo_bps(pe_coin, pf_coin, pe_btc, pf_btc, sens) or {}
            ref = meta["sz_tot"] * float(px) if px is not None else None
            out.append({
                "metaorder_id": mid_id, "stade": classer_stade(i, n, meta), "is_twap": est_twap(f, idx_twap),
                "sens": sens, "vault": vault, "coin": coin0, "slice_i": i, "n_slices": n,
                "taille_usd": round(taille_usd, 2) if taille_usd is not None else None,
                "taille_relative": round(taille_usd / ref, 4) if (taille_usd and ref) else None,
                "maker_taker": maker_taker(f),
                "age_stade_ms": t - meta["t0"], "age_fill_hl_ms": round(now - t), "latence_locale_ms": None,
                "jour": int(t // JOUR_MS),
                "horizon_ms": horizon_ms, "cout_ar_bps": cout_bps, "cout_source": cout_src,
                "cout_notional_usd": copy_notional_usd,
                "pnl_net_bps": pnl_forward_net_bps(pe_coin, pf_coin, sens, cout_bps),
                "ret_coin_bps": plc.get("ret_coin_bps"), "ret_marche_bps": plc.get("ret_marche_bps"),
                "alpha_vs_marche_bps": plc.get("alpha_vs_marche_bps"),
                "fill_time": t, "tid": f.get("tid"), "hash": f.get("hash"),
            })
    return out


def bootstrap_clusterise(paires: list, *, n: int = 2000, seed: int = 0, alpha: float = 0.05) -> dict:
    """IC de la MOYENNE par bootstrap CLUSTERISÉ : `paires` = [(cluster_id, valeur)]. On rééchantillonne les
    CLUSTERS avec remise (tous les points d'un cluster ensemble) → respecte la dépendance intra-cluster.
    Rend {moy, ic_bas, ic_haut, n_clusters, n_obs}. CI None si < 2 clusters."""
    from collections import defaultdict
    g: dict = defaultdict(list)
    for c, v in paires:
        if v is not None:
            g[c].append(float(v))
    clusters = [vs for vs in g.values() if vs]
    allv = [v for vs in clusters for v in vs]
    if not allv:
        return {"moy": None, "ic_bas": None, "ic_haut": None, "n_clusters": 0, "n_obs": 0}
    moy = sum(allv) / len(allv)
    if len(clusters) < 2:
        return {"moy": round(moy, 3), "ic_bas": None, "ic_haut": None, "n_clusters": len(clusters), "n_obs": len(allv)}
    rnd = random.Random(seed)
    k = len(clusters)
    moys = []
    for _ in range(n):
        pool: list = []
        for _ in range(k):
            pool.extend(clusters[rnd.randrange(k)])
        if pool:
            moys.append(sum(pool) / len(pool))
    moys.sort()
    lo = moys[int(alpha / 2 * len(moys))]
    hi = moys[min(len(moys) - 1, int((1 - alpha / 2) * len(moys)))]
    return {"moy": round(moy, 3), "ic_bas": round(lo, 3), "ic_haut": round(hi, 3),
            "n_clusters": k, "n_obs": len(allv)}


def walk_forward_purge(signaux: list, *, n_folds: int = 3, horizon_ms: float = HORIZON_FWD_MS,
                       cle: str = "fill_time") -> dict:
    """Walk-forward PURGÉ : découpe le temps en n_folds contigus ; pour chaque fold, on DROPPE le 1er horizon
    (embargo → pas de chevauchement de fenêtre forward avec le fold précédent) et on rapporte la moyenne OOS
    du PnL net PAR STADE. Vérifie qu'un stade n'est pas porté par une seule période."""
    from collections import defaultdict
    s = sorted([x for x in signaux if x.get(cle) is not None and x.get("pnl_net_bps") is not None],
               key=lambda x: x[cle])
    if len(s) < max(2 * n_folds, 6):
        return {"n_folds": n_folds, "folds": [], "note": "trop peu de signaux pour un walk-forward"}
    t0, t1 = s[0][cle], s[-1][cle]
    bornes = [t0 + (t1 - t0) * i / n_folds for i in range(n_folds + 1)]
    folds = []
    for i in range(n_folds):
        a, b = bornes[i] + (horizon_ms if i > 0 else 0), bornes[i + 1]   # embargo au début du fold
        seg = [x for x in s if a <= x[cle] < b]
        ps: dict = defaultdict(list)
        for x in seg:
            ps[x["stade"]].append(x["pnl_net_bps"])
        folds.append({"fold": i, "n": len(seg),
                      "par_stade": {st: round(sum(v) / len(v), 2) for st, v in ps.items() if v}})
    return {"n_folds": n_folds, "folds": folds}


def _agg_metaordre(xs: list) -> list:
    """Agrège les slices en points par MÉTAORDRE : (metaorder_id, moyenne du pnl_net) — 1 point/métaordre."""
    from collections import defaultdict
    g: dict = defaultdict(list)
    for x in xs:
        if x.get("pnl_net_bps") is not None:
            g[x.get("metaorder_id")].append(x["pnl_net_bps"])
    return [(mid, sum(v) / len(v)) for mid, v in g.items() if v]


def stats_par_stade(signaux: list, *, n_boot: int = 2000) -> dict:
    """Par STADE : n_slices, **n_metaordres UNIQUES**, PnL net moyen + **IC bootstrap CLUSTERISÉ par métaordre**,
    part de MÉTAORDRES positifs, placebo alpha (clusterisé), capacité, % taker, % TWAP, coût moyen + source.
    (Pas d'IC par slice : dépendance intra-métaordre respectée.)"""
    from collections import defaultdict
    g: dict = defaultdict(list)
    for s in signaux:
        g[s.get("stade")].append(s)
    out: dict = {}
    for stade, xs in g.items():
        paires_pnl = [(x.get("metaorder_id"), x["pnl_net_bps"]) for x in xs if x.get("pnl_net_bps") is not None]
        paires_alpha = [(x.get("metaorder_id"), x["alpha_vs_marche_bps"]) for x in xs
                        if x.get("alpha_vs_marche_bps") is not None]
        mo = _agg_metaordre(xs)
        caps = [x["taille_usd"] for x in xs if x.get("taille_usd") is not None]
        couts = [x["cout_ar_bps"] for x in xs if x.get("cout_ar_bps") is not None]
        srcs = {}
        for x in xs:
            srcs[x.get("cout_source")] = srcs.get(x.get("cout_source"), 0) + 1
        boot = bootstrap_clusterise(paires_pnl, n=n_boot)
        out[stade] = {
            "n_slices": len(xs), "n_metaordres": len({x.get("metaorder_id") for x in xs}),
            "pnl_net_bps_moy": boot["moy"], "pnl_net_ic95": [boot["ic_bas"], boot["ic_haut"]],
            "part_metaordres_positifs_pct": round(100 * sum(1 for _, v in mo if v > 0) / len(mo), 1) if mo else None,
            "placebo_alpha_moy_bps": bootstrap_clusterise(paires_alpha, n=n_boot)["moy"],
            "capacite_usd": round(sum(caps), 1) if caps else None,
            "taker_pct": round(100 * sum(1 for x in xs if x.get("maker_taker") == "taker") / len(xs), 1) if xs else None,
            "twap_pct": round(100 * sum(1 for x in xs if x.get("is_twap")) / len(xs), 1) if xs else None,
            "cout_moy_bps": round(sum(couts) / len(couts), 2) if couts else None, "cout_sources": srcs,
        }
    return out


def agreger_par(signaux: list, cle: str) -> dict:
    """Résultats groupés par `cle` (vault/coin/jour) : par groupe → n_metaordres + PnL net moyen (clusterisé)."""
    from collections import defaultdict
    g: dict = defaultdict(list)
    for s in signaux:
        g[s.get(cle)].append(s)
    out: dict = {}
    for k, xs in g.items():
        paires = [(x.get("metaorder_id"), x["pnl_net_bps"]) for x in xs if x.get("pnl_net_bps") is not None]
        out[str(k)] = {"n_metaordres": len({x.get("metaorder_id") for x in xs}),
                       "pnl_net_bps_moy": bootstrap_clusterise(paires)["moy"]}
    return out


# ─────────────────────────────── runner SHADOW (réseau, borné, poli) ───────────────────────────────

def _providers_reels():
    """Fournisseurs REST réels : userFillsByTime, userTwapSliceFills, l2Book (coût L2). Lecture seule."""
    import sys
    import urllib.request
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
    from sonde_confirmation_vaults import userfills_by_time_rest

    def _post(corps):
        req = urllib.request.Request("https://api.hyperliquid.xyz/info", data=json.dumps(corps).encode("utf-8"),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as rep:      # noqa: S310 (URL publique constante)
            return json.loads(rep.read().decode("utf-8"))

    def twap_provider(vault, start_ms):
        return _post({"type": "userTwapSliceFills", "user": vault})

    def l2_provider(coin):
        import sys as _s
        _s.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
        from collecter_carnet import _post_hl, parser_book_hl
        rep = _post_hl(coin, timeout_s=6.0)
        p = parser_book_hl(rep)
        if not p:
            return None
        bid, ask, bsz, asz = p
        mid = 0.5 * (bid + ask)
        depth = min(bsz, asz) * mid
        return {"hl_bid": bid, "hl_ask": ask, "depth_usd": round(depth, 2)}
    return userfills_by_time_rest, twap_provider, l2_provider


def executer(root: str | Path, vaults: list, *, fills_provider=None, twap_provider=None, l2_provider=None,
             tape=None, horizon_ms: float = HORIZON_FWD_MS, fenetre_ms: float = 7_200_000.0,
             config_hash: str = "", git_commit: str = "", maintenant_ms: float | None = None) -> dict:
    """Passe SHADOW : par vault, `userFillsByTime` (fenêtre bornée) + `userTwapSliceFills` (statut TWAP), coût
    L2 réel par coin, construit les signaux (dédup + metaorder_id), écrit ledger + stats (clusterisées,
    walk-forward, groupées) + budget REST EXACT. INJECTABLE pour test. N'OUVRE AUCUNE POSITION."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
    import sonde_confirmation_vaults as SD
    root = Path(root)
    now = maintenant_ms if maintenant_ms is not None else time.time() * 1000
    if fills_provider is None or twap_provider is None or l2_provider is None:
        fp, tp, lp = _providers_reels()
        fills_provider = fills_provider or fp
        twap_provider = twap_provider or tp
        l2_provider = l2_provider or lp
    if tape is None:
        try:
            from hl_observer.experimental.copy_edge_forward import charger_prix_tape
            tape = charger_prix_tape(root)
        except Exception:  # noqa: BLE001
            tape = {}
    tape_btc = tape.get("BTC") or []
    start = int(now - fenetre_ms)
    signaux: list = []
    appels_budget: list = []
    twap_statut: dict = {}
    l2_cache: dict = {}

    def _cout_fn(coin, taille_usd):
        if coin not in l2_cache:
            try:
                l2_cache[coin] = l2_provider(coin)
                appels_budget.append(("l2Book", 0))
            except Exception:  # noqa: BLE001
                l2_cache[coin] = None
        return cout_l2_reel_bps(l2_cache.get(coin), taille_usd)

    for v in vaults:
        try:
            fills = fills_provider(v, start)
            appels_budget.append(("userFillsByTime", len(fills) if isinstance(fills, list) else 0))
        except Exception:  # noqa: BLE001 — le réseau ne fait JAMAIS crasher la passe
            continue
        try:
            twaps = twap_provider(v, start)
            appels_budget.append(("userTwapSliceFills", len(twaps) if isinstance(twaps, list) else 0))
            twap_statut[v] = "couvert_avec_twap" if (isinstance(twaps, list) and twaps) else "couvert_vide"
        except Exception:  # noqa: BLE001
            twaps, twap_statut[v] = [], "non_couvert"           # endpoint indisponible ≠ aucun TWAP
        if not isinstance(fills, list):
            continue
        idx = index_twap(twaps if isinstance(twaps, list) else [])
        par_coin: dict = {}
        for f in fills:
            if int((f or {}).get("time") or 0) <= now - horizon_ms:   # assez vieux : forward disponible
                par_coin.setdefault(str(f.get("coin") or "").upper(), []).append(f)
        for coin, fs in par_coin.items():
            sigs = construire_signaux(fs, vault=v, idx_twap=idx, tape_coin=tape.get(coin) or [],
                                      tape_btc=tape_btc, cout_fn=_cout_fn, horizon_ms=horizon_ms, maintenant_ms=now)
            for s in sigs:
                s.update({"version": VERSION, "config_hash": config_hash, "git_commit": git_commit,
                          "shadow": True, "real_execution": False, "ts_ms": int(now)})
            signaux.extend(sigs)

    stats = stats_par_stade(signaux)
    wf = walk_forward_purge(signaux, horizon_ms=horizon_ms)
    poids = SD.poids_info(appels_budget)
    SD.journaliser_budget(root, "metaorder_shadow", poids, 600.0)
    budget = SD.budget_total(root)
    n_twap = {k: sum(1 for vv in twap_statut.values() if vv == k) for k in set(twap_statut.values())}
    _ecrire(root, signaux, {
        "version": VERSION, "n_signaux": len(signaux), "n_metaordres": len({s["metaorder_id"] for s in signaux}),
        "stats_par_stade": stats, "walk_forward_purge": wf,
        "par_vault": agreger_par(signaux, "vault"), "par_coin": agreger_par(signaux, "coin"),
        "par_jour": agreger_par(signaux, "jour"), "twap_statut_par_vault": n_twap,
        "budget_rest": {"poids_passe": poids, "n_appels": len(appels_budget), "total_ip": budget},
    }, now)
    return {"n_signaux": len(signaux), "n_metaordres": len({s["metaorder_id"] for s in signaux}),
            "poids_passe": poids, "n_appels": len(appels_budget), "budget_total": budget, "stats": stats}


def _ecrire(root: Path, signaux: list, resume: dict, now: float) -> None:
    (root / LEDGER_RELPATH).parent.mkdir(parents=True, exist_ok=True)
    with (root / LEDGER_RELPATH).open("a", encoding="utf-8") as fh:
        for s in signaux:
            fh.write(json.dumps(s, ensure_ascii=False) + "\n")
    p = root / STATS_RELPATH
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"ts_ms": int(now), **resume}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


__all__ = ["VERSION", "sens_fill", "maker_taker", "dedup_fills", "metaorder_id", "index_twap", "est_twap",
           "detecter_metaordres", "classer_stade", "pnl_forward_net_bps", "placebo_bps", "ofi_top5", "prix_au",
           "cout_l2_reel_bps", "construire_signaux", "bootstrap_clusterise", "walk_forward_purge",
           "stats_par_stade", "agreger_par", "executer", "LEDGER_RELPATH", "STATS_RELPATH"]
