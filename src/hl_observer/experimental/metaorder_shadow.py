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
`docs/METAORDER_SHADOW_V1.md`. Le tape L2 causal fournit OFI multi-niveaux, microprice, depletion de file,
forme de profondeur et flux agressif lorsqu'ils sont reellement observables. Le gate et son ablation restent
strictement SHADOW : aucune entree paper, aucune promotion automatique, 0 ordre, 0 cle, 0 signature.
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
DELAIS_ENTREE_MS = (50, 100, 250, 500, 1000, 2000, 5000)
TWAP_SLICE_INTERVAL_MS = 30_000.0
TWAP_CATCH_UP_RATIO = 1.25
ZERO_TWAP_HASH = "0x" + ("0" * 64)
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
    brut = f"{str(vault).lower()}|{str(coin).upper()}|{int(sens)}|{int(t0)}"
    return "mo-" + hashlib.sha1(brut.encode("utf-8")).hexdigest()[:12]


def twap_metaorder_id(vault: str, coin: str, twap_id) -> str:
    """ID stable d'un TWAP visible, indépendant du découpage temporel local."""
    brut = f"{str(vault).lower()}|{str(coin).upper()}|{twap_id}"
    return "twap-" + hashlib.sha1(brut.encode("utf-8")).hexdigest()[:12]


def _fill_identity_keys(fill: dict | None) -> tuple:
    """Identités fortes d'un fill, sans utiliser le hash nul des TWAP."""
    fill = fill or {}
    keys: list[tuple[str, str]] = []
    tid = fill.get("tid")
    if tid is not None:
        keys.append(("tid", str(tid)))
    oid = fill.get("oid")
    ts = fill.get("time")
    if oid is not None and ts is not None:
        keys.append(("oid_time", f"{oid}:{ts}"))
    raw_hash = str(fill.get("hash") or "").lower()
    if raw_hash and raw_hash != ZERO_TWAP_HASH:
        keys.append(("hash", raw_hash))
    return tuple(keys)


def index_twap(twap_slice_fills) -> dict:
    idx: dict = {}
    for s in (twap_slice_fills or []):
        f = (s or {}).get("fill") or {}
        tw = (s or {}).get("twapId")
        if tw is None:
            continue
        for key in _fill_identity_keys(f):
            idx[key] = tw
    return idx


def twap_id_fill(fill: dict | None, idx_twap: dict) -> int | str | None:
    for key in _fill_identity_keys(fill):
        if key in (idx_twap or {}):
            return idx_twap[key]
    # Compatibilité avec les index historiques tid/hash sans préfixe.
    for legacy_key in ((fill or {}).get("tid"), (fill or {}).get("hash")):
        if legacy_key is not None and legacy_key in (idx_twap or {}):
            return idx_twap[legacy_key]
    return None


def est_twap(f, idx_twap: dict) -> bool:
    return twap_id_fill(f, idx_twap) is not None


def normaliser_twap_states(payload, *, observed_at_ms: int | None = None) -> dict:
    """Normalise le format officiel ``states: Array<[twapId, TwapState]>``."""
    data = payload or {}
    if isinstance(data, dict) and data.get("channel") == "twapStates":
        data = data.get("data") or {}
    if isinstance(data, dict):
        observed = data.get("observed_at_ms", data.get("received_at_ms", observed_at_ms))
        states = data.get("states") or []
    else:
        observed = observed_at_ms
        states = data if isinstance(data, list) else []
    out: dict = {}
    for item in states:
        if not isinstance(item, (list, tuple)) or len(item) != 2 or not isinstance(item[1], dict):
            continue
        twap_id, state = item
        try:
            total = float(state.get("sz"))
            executed = float(state.get("executedSz") or 0.0)
            minutes = float(state.get("minutes") or 0.0)
            started_at = int(state.get("timestamp") or 0)
            executed_ntl = float(state.get("executedNtl") or 0.0)
        except (TypeError, ValueError):
            continue
        if total <= 0:
            continue
        expected_slices = max(1.0, minutes * 2.0)
        out[twap_id] = {
            "twap_id": twap_id,
            "coin": str(state.get("coin") or "").upper(),
            "side": str(state.get("side") or "").upper(),
            "reduce_only": bool(state.get("reduceOnly")),
            "randomize": bool(state.get("randomize")),
            "total_size": total,
            "executed_size": max(0.0, executed),
            "executed_notional": executed_ntl,
            "minutes": minutes,
            "started_at_ms": started_at,
            "normal_slice_size": total / expected_slices,
            "fraction_executed": min(1.0, max(0.0, executed) / total),
            "residual_size": max(0.0, total - max(0.0, executed)),
            "observed_at_ms": int(observed) if observed is not None else None,
            "source": "hyperliquid_ws:twapStates",
        }
    return out


