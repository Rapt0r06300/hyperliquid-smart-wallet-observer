"""SCORE MULTI-FACTEURS DES VAULTS (rectif Flo 23/07) — on ne sélectionne PLUS sur l'APR seul.

POURQUOI
--------
L'APR affiché par HL est une fenêtre glissante bruitée : un vault peut afficher 900 %/an sur un coup
de chance puis rendre l'argent. Copier un vault ne vaut que s'il est RÉGULIER, peu risqué, ancien,
pas trop concentré, à turnover copiable, avec de la capacité et surtout COPYABLE (positions sur des
coins réellement exécutables). Ce module calcule 8 facteurs MESURÉS depuis l'historique de snapshots,
un composite transparent, et une liste de rétention. Aucun chiffre inventé : si un facteur manque, il
est neutre et signalé.

Les 8 facteurs (chacun normalisé dans [0,1], 1 = meilleur) :
  1. pnl_net       — rendement net sur la fenêtre, corrigé des dépôts/retraits (le vrai gain)
  2. regularite    — part de périodes non-négatives (un gain régulier > un gain en dents de scie)
  3. drawdown      — 1 − drawdown max observé (moins ça a plongé, mieux c'est)
  4. anciennete    — âge du vault (track record)
  5. concentration — 1 − Herfindahl de l'expo par coin (diversifié = moins de risque idiosyncratique)
  6. turnover      — cloche : ni figé (rien à copier) ni frénétique (incopiable, coûts) = optimum au milieu
  7. capacite      — log(TVL) (absorbe la copie sans impact)
  8. copyabilite   — part de l'expo sur des coins exécutables (sinon on ne peut PAS répliquer)

READ-ONLY : ce module lit des snapshots publics, il ne price ni n'exécute rien.
"""
from __future__ import annotations

import math
from typing import Any, Iterable

# bornes de normalisation (transparentes, ajustables) — choisies conservatrices
DD_MAX_TOLERE_PCT = 40.0            # au-delà : score drawdown = 0
AGE_PLEIN_J = 365.0                # 1 an de track record = score ancienneté plein
TVL_REF_LOG = (5.0, 7.5)          # log10(TVL) de 100k$ (5.0) à ~30M$ (7.5) mappé sur [0,1]
TURNOVER_OPTIMUM = 0.15            # ~15 % du NAV re-déployé par période = sweet spot copiable
TURNOVER_LARGEUR = 0.20            # largeur de la cloche autour de l'optimum
# filtre de rétention (un vault non retenu n'est jamais copié)
SEUIL_AGE_J = 45.0
SEUIL_DD_PCT = 45.0
SEUIL_COPYABILITE = 0.5
SEUIL_COMPOSITE = 0.45


