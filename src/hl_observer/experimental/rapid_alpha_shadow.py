"""RAPID_ALPHA_SHADOW — lead-lag cross-venue Binance→HL, SHADOW (n'ouvre RIEN). PUR, sans réseau.

Timebox : quelques HEURES, décision **SCALE/KILL** rapide. Teste si les retours **Binance PRÉCÈDENT** les
retours **HL** du même coin (hypothèse **cross-venue**, NON réfutée — distincte du lead-lag **intra-HL**
BTC→alts déjà mort 0/66 [[cloture-291-et-lead-lag-mort-20260714]]).

Un lead n'est retenu comme candidat que s'il est **(a)** à un lag STRICTEMENT positif (Binance devant),
**(b)** assez corrélé, **(c)** à un horizon > notre latence, **(d)** d'amplitude capturable > **coûts HL A/R
complets**. Sinon KILL. Aucune promesse : on mesure, on tranche.

Données : jambe HL **déjà locale** (bbo_tape / allMids → mids HL) ; jambe Binance = archives publiques GRATUITES
(`data.binance.vision`, sans compte) à tirer sur Windows. Ce module ne fait QUE l'analyse (aucun téléchargement).
"""
from __future__ import annotations

import math

SEUIL_CORR = 0.15                    # corrélation minimale d'un lead cross-venue crédible (préliminaire, prudent)
FEE_AR_BPS = 9.0                     # coûts HL A/R complets (base conservatrice, cohérente avec le live)


def serie_retours(mids: list, pas_ms: float) -> list:
    """[(ts_ms, mid)] → [(bucket_ts, retour_log_bps)] échantillonné à `pas_ms` (dernier mid par bucket)."""
    if not mids:
        return []
    par_bucket = {}
    for t, m in sorted(mids):
        if m and m > 0:
            par_bucket[int(t // pas_ms)] = float(m)              # dernier mid du bucket
    buckets = sorted(par_bucket)
    out = []
    for i in range(1, len(buckets)):
        if buckets[i] == buckets[i - 1] + 1:                     # buckets CONTIGUS (pas de trou)
            pa, pb = par_bucket[buckets[i - 1]], par_bucket[buckets[i]]
            out.append((buckets[i], math.log(pb / pa) * 1e4))    # retour en bps
    return out


def _aligner(a: list, b: list) -> tuple:
    """Deux séries [(bucket, ret)] au même pas → (xs, ys) alignées sur les buckets COMMUNS."""
    da, db = dict(a), dict(b)
    communs = sorted(set(da) & set(db))
    return [da[t] for t in communs], [db[t] for t in communs], communs


def correl(xs: list, ys: list) -> float | None:
    n = len(xs)
    if n < 8:
        return None
    mx, my = sum(xs) / n, sum(ys) / n
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    sxx = sum((x - mx) ** 2 for x in xs)
    syy = sum((y - my) ** 2 for y in ys)
    if sxx <= 0 or syy <= 0:
        return None
    return sxy / math.sqrt(sxx * syy)


def profil_lead_lag(ret_binance: list, ret_hl: list, lags: range) -> dict:
    """{lag: corr(binance[t], hl[t+lag])}. **lag > 0 ⇒ Binance DEVANCE HL** de `lag` pas."""
    bt = {t: r for t, r in ret_binance}
    ht = {t: r for t, r in ret_hl}
    communs = sorted(set(bt) & set(ht))
    prof = {}
    for k in lags:
        xs = [bt[t] for t in communs if (t + k) in ht]
        ys = [ht[t + k] for t in communs if (t + k) in ht]
        c = correl(xs, ys)
        if c is not None:
            prof[k] = round(c, 4)
    return prof


def meilleur_lead(profil: dict) -> tuple:
    """(lag*, corr*) au |corr| max PARMI LES LAGS > 0 (on ne veut qu'un Binance-DEVANT). (None, None) si vide."""
    pos = {k: v for k, v in profil.items() if k > 0}
    if not pos:
        return None, None
    lag = max(pos, key=lambda k: abs(pos[k]))
    return lag, pos[lag]


def _sigma_bps(ret: list) -> float:
    xs = [r for _, r in ret]
    n = len(xs)
    if n < 2:
        return 0.0
    m = sum(xs) / n
    return math.sqrt(sum((x - m) ** 2 for x in xs) / (n - 1))


def verdict(profil: dict, ret_hl: list, *, pas_ms: float, latence_ms: float,
            cout_ar_bps: float = FEE_AR_BPS, seuil_corr: float = SEUIL_CORR) -> dict:
    """SCALE/KILL borné. Candidat SEULEMENT si lead>latence ET |corr|≥seuil ET amplitude capturable > coûts."""
    lag, corr = meilleur_lead(profil)
    sigma = _sigma_bps(ret_hl)
    lead_ms = (lag * pas_ms) if lag else 0.0
    capturable_bps = round(abs(corr) * sigma, 2) if corr is not None else 0.0   # fraction prévisible du move HL
    ok = bool(corr is not None and lag and lead_ms > latence_ms
              and abs(corr) >= seuil_corr and capturable_bps > cout_ar_bps)
    return {
        "lead_lag_pas": lag, "lead_ms": lead_ms, "corr": corr,
        "sigma_hl_bps": round(sigma, 2), "capturable_bps": capturable_bps,
        "cout_ar_bps": cout_ar_bps, "latence_ms": latence_ms, "seuil_corr": seuil_corr,
        "verdict": "CANDIDAT_LEAD_SCALE" if ok else "KILL_PAS_DE_LEAD_EXPLOITABLE",
        "regle": "SHADOW — mesure seule. Un candidat n'ouvre une cohorte paper qu'après edge net>0 sur L2 frais.",
    }


def shadow_leadlag(binance_mids: list, hl_mids: list, *, pas_ms: float = 1000.0,
                   lags_max: int = 10, latence_ms: float = 400.0) -> dict:
    """Bout-en-bout : mids Binance + mids HL (même coin) → profil lead-lag + verdict SCALE/KILL."""
    rb = serie_retours(binance_mids, pas_ms)
    rh = serie_retours(hl_mids, pas_ms)
    prof = profil_lead_lag(rb, rh, range(-lags_max, lags_max + 1))
    v = verdict(prof, rh, pas_ms=pas_ms, latence_ms=latence_ms)
    v.update({"n_bucket_binance": len(rb), "n_bucket_hl": len(rh), "profil_lead_lag": prof})
    return v


def par_heure(mids: list) -> dict:
    """Régimes horaires : σ des retours (bps) par heure-de-jour UTC — pour cibler les fenêtres actives."""
    from collections import defaultdict
    seaux = defaultdict(list)
    for t, r in serie_retours(mids, 1000.0):
        seaux[int((t * 1000) // 3_600_000) % 24].append(r)
    return {h: round(_sigma_bps([(0, x) for x in xs]), 2) for h, xs in sorted(seaux.items())}


__all__ = ["serie_retours", "correl", "profil_lead_lag", "meilleur_lead", "verdict",
           "shadow_leadlag", "par_heure", "SEUIL_CORR", "FEE_AR_BPS"]