def etat_twap_observable(twap_state_snapshots, twap_id, *, as_of_ms: int) -> dict | None:
    """Dernier état reçu avant la décision ; un état non horodaté est refusé."""
    chosen = None
    chosen_at = -1
    for snapshot in twap_state_snapshots or []:
        if not isinstance(snapshot, dict):
            continue
        observed = snapshot.get("observed_at_ms", snapshot.get("received_at_ms"))
        try:
            observed_i = int(observed)
        except (TypeError, ValueError):
            continue
        if observed_i > int(as_of_ms) or observed_i < chosen_at:
            continue
        states = normaliser_twap_states(snapshot, observed_at_ms=observed_i)
        state = states.get(twap_id)
        if state is None:
            state = next(
                (candidate for key, candidate in states.items() if str(key) == str(twap_id)),
                None,
            )
        if state is not None:
            chosen = state
            chosen_at = observed_i
    return chosen


def rejouer_metaordres_causaux(
    fills: list,
    *,
    vault: str,
    idx_twap: dict,
    twap_state_snapshots=None,
    intervalle_ms: float = INTERVALLE_METAORDRE_MS,
) -> list:
    """Rejoue les slices dans l'ordre sans consulter un événement futur."""
    events = sorted(dedup_fills(fills), key=lambda f: int((f or {}).get("time") or 0))
    groups: dict[str, dict] = {}
    inferred_by_coin: dict[str, str] = {}
    previous_side_by_coin: dict[str, int] = {}
    out: list = []
    for fill in events:
        side = sens_fill(fill)
        if side == 0:
            continue
        coin = str(fill.get("coin") or "").upper()
        event_time = int(fill.get("time") or 0)
        decision_time = int(fill.get("_received_at_ms") or fill.get("received_at_ms") or event_time)
        direct_twap_id = twap_id_fill(fill, idx_twap)
        source = "DIRECT_TWAP_ID" if direct_twap_id is not None else "INFERRED_METAORDER"
        if direct_twap_id is not None:
            group_id = twap_metaorder_id(vault, coin, direct_twap_id)
        else:
            group_id = inferred_by_coin.get(coin)
            prior = groups.get(group_id or "")
            if (
                prior is None
                or prior["side"] != side
                or event_time - prior["last_time_ms"] > intervalle_ms
            ):
                group_id = metaorder_id(vault, coin, side, event_time)
                inferred_by_coin[coin] = group_id
        current = groups.get(group_id)
        is_new = current is None
        reversal = bool(is_new and previous_side_by_coin.get(coin) == -side)
        if current is None:
            current = {
                "side": side,
                "first_time_ms": event_time,
                "last_time_ms": event_time,
                "slice_count": 0,
                "executed_from_fills": 0.0,
            }
            groups[group_id] = current
            previous_side_by_coin[coin] = side
        previous_time = current["last_time_ms"]
        current["slice_count"] += 1
        current["last_time_ms"] = event_time
        try:
            slice_size = abs(float(fill.get("sz") or 0.0))
        except (TypeError, ValueError):
            slice_size = 0.0
        current["executed_from_fills"] += slice_size

        observed_state = None
        if direct_twap_id is not None:
            observed_state = etat_twap_observable(
                twap_state_snapshots,
                direct_twap_id,
                as_of_ms=decision_time,
            )
        total_size = (observed_state or {}).get("total_size")
        executed_size = max(
            current["executed_from_fills"],
            float((observed_state or {}).get("executed_size") or 0.0),
        )
        if total_size:
            residual_size = max(0.0, float(total_size) - executed_size)
            fraction_executed = min(1.0, executed_size / float(total_size))
            residual_status = "MEASURED_FROM_TWAP_STATE"
        else:
            residual_size = None
            fraction_executed = None
            residual_status = "RESIDUAL_UNMEASURABLE"
        if reversal:
            stage = "REVERSAL"
        elif fraction_executed is not None and fraction_executed >= LATE_FRAC:
            stage = "LATE_STAGE"
        elif current["slice_count"] == 1:
            stage = "FIRST_SLICE"
        else:
            stage = "CONTINUATION"

        normal_slice_size = (observed_state or {}).get("normal_slice_size")
        catch_up_ratio = (
            slice_size / float(normal_slice_size)
            if normal_slice_size and float(normal_slice_size) > 0
            else None
        )
        if catch_up_ratio is None:
            slice_mode = "UNMEASURABLE"
        elif catch_up_ratio > TWAP_CATCH_UP_RATIO:
            slice_mode = "CATCH_UP"
        else:
            slice_mode = "NORMAL"
        started_at = int((observed_state or {}).get("started_at_ms") or current["first_time_ms"])
        duration_ms = float((observed_state or {}).get("minutes") or 0.0) * 60_000.0
        eta_ms = max(0, round(started_at + duration_ms - decision_time)) if duration_ms > 0 else None
        out.append({
            "_fill": fill,
            "metaorder_id": group_id,
            "twap_id": direct_twap_id,
            "metaorder_source": source,
            "is_twap": direct_twap_id is not None,
            "stade": stage,
            "metaorder_started_at_ms": current["first_time_ms"],
            "slice_i": current["slice_count"] - 1,
            "n_slices_observed": current["slice_count"],
            "slice_size": slice_size,
            "slice_mode": slice_mode,
            "catch_up_ratio": round(catch_up_ratio, 6) if catch_up_ratio is not None else None,
            "cadence_ms": event_time - previous_time if current["slice_count"] > 1 else None,
            "estimated_total_size": total_size,
            "executed_cumulative_size": round(executed_size, 12),
            "fraction_executed": round(fraction_executed, 8) if fraction_executed is not None else None,
            "residual_estimated_size": round(residual_size, 12) if residual_size is not None else None,
            "residual_status": residual_status,
            "eta_ms": eta_ms,
            "reduce_only": (observed_state or {}).get("reduce_only"),
            "twap_state_observed_at_ms": (observed_state or {}).get("observed_at_ms"),
            "decision_time_ms": decision_time,
            "causal_replay": True,
            "shadow": True,
            "real_execution": False,
        })
    return out


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
    """Classe un préfixe causal ; `n` reste accepté pour compatibilité mais n'est pas consulté."""
    if meta.get("reversal") and i == 0:
        return "REVERSAL"
    fraction = meta.get("fraction_executed")
    if fraction is not None and float(fraction) >= late_frac:
        return "LATE_STAGE"
    if i == 0:
        return "FIRST_SLICE"
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
                       intervalle_ms: float = INTERVALLE_METAORDRE_MS, maintenant_ms: float | None = None,
                       twap_state_snapshots=None) -> list:
    """CŒUR TESTABLE : fills BRUTS d'un (vault, coin) → un signal par slice, avec metaorder_id STABLE, stade,
    TWAP, taille rel, maker/taker, les 3 âges, jour, coût L2 réel (via cout_fn) et PnL forward net + placebo.
    IMPORTANT : le coût L2 est calculé pour NOTRE taille de copie (`copy_notional_usd`, petite), PAS pour la
    taille du LEADER (qui sert à la capacité/taille relative) — sinon le slippage du leader fausse tout.
    N'ouvre RIEN ; slice sans forward → pnl_net_bps=None (jamais inventé). Fills dédupliqués en amont."""
    now = maintenant_ms if maintenant_ms is not None else time.time() * 1000
    cfn = cout_fn or _cout_screening
    replay = rejouer_metaordres_causaux(
        fills,
        vault=vault,
        idx_twap=idx_twap,
        twap_state_snapshots=twap_state_snapshots,
        intervalle_ms=intervalle_ms,
    )
    out: list = []
    for evidence in replay:
        f = evidence["_fill"]
        t = int(f.get("time") or 0)
        sens = sens_fill(f)
        coin0 = str(f.get("coin") or "").upper()
        sz = abs(float(f.get("sz") or 0.0))
        px = f.get("px")
        try:
            taille_usd = sz * float(px) if px is not None else None
        except (TypeError, ValueError):
            taille_usd = None
        cout_bps, cout_src = cfn(coin0, copy_notional_usd)
        pe_coin = prix_au(tape_coin, t) if tape_coin else (float(px) if px is not None else None)
        pf_coin = prix_au(tape_coin, t + horizon_ms) if tape_coin else None
        pe_btc = prix_au(tape_btc, t) if tape_btc else None
        pf_btc = prix_au(tape_btc, t + horizon_ms) if tape_btc else None
        plc = placebo_bps(pe_coin, pf_coin, pe_btc, pf_btc, sens) or {}
        total_size = evidence.get("estimated_total_size")
        public_evidence = {key: value for key, value in evidence.items() if key != "_fill"}
        out.append({
            **public_evidence,
            "sens": sens,
            "vault": vault,
            "coin": coin0,
            "n_slices": evidence["n_slices_observed"],
            "taille_usd": round(taille_usd, 2) if taille_usd is not None else None,
            "taille_relative": round(sz / float(total_size), 4) if total_size else None,
            "maker_taker": maker_taker(f),
            "age_stade_ms": t - int(evidence["metaorder_started_at_ms"]),
            "age_fill_hl_ms": round(now - t),
            "latence_locale_ms": None,
            "jour": int(t // JOUR_MS),
            "horizon_ms": horizon_ms,
            "cout_ar_bps": cout_bps,
            "cout_source": cout_src,
            "cout_notional_usd": copy_notional_usd,
            "pnl_net_bps": pnl_forward_net_bps(pe_coin, pf_coin, sens, cout_bps),
            "ret_coin_bps": plc.get("ret_coin_bps"),
            "ret_marche_bps": plc.get("ret_marche_bps"),
            "alpha_vs_marche_bps": plc.get("alpha_vs_marche_bps"),
            "fill_time": t,
            "tid": f.get("tid"),
            "oid": f.get("oid"),
            "hash": f.get("hash"),
        })
    return out


def evaluer_delais_entree(
    signaux: list,
    tape_par_coin: dict,
    *,
    delays_ms=DELAIS_ENTREE_MS,
    horizon_ms: float = HORIZON_FWD_MS,
) -> dict:
    """Mesure SHADOW des délais pré-enregistrés, avec une sortie à horizon fixe."""
    result: dict = {}
    for delay in delays_ms:
        by_stage: dict[str, list[float]] = {}
        n_unmeasurable = 0
        for signal in signaux or []:
            coin = str(signal.get("coin") or "").upper()
            tape = (tape_par_coin or {}).get(coin) or []
            t0 = int(signal.get("fill_time") or 0)
            entry = prix_au(tape, t0 + int(delay))
            exit_price = prix_au(tape, t0 + int(horizon_ms))
            pnl = pnl_forward_net_bps(
                entry,
                exit_price,
                int(signal.get("sens") or 0),
                float(signal.get("cout_ar_bps") or 0.0),
            )
            if pnl is None:
                n_unmeasurable += 1
                continue
            by_stage.setdefault(str(signal.get("stade") or "UNKNOWN"), []).append(pnl)
        result[str(int(delay))] = {
            "delay_ms": int(delay),
            "n_mesurable": sum(len(values) for values in by_stage.values()),
            "n_non_mesurable": n_unmeasurable,
            "par_stade": {
                stage: {
                    "n": len(values),
                    "pnl_net_bps_moy": round(sum(values) / len(values), 6),
                }
                for stage, values in sorted(by_stage.items())
            },
            "shadow": True,
            "real_execution": False,
        }
    return result


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


NOTIONALS_DEFAUT = (10.0, 25.0, 50.0, 100.0, 250.0, 500.0)   # courbe edge/coûts par taille de copie
PREREG_RELPATH = Path("runtime") / "data" / "metaorder_preregistration.json"


def vwap_slippage(book: dict, notional_usd: float, sens: int) -> tuple:
    """WALK du carnet l2Book pour un notional : côté ASK si achat (sens>0), BID si vente. Rend
    (vwap, slippage_bps_vs_mid, filled_usd, profondeur_suffisante). Slippage = coût d'exécuter la TAILLE
    (inclut le demi-spread du touch). profondeur_suffisante=False si le carnet ne remplit pas le notional."""
    try:
        bids, asks = book["levels"][0], book["levels"][1]
        bid, ask = float(bids[0]["px"]), float(asks[0]["px"])
    except (KeyError, IndexError, TypeError, ValueError):
        return (None, None, 0.0, False)
    if bid <= 0 or ask <= 0:
        return (None, None, 0.0, False)
    mid = 0.5 * (bid + ask)
    cote = asks if sens > 0 else bids
    reste, base = float(notional_usd), 0.0
    for niv in cote:
        try:
            px, sz = float(niv["px"]), float(niv["sz"])
        except (KeyError, TypeError, ValueError):
            continue
        pris = min(px * sz, reste)
        if px > 0:
            base += pris / px
        reste -= pris
        if reste <= 1e-9:
            break
    filled = float(notional_usd) - reste
    if base <= 0:
        return (None, None, 0.0, False)
    vwap = filled / base
    slip = sens * (vwap - mid) / mid * 1e4
    return (round(vwap, 8), round(slip, 3), round(filled, 2), reste <= 1e-9)


def cout_composants(book: dict, notional_usd: float, sens: int, fee_ar_bps: float) -> dict | None:
    """Coût aller-retour DÉCOMPOSÉ pour un notional : spread (½ à l'entrée + ½ à la sortie), slippage VWAP PUR
    (impact au-delà du touch, ×2 A/R) et frais (palier exact, déjà A/R dans fee_ar_bps). Rend chaque composant
    séparément + le total. None si carnet illisible."""
    v = vwap_slippage(book, notional_usd, sens)
    vwap, slip_touch, filled, complet = v
    try:
        bids, asks = book["levels"][0], book["levels"][1]
        bid, ask = float(bids[0]["px"]), float(asks[0]["px"])
        mid = 0.5 * (bid + ask)
        spread = (ask - bid) / mid * 1e4
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    if vwap is None or slip_touch is None:
        return None
    slip_pur = max(0.0, slip_touch - spread / 2.0)                # au-delà du 1er niveau (le ½ spread est le touch)
    cout_ar = spread + 2.0 * slip_pur + float(fee_ar_bps)
    return {"spread_bps": round(spread, 3), "slippage_vwap_bps": round(2.0 * slip_pur, 3),
            "fee_bps": round(float(fee_ar_bps), 3), "vwap": vwap, "cout_ar_bps": round(cout_ar, 3),
            "profondeur_suffisante": complet, "filled_usd": filled}


FEE_AR_BASE_BPS = 9.0                      # scénario CONSERVATEUR de base (taker A/R) tant que le palier n'est pas prouvé
FEES_TIERS_DEFAUT = (9.0, 7.0, 5.0)        # paliers pour la sensibilité de la capacité


def courbe_edge_cout(signaux: list, book_par_coin: dict, *, book_sync: dict | None = None,
                     fee_ar_bps: float = FEE_AR_BASE_BPS, notionals=NOTIONALS_DEFAUT,
                     fees_tiers=FEES_TIERS_DEFAUT, n_boot: int = 1000) -> dict:
    """Courbe EDGE/COÛTS par STADE et par NOTIONAL : net = gross(ret_coin_bps) − coût_A/R(notional) au VRAI
    carnet (spread + slippage VWAP + frais). Par stade :
    • `courbe` : {notional: {net_moy, **IC95 clusterisé**, n_métaordres, spread, slippage, fee, %profondeur}} ;
    • `profondeur_suffisante_usd` : plus grand notional où le carnet remplit 100 % (≠ capacité d'edge) ;
    • `l2_synchronise_pct` : % de signaux dont le carnet est HORODATÉ au fill (pas le carnet courant) ;
    • **`capacite_edge_prouve_usd_par_palier`** : par palier de frais, plus grand notional où la **BORNE BASSE**
      de l'IC95 > 0 (edge PROUVÉ) — **ET** carnet synchronisé (sinon 0 : un carnet courant sur des fills
      historiques n'prouve rien). Un point estimate positif à IC traversant 0 ⇒ capacité **0 $**."""
    from collections import defaultdict
    bs = book_sync or {}
    parstade = defaultdict(list)
    for s in signaux:
        parstade[s.get("stade")].append(s)
    out: dict = {}
    for stade, xs in parstade.items():
        courbe = {}
        n_sync = sum(1 for s in xs if s.get("l2_synchronise"))
        sync_pct = round(100 * n_sync / len(xs), 1) if xs else 0.0
        prof_ok = 0.0
        for N in notionals:
            paires, sp, sl, cp, tot = [], [], [], 0, 0
            for s in xs:
                g = s.get("ret_coin_bps")
                book = bs.get((s.get("coin"), s.get("hash"), s.get("fill_time"))) or book_par_coin.get(s.get("coin"))
                if g is None or not book:
                    continue
                cc = cout_composants(book, N, int(s.get("sens") or 1), fee_ar_bps)
                if not cc:
                    continue
                paires.append((s.get("metaorder_id"), float(g) - cc["cout_ar_bps"]))
                sp.append(cc["spread_bps"])
                sl.append(cc["slippage_vwap_bps"])
                tot += 1
                cp += 1 if cc["profondeur_suffisante"] else 0
            boot = bootstrap_clusterise(paires, n=n_boot)
            prof_pct = round(100 * cp / tot, 1) if tot else None
            if prof_pct == 100.0:
                prof_ok = max(prof_ok, float(N))
            courbe[str(int(N))] = {"net_moy_bps": boot["moy"], "net_ic95": [boot["ic_bas"], boot["ic_haut"]],
                                   "n_metaordres": boot["n_clusters"],
                                   "spread_moy_bps": round(sum(sp) / len(sp), 2) if sp else None,
                                   "slippage_moy_bps": round(sum(sl) / len(sl), 2) if sl else None,
                                   "fee_bps": round(float(fee_ar_bps), 2), "profondeur_suffisante_pct": prof_pct}
        capa_palier: dict = {}
        for tier in fees_tiers:
            shift = float(fee_ar_bps) - float(tier)                # net augmente de `shift` si le palier est plus bas
            cap = 0.0
            if sync_pct >= 100.0:                                  # capacité d'EDGE PROUVÉ exige un carnet synchronisé
                for N in notionals:
                    icb = courbe[str(int(N))]["net_ic95"][0]
                    if icb is not None and (icb + shift) > 0:      # BORNE BASSE > 0 = edge prouvé (pas le point)
                        cap = max(cap, float(N))
            capa_palier[str(tier)] = cap
        out[stade] = {"courbe": courbe, "profondeur_suffisante_usd": prof_ok, "l2_synchronise_pct": sync_pct,
                      "capacite_edge_prouve_usd_par_palier": capa_palier,
                      "capacite_edge_prouve_usd": capa_palier.get(str(float(fee_ar_bps)), 0.0)}
    return out


def comparer_executions(signal: dict, tape_coin: list, book: dict, *, fee_taker_ar_bps: float,
                        fee_maker_ar_bps: float, notional_usd: float = 100.0, horizon_ms: float = HORIZON_FWD_MS,
                        fenetre_passif_ms: float = 60_000.0) -> dict:
    """Compare 3 exécutions en SHADOW pour un signal, SANS fill fictif :
    • taker_immediat : net = gross − coût_A/R(taker, notional) au vrai carnet ;
    • limite_passive_bornee : limite au TOUCH passif (bid si achat), valable fenetre_passif_ms. FILL SEULEMENT si
      le tape atteint notre limite (sinon `rempli=False` = fill MANQUÉ). Si rempli : délai, queue devant (taille
      au niveau), adverse selection (rendement conditionnel au fill) ; frais maker, ~0 slippage/spread ;
    • no_trade : 0. Rend un dict complet. Aucune position inventée."""
    sens = int(signal.get("sens") or 1)
    t = int(signal.get("fill_time") or 0)
    pe = prix_au(tape_coin, t)
    pf = prix_au(tape_coin, t + horizon_ms)
    res = {"taker_immediat": None, "limite_passive": None, "no_trade": 0.0}
    # taker
    cc = cout_composants(book, notional_usd, sens, fee_taker_ar_bps)
    if pe and pf is not None and cc:
        res["taker_immediat"] = round(sens * (pf - pe) / pe * 1e4 - cc["cout_ar_bps"], 3)
    # passive au touch
    try:
        bids, asks = book["levels"][0], book["levels"][1]
        limite = float(bids[0]["px"]) if sens > 0 else float(asks[0]["px"])
        q_sz = float((bids[0] if sens > 0 else asks[0])["sz"])
    except (KeyError, IndexError, TypeError, ValueError):
        limite = q_sz = None
    if limite and pf is not None:
        # fill si le tape franchit la limite dans la fenêtre (achat: prix <= limite ; vente: prix >= limite)
        t_fill = None
        for (tt, px) in tape_coin or []:
            if t < tt <= t + fenetre_passif_ms and ((sens > 0 and px <= limite) or (sens < 0 and px >= limite)):
                t_fill = tt
                break
        if t_fill is None:
            res["limite_passive"] = {"rempli": False, "raison": "fill_manque"}
        else:
            net = sens * (pf - limite) / limite * 1e4 - float(fee_maker_ar_bps)   # entrée au touch, frais maker
            adverse = sens * (prix_au(tape_coin, t_fill + 5_000) - limite) / limite * 1e4 \
                if prix_au(tape_coin, t_fill + 5_000) is not None else None
            res["limite_passive"] = {"rempli": True, "delai_ms": t_fill - t, "queue_devant_usd": round((q_sz or 0) * limite, 1),
                                     "adverse_selection_bps": round(adverse, 3) if adverse is not None else None,
                                     "net_bps": round(net, 3)}
    return res


def write_preregistration(root, *, notionals=NOTIONALS_DEFAUT, horizon_ms: float = HORIZON_FWD_MS) -> Path:
    """PRÉ-ENREGISTRE (une seule fois, jamais réécrit → anti data-snooping) l'UNIQUE variante future testable :
    `CONTINUATION/LATE + OFI top-5`, exécutions {taker_immediat, limite_passive_bornee, no_trade}, validée
    UNIQUEMENT en walk-forward OOS sur les PROCHAINES fenêtres. Aucune sélection/retune sur la fenêtre courante."""
    p = Path(root) / PREREG_RELPATH
    if p.exists():
        return p                                                 # gelé : on ne réécrit JAMAIS (anti-retune)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "version": "prereg_v1", "gele_le_ts_ms": int(time.time() * 1000),
        "hypothese_unique": {"stades": ["CONTINUATION", "LATE_STAGE"], "filtre": "OFI_top5>0 (confirmation flux)",
                             "executions_comparees": ["taker_immediat", "limite_passive_bornee", "no_trade"],
                             "notionals_usd": list(notionals), "horizon_ms": horizon_ms,
                             "l2_eligibilite": {"book_posterieur_au_fill": True, "latence_plafond_ms": 2000,
                                                "note": "sinon L2_NON_SYNCHRONISE : capturé mais exclu des coûts/OOS"}},
        "regle_validation": "walk-forward OOS sur les PROCHAINES fenetres UNIQUEMENT ; aucune selection ni retune "
                            "sur la fenetre courante",
        "regle_decision": "n'ouvrir une cohorte QUE si edge net FORTEMENT positif apres couts, contre placebo, "
                          "sur OOS futur ; sinon KILL/OBSERVE",
        "note": "pre-enregistre pour eviter le data-snooping ; JAMAIS modifie retroactivement",
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    return p


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

    def book_provider(coin):
        import sys as _s
        _s.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
        from collecter_carnet import _post_hl
        return _post_hl(coin, timeout_s=6.0)                      # carnet BRUT {levels:[bids,asks]} pour le VWAP-walk
    return userfills_by_time_rest, twap_provider, book_provider


def _resume_book(book) -> dict | None:
    """Résumé {hl_bid, hl_ask, depth_usd top-5} depuis un carnet BRUT (pour le coût per-signal existant)."""
    try:
        bids, asks = book["levels"][0], book["levels"][1]
        bid, ask = float(bids[0]["px"]), float(asks[0]["px"])
        mid = 0.5 * (bid + ask)
        depth = min(sum(float(x["sz"]) for x in bids[:5]), sum(float(x["sz"]) for x in asks[:5])) * mid
        return {"hl_bid": bid, "hl_ask": ask, "depth_usd": round(depth, 2)}
    except (KeyError, IndexError, TypeError, ValueError):
        return None


def executer(root: str | Path, vaults: list, *, fills_provider=None, twap_provider=None, book_provider=None,
             twap_state_provider=None, tape=None, horizon_ms: float = HORIZON_FWD_MS, fenetre_ms: float = 7_200_000.0,
             config_hash: str = "", git_commit: str = "", maintenant_ms: float | None = None) -> dict:
    """Passe SHADOW : par vault, `userFillsByTime` + `userTwapSliceFills` (statut TWAP) ; carnet BRUT par coin
    (VWAP-walk) → coût per-signal + **courbe edge/coûts par notional** (10..500 $, spread/slippage/frais séparés,
    VRAIE capacité L2) + **comparaison d'exécutions** (taker/passif/no-trade) sur CONTINUATION/LATE. Pré-enregistre
    l'unique variante future. Écrit ledger + stats (clusterisées, walk-forward, groupées) + budget REST EXACT.
    INJECTABLE pour test. N'OUVRE AUCUNE POSITION."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "tools"))
    import sonde_confirmation_vaults as SD
    root = Path(root)
    now = maintenant_ms if maintenant_ms is not None else time.time() * 1000
    if fills_provider is None or twap_provider is None or book_provider is None:
        fp, tp, bp = _providers_reels()
        fills_provider = fills_provider or fp
        twap_provider = twap_provider or tp
        book_provider = book_provider or bp
    if tape is None:
        try:
            from hl_observer.experimental.copy_edge_forward import charger_prix_tape
            tape = charger_prix_tape(root)
        except Exception:  # noqa: BLE001
            tape = {}
    fee_base = FEE_AR_BASE_BPS                                    # 9 bps A/R : scénario CONSERVATEUR de base
    try:
        from hl_observer.experimental.carry_deux_jambes import frais_venues
        fee_config = round(2.0 * float(frais_venues(root)[0]), 3)  # palier CONFIG (donnée de sensibilité, PAS le défaut)
    except Exception:  # noqa: BLE001
        fee_config = 7.0
    from hl_observer.experimental import (
        metaorder_l2_tape as MT,  # tape L2 synchronisée (coût entrée/sortie horodaté)
    )
    tape_l2 = MT.charger_tape(root)
    tape_btc = tape.get("BTC") or []
    start = int(now - fenetre_ms)
    signaux: list = []
    appels_budget: list = []
    twap_statut: dict = {}
    book_cache: dict = {}

    def _book(coin):
        if coin not in book_cache:
            try:
                book_cache[coin] = book_provider(coin)
                appels_budget.append(("l2Book", 0))
            except Exception:  # noqa: BLE001
                book_cache[coin] = None
        return book_cache.get(coin)

    def _cout_fn(coin, notional_usd):
        return cout_l2_reel_bps(_resume_book(_book(coin)), notional_usd)

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
        try:
            twap_states = twap_state_provider(v, now) if twap_state_provider is not None else []
        except Exception:  # noqa: BLE001
            twap_states = []
        if not isinstance(fills, list):
            continue
        idx = index_twap(twaps if isinstance(twaps, list) else [])
        par_coin: dict = {}
        for f in fills:
            if int((f or {}).get("time") or 0) <= now - horizon_ms:   # assez vieux : forward disponible
                par_coin.setdefault(str(f.get("coin") or "").upper(), []).append(f)
        for coin, fs in par_coin.items():
            sigs = construire_signaux(fs, vault=v, idx_twap=idx, tape_coin=tape.get(coin) or [],
                                      tape_btc=tape_btc, cout_fn=_cout_fn, horizon_ms=horizon_ms, maintenant_ms=now,
                                      twap_state_snapshots=twap_states)
            for s in sigs:
                s.update({"version": VERSION, "config_hash": config_hash, "git_commit": git_commit,
                          "shadow": True, "real_execution": False, "ts_ms": int(now)})
            signaux.extend(sigs)

    book_par_coin = {c: b for c, b in book_cache.items() if b}
    # SYNCHRONISATION L2 : carnet HORODATÉ au fill (tape) — sinon carnet COURANT = provisoire, ne prouve rien
    book_sync: dict = {}
    for s in signaux:
        c = tape_l2.get(MT.cle_fill(s.get("coin"), s.get("hash"), s.get("fill_time")), {}).get("fill")
        ent = (c or {}).get("entree") or {}
        # ÉLIGIBLE seulement si carnet d'entrée POSTÉRIEUR au fill ET sous le plafond de latence pré-enregistré :
        # une ligne capturée mais non synchronisée (ex. FIRST_SLICE 7 s) est CONSERVÉE mais EXCLUE des coûts/OOS.
        a_book = bool(ent.get("bids")) and MT.est_eligible(c)
        s["l2_synchronise"] = a_book
        s["l2_eligibilite"] = MT.statut_eligibilite(c) if c else "ABSENT"
        s["microstructure_features"] = (c or {}).get("microstructure_features")
        s["microstructure_gate"] = (c or {}).get("microstructure_gate")
        if a_book:
            book_sync[(s.get("coin"), s.get("hash"), s.get("fill_time"))] = {
                "levels": [[{"px": b[0], "sz": b[1]} for b in ent.get("bids", [])],
                           [{"px": a[0], "sz": a[1]} for a in ent.get("asks", [])]]}
    n_sync = sum(1 for s in signaux if s.get("l2_synchronise"))
    courbe = courbe_edge_cout(signaux, book_par_coin, book_sync=book_sync, fee_ar_bps=fee_base,
                              fees_tiers=(fee_base, fee_config, 5.0))
    execs = _comparer_stades(signaux, tape, book_par_coin, fee_base, horizon_ms)   # taker/passif/no-trade
    prereg = write_preregistration(root, horizon_ms=horizon_ms)
    stats = stats_par_stade(signaux)
    wf = walk_forward_purge(signaux, horizon_ms=horizon_ms)
    delais = evaluer_delais_entree(signaux, tape, horizon_ms=horizon_ms)
    microstructure_ablation = MT.ablation_microstructure(signaux)
    poids = SD.poids_info(appels_budget)
    SD.journaliser_budget(root, "metaorder_shadow", poids, 600.0)
    budget = SD.budget_total(root)
    n_twap = {k: sum(1 for vv in twap_statut.values() if vv == k) for k in set(twap_statut.values())}
    _ecrire(root, signaux, {
        "version": VERSION, "n_signaux": len(signaux), "n_metaordres": len({s["metaorder_id"] for s in signaux}),
        "fee_ar_base_bps": fee_base, "fee_config_bps": fee_config,
        "l2_synchronise_pct": round(100 * n_sync / len(signaux), 1) if signaux else 0.0,
        "n_dans_tape_l2": len(tape_l2),
        "stats_par_stade": stats, "courbe_edge_cout_par_notional": courbe,
        "execution_comparee_continuation_late": execs, "walk_forward_purge": wf,
        "delais_entree_shadow": delais, "microstructure_ablation": microstructure_ablation,
        "par_vault": agreger_par(signaux, "vault"), "par_coin": agreger_par(signaux, "coin"),
        "par_jour": agreger_par(signaux, "jour"), "twap_statut_par_vault": n_twap,
        "preregistration": str(prereg.name),
        "budget_rest": {"poids_passe": poids, "n_appels": len(appels_budget), "total_ip": budget},
    }, now)
    return {"n_signaux": len(signaux), "n_metaordres": len({s["metaorder_id"] for s in signaux}),
            "poids_passe": poids, "n_appels": len(appels_budget), "budget_total": budget,
            "l2_synchronise_pct": round(100 * n_sync / len(signaux), 1) if signaux else 0.0,
            "stats": stats, "courbe": courbe, "execs": execs, "delais": delais,
            "microstructure_ablation": microstructure_ablation}


def _comparer_stades(signaux: list, tape: dict, book_par_coin: dict, fee_ar: float, horizon_ms: float,
                     *, notional_usd: float = 100.0) -> dict:
    """Agrège la comparaison taker/passif/no-trade sur les stades pré-enregistrés (CONTINUATION/LATE), à
    notional=100 $. Passif : taux de fill, délai, adverse selection (aucun fill fictif)."""
    from collections import defaultdict
    g: dict = defaultdict(lambda: {"taker": [], "fill": 0, "miss": 0, "net": [], "delai": [], "adverse": []})
    for s in signaux:
        if s.get("stade") not in ("CONTINUATION", "LATE_STAGE"):
            continue
        book = book_par_coin.get(s.get("coin"))
        if not book:
            continue
        r = comparer_executions(s, tape.get(s.get("coin")) or [], book, fee_taker_ar_bps=fee_ar,
                                fee_maker_ar_bps=fee_ar, notional_usd=notional_usd, horizon_ms=horizon_ms)
        gg = g[s["stade"]]
        if r["taker_immediat"] is not None:
            gg["taker"].append(r["taker_immediat"])
        lp = r.get("limite_passive")
        if isinstance(lp, dict):
            if lp.get("rempli"):
                gg["fill"] += 1
                gg["net"].append(lp["net_bps"])
                gg["delai"].append(lp["delai_ms"])
                if lp.get("adverse_selection_bps") is not None:
                    gg["adverse"].append(lp["adverse_selection_bps"])
            else:
                gg["miss"] += 1
    out: dict = {}
    for st, d in g.items():
        nf, nm = d["fill"], d["miss"]
        out[st] = {"notional_usd": notional_usd,
                   "taker_net_moy_bps": round(sum(d["taker"]) / len(d["taker"]), 2) if d["taker"] else None,
                   "passif_fill_rate_pct": round(100 * nf / (nf + nm), 1) if (nf + nm) else None,
                   "passif_net_moy_bps_si_fill": round(sum(d["net"]) / len(d["net"]), 2) if d["net"] else None,
                   "passif_delai_moy_ms": round(sum(d["delai"]) / len(d["delai"])) if d["delai"] else None,
                   "passif_adverse_moy_bps": round(sum(d["adverse"]) / len(d["adverse"]), 2) if d["adverse"] else None,
                   "no_trade_net_bps": 0.0}
    return out


def _ecrire(root: Path, signaux: list, resume: dict, now: float) -> None:
    (root / LEDGER_RELPATH).parent.mkdir(parents=True, exist_ok=True)
    with (root / LEDGER_RELPATH).open("a", encoding="utf-8") as fh:
        for s in signaux:
            fh.write(json.dumps(s, ensure_ascii=False) + "\n")
    p = root / STATS_RELPATH
    tmp = p.with_suffix(".json.tmp")
    tmp.write_text(json.dumps({"ts_ms": int(now), **resume}, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(p)


__all__ = ["VERSION", "sens_fill", "maker_taker", "dedup_fills", "metaorder_id", "twap_metaorder_id",
           "index_twap", "twap_id_fill", "est_twap", "normaliser_twap_states", "etat_twap_observable",
           "rejouer_metaordres_causaux", "detecter_metaordres", "classer_stade", "pnl_forward_net_bps",
           "placebo_bps", "ofi_top5", "prix_au", "cout_l2_reel_bps", "construire_signaux",
           "evaluer_delais_entree", "DELAIS_ENTREE_MS", "bootstrap_clusterise", "walk_forward_purge",
           "stats_par_stade", "agreger_par", "vwap_slippage", "cout_composants", "courbe_edge_cout",
           "comparer_executions", "write_preregistration", "NOTIONALS_DEFAUT", "executer",
           "LEDGER_RELPATH", "STATS_RELPATH", "PREREG_RELPATH"]