def _clamp(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _positions_expo(snap: dict) -> dict[str, float]:
    """{coin: |notional signé|} depuis un snapshot (szi × entryPx)."""
    out: dict[str, float] = {}
    for p in (snap.get("positions") or []):
        c = str(p.get("coin") or "").upper()
        if not c:
            continue
        try:
            out[c] = abs(float(p.get("szi") or 0.0) * float(p.get("entryPx") or 0.0))
        except (TypeError, ValueError):
            continue
    return out


def rendement_net(snaps: list[dict]) -> float:
    """Rendement net sur la fenêtre, corrigé des flux : (Δnav − dépôts_nets) / nav_initial.
    Robuste : sans nav initial exploitable → 0.0 (neutre, jamais inventé)."""
    if len(snaps) < 2:
        return 0.0
    nav0 = float(snaps[0].get("nav_usd") or 0.0)
    nav1 = float(snaps[-1].get("nav_usd") or 0.0)
    if nav0 <= 0:
        return 0.0
    flux = sum(float(s.get("depot_retrait_net_usd") or 0.0) for s in snaps[1:])
    return (nav1 - nav0 - flux) / nav0


def regularite(snaps: list[dict]) -> float:
    """Part de périodes où le NAV (corrigé du flux de la période) n'a pas baissé. 1.0 = jamais en perte."""
    rets = _returns_par_periode(snaps)
    if not rets:
        return 0.0
    return sum(1 for r in rets if r >= 0) / len(rets)


def _returns_par_periode(snaps: list[dict]) -> list[float]:
    rets: list[float] = []
    for a, b in zip(snaps, snaps[1:]):
        na, nb = float(a.get("nav_usd") or 0.0), float(b.get("nav_usd") or 0.0)
        if na > 0:
            flux = float(b.get("depot_retrait_net_usd") or 0.0)
            rets.append((nb - na - flux) / na)
    return rets


def drawdown_max_pct(snaps: list[dict]) -> float:
    """Drawdown max observé (en %). Prend le champ drawdown_pct s'il existe, sinon le calcule du NAV."""
    dds = [float(s.get("drawdown_pct") or 0.0) for s in snaps if s.get("drawdown_pct") is not None]
    if dds:
        return max(abs(x) for x in dds)
    pic, ddmax = 0.0, 0.0
    for s in snaps:
        nav = float(s.get("nav_usd") or 0.0)
        pic = max(pic, nav)
        if pic > 0:
            ddmax = max(ddmax, (pic - nav) / pic * 100.0)
    return ddmax


def concentration_hhi(snap: dict) -> float:
    """Herfindahl de l'expo par coin ∈ [0,1] (1 = tout sur un coin). Snapshot le plus récent."""
    expo = _positions_expo(snap)
    tot = sum(expo.values())
    if tot <= 0:
        return 1.0
    return sum((v / tot) ** 2 for v in expo.values())


def turnover_moyen(snaps: list[dict]) -> float:
    """Turnover = |Δexpo nette| / nav, moyenné par période. 0 = figé, grand = frénétique."""
    vals: list[float] = []
    for a, b in zip(snaps, snaps[1:]):
        nav = float(b.get("nav_usd") or 0.0)
        d = b.get("delta_expo_nette_usd")
        if nav > 0 and d is not None:
            vals.append(abs(float(d)) / nav)
        elif nav > 0:
            ea = float(a.get("expo_nette_usd") or 0.0)
            eb = float(b.get("expo_nette_usd") or 0.0)
            vals.append(abs(eb - ea) / nav)
    return sum(vals) / len(vals) if vals else 0.0


def copyabilite(snap: dict, coins_executables: Iterable[str]) -> float:
    """Part de l'expo (en valeur) sur des coins exécutables (présents dans `coins_executables`).
    Sans coins exécutables connus → 0.0 (on ne prétend pas pouvoir copier ce qu'on ne peut pricer)."""
    exe = {str(c).upper() for c in coins_executables}
    if not exe:
        return 0.0
    expo = _positions_expo(snap)
    tot = sum(expo.values())
    if tot <= 0:
        return 0.0
    return sum(v for c, v in expo.items() if c in exe) / tot


# ─────────────────────────────── normalisation + composite ───────────────────────────────

def _norm_turnover(t: float) -> float:
    """Cloche gaussienne centrée sur l'optimum : ni figé ni frénétique."""
    return math.exp(-((t - TURNOVER_OPTIMUM) ** 2) / (2 * TURNOVER_LARGEUR ** 2))


POIDS = {"pnl_net": 0.24, "regularite": 0.18, "drawdown": 0.16, "anciennete": 0.08,
         "concentration": 0.08, "turnover": 0.08, "capacite": 0.08, "copyabilite": 0.10}


def scorer_vault(snaps: list[dict], *, age_j: float = 0.0, tvl_usd: float = 0.0,
                 coins_executables: Iterable[str] = (), date_max_ms: int | None = None) -> dict[str, Any]:
    """Score un vault depuis sa série de snapshots + méta (âge, TVL) + l'univers exécutable.
    Rend les 8 facteurs bruts, leurs versions normalisées [0,1], et le composite pondéré.
    POINT-IN-TIME (rectif Flo 23/07) : si `date_max_ms`, on n'utilise QUE les snapshots ≤ cette date —
    le score à une date historique ne connaît jamais le futur (anti-fuite de sélection)."""
    snaps = sorted(snaps, key=lambda s: int(s.get("ts_ms") or 0))
    if date_max_ms is not None:
        snaps = [s for s in snaps if int(s.get("ts_ms") or 0) <= date_max_ms]
    dernier = snaps[-1] if snaps else {}
    rn = rendement_net(snaps)
    reg = regularite(snaps)
    dd = drawdown_max_pct(snaps)
    hhi = concentration_hhi(dernier)
    tno = turnover_moyen(snaps)
    cap_log = math.log10(tvl_usd) if tvl_usd > 0 else 0.0
    copy = copyabilite(dernier, coins_executables)
    brut = {"pnl_net": rn, "regularite": reg, "drawdown_pct": dd, "anciennete_j": age_j,
            "concentration_hhi": hhi, "turnover": tno, "tvl_usd": tvl_usd, "copyabilite": copy}
    norm = {
        "pnl_net": _clamp(0.5 + rn * 5.0),                       # +10 %/fenêtre -> ~1.0 ; −10 % -> 0
        "regularite": _clamp(reg),
        "drawdown": _clamp(1.0 - dd / DD_MAX_TOLERE_PCT),
        "anciennete": _clamp(age_j / AGE_PLEIN_J),
        "concentration": _clamp(1.0 - hhi),
        "turnover": _clamp(_norm_turnover(tno)),
        "capacite": _clamp((cap_log - TVL_REF_LOG[0]) / (TVL_REF_LOG[1] - TVL_REF_LOG[0])),
        "copyabilite": _clamp(copy),
    }
    composite = round(sum(POIDS[k] * norm[k] for k in POIDS), 4)
    return {"facteurs": brut, "normalises": {k: round(v, 4) for k, v in norm.items()},
            "composite": composite, "n_snapshots": len(snaps)}


def retenu(score: dict[str, Any]) -> tuple[bool, str]:
    """Filtre dur : un vault n'est copiable que s'il est assez ancien, pas trop en drawdown, assez
    copyable et au composite suffisant. Rend (retenu, raison_du_rejet)."""
    f = score.get("facteurs", {})
    if f.get("anciennete_j", 0.0) < SEUIL_AGE_J:
        return False, "TROP_JEUNE"
    if f.get("drawdown_pct", 100.0) > SEUIL_DD_PCT:
        return False, "DRAWDOWN_EXCESSIF"
    if f.get("copyabilite", 0.0) < SEUIL_COPYABILITE:
        return False, "PEU_COPYABLE"
    if score.get("composite", 0.0) < SEUIL_COMPOSITE:
        return False, "COMPOSITE_INSUFFISANT"
    return True, ""


def classer(vaults: dict[str, list[dict]], *, meta: dict[str, dict] | None = None,
            coins_executables: Iterable[str] = (), date_max_ms: int | None = None) -> list[dict[str, Any]]:
    """Score et CLASSE tous les vaults (composite décroissant). `meta[adr]` peut porter age_j/tvl_usd.
    `date_max_ms` (point-in-time) propage le cutoff : à une date historique, aucun vault n'est jugé sur
    des données futures. Chaque entrée : {vault, composite, retenu, raison, facteurs, normalises}."""
    meta = meta or {}
    exe = list(coins_executables)
    out: list[dict[str, Any]] = []
    for adr, snaps in vaults.items():
        m = meta.get(adr, {})
        sc = scorer_vault(snaps, age_j=float(m.get("age_j") or 0.0),
                          tvl_usd=float(m.get("tvl_usd") or 0.0), coins_executables=exe, date_max_ms=date_max_ms)
        ok, raison = retenu(sc)
        out.append({"vault": adr, "composite": sc["composite"], "retenu": ok, "raison": raison,
                    "facteurs": sc["facteurs"], "normalises": sc["normalises"], "n_snapshots": sc["n_snapshots"]})
    out.sort(key=lambda x: -x["composite"])
    return out


__all__ = ["scorer_vault", "retenu", "classer", "rendement_net", "regularite", "drawdown_max_pct",
           "concentration_hhi", "turnover_moyen", "copyabilite", "POIDS"]
