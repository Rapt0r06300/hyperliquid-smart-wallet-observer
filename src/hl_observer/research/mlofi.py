"""ALPHA — MLOFI : Order Flow Imbalance MULTI-NIVEAUX (Xu & Cont), pas juste L1.

Généralise l'OFI de Cont-Kukanov-Stoikov à plusieurs niveaux du carnet : pour chaque niveau m, on compare
prix+taille entre deux snapshots. Le vecteur `[OFI_1..OFI_M]` (MLOFI) contient plus d'information que le seul
L1 quand le flux se déplace en profondeur. On ajoute l'**OFI intégré** (somme pondérée), la **pente de
profondeur** (depth slope) et la **convexité** — features « state-first » de la littérature récente.

Schéma d'entrée d'un carnet : `{"bids": [[px, sz], ...], "asks": [[px, sz], ...]}` (niveaux triés du meilleur
au pire). Fonctionne sur le `top5` du metaorder tape (réel, 5 niveaux) et sur tout tape L2 multi-niveaux futur.

Discipline identique : causal, DISCOVERY→FREEZE→OOS, coûts déduits, `UNMEASURABLE` jamais 0. Pur, 0 réseau.
"""
from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from typing import Any

UNMEASURABLE = "UNMEASURABLE"


def _ofi_cote(p0: float, q0: float, p1: float, q1: float, *, cote: str) -> float:
    """Contribution OFI d'un côté à un niveau (CKS généralisé)."""
    if cote == "bid":
        return (q1 if p1 >= p0 else 0.0) - (q0 if p1 <= p0 else 0.0)
    return (q1 if p1 <= p0 else 0.0) - (q0 if p1 >= p0 else 0.0)


def _niv(book: Mapping[str, Any], cote: str, m: int) -> tuple[float, float] | None:
    lst = book.get(cote if cote in book else ("bids" if cote == "bid" else "asks"))
    if not lst or m >= len(lst):
        return None
    px, sz = lst[m][0], lst[m][1]
    if not (isinstance(px, (int, float)) and isinstance(sz, (int, float))):
        return None
    return float(px), float(sz)


def ofi_niveau(prev_book: Mapping[str, Any], cur_book: Mapping[str, Any], m: int) -> float | None:
    """OFI au niveau m (0-indexé) = contribution bid − contribution ask. `None` si le niveau manque."""
    b0 = _niv(prev_book, "bid", m); b1 = _niv(cur_book, "bid", m)
    a0 = _niv(prev_book, "ask", m); a1 = _niv(cur_book, "ask", m)
    if None in (b0, b1, a0, a1):
        return None
    eb = _ofi_cote(b0[0], b0[1], b1[0], b1[1], cote="bid")
    ea = _ofi_cote(a0[0], a0[1], a1[0], a1[1], cote="ask")
    return eb - ea


def mlofi(prev_book: Mapping[str, Any], cur_book: Mapping[str, Any], *, niveaux: int = 5) -> list[float | None]:
    """Vecteur MLOFI [OFI_1..OFI_niveaux]."""
    return [ofi_niveau(prev_book, cur_book, m) for m in range(niveaux)]


def mlofi_integre(vecteur: Sequence[float | None], *, poids: Sequence[float] | None = None) -> float | None:
    """OFI intégré = somme pondérée des niveaux mesurables. Poids par défaut décroissants (1, 1/2, 1/3…)."""
    vals = [(i, v) for i, v in enumerate(vecteur) if isinstance(v, (int, float)) and not math.isnan(v)]
    if not vals:
        return None
    if poids is None:
        return sum(v / (i + 1) for i, v in vals)
    return sum(v * poids[i] for i, v in vals if i < len(poids))


def depth_slope(book: Mapping[str, Any], *, niveaux: int = 5) -> float | None:
    """Pente de la profondeur cumulée (bid+ask) par niveau : régression linéaire simple. Liquidité en profondeur."""
    cum = []
    tot = 0.0
    for m in range(niveaux):
        b = _niv(book, "bid", m); a = _niv(book, "ask", m)
        if b is None or a is None:
            break
        tot += b[1] + a[1]
        cum.append(tot)
    n = len(cum)
    if n < 3:
        return None
    xs = list(range(n))
    mx = sum(xs) / n; my = sum(cum) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    return sum((x - mx) * (y - my) for x, y in zip(xs, cum)) / sxx


def convexity(book: Mapping[str, Any], *, niveaux: int = 5) -> float | None:
    """Convexité de la profondeur cumulée = moyenne des différences secondes (accélération de la liquidité)."""
    cum = []
    tot = 0.0
    for m in range(niveaux):
        b = _niv(book, "bid", m); a = _niv(book, "ask", m)
        if b is None or a is None:
            break
        tot += b[1] + a[1]
        cum.append(tot)
    if len(cum) < 3:
        return None
    d2 = [cum[i + 1] - 2 * cum[i] + cum[i - 1] for i in range(1, len(cum) - 1)]
    return sum(d2) / len(d2) if d2 else None


def _mid(book: Mapping[str, Any]) -> float | None:
    b = _niv(book, "bid", 0); a = _niv(book, "ask", 0)
    if b is None or a is None or (b[0] + a[0]) <= 0:
        return None
    return (b[0] + a[0]) / 2.0


def experience_mlofi(books: Sequence[Mapping[str, Any]], *, niveaux: int = 5, horizon_pas: int = 1,
                     fee_bps: float = 9.0, fraction_decouverte: float = 0.5) -> dict[str, Any]:
    """MLOFI intégré prédit-il le mid forward, net de coût ? Compare aussi à L1 seul (incrément multi-niveaux).

    `books` = snapshots consécutifs d'un MÊME coin (triés). Retourne les nets OOS L1 vs multi-niveaux.
    """
    feats = []
    for i in range(1, len(books)):
        m0 = _mid(books[i - 1]); m1 = _mid(books[i])
        if m0 is None or m1 is None:
            continue
        vec = mlofi(books[i - 1], books[i], niveaux=niveaux)
        l1 = vec[0] if vec else None
        integ = mlofi_integre(vec)
        feats.append({"mid": _mid(books[i]), "ofi_l1": l1, "mlofi_integre": integ,
                      "spread_bps": _spread_bps(books[i])})
    if len(feats) < 60:
        return {"verdict": "MORE_DATA", "raison": "trop peu de paires de carnets", "n": len(feats),
                "real_execution": False}

    def net_oos(cle: str) -> dict[str, Any]:
        coupe = int(len(feats) * fraction_decouverte)
        dec = [abs(f[cle]) for f in feats[:coupe] if isinstance(f.get(cle), (int, float)) and not math.isnan(f[cle])]
        if len(dec) < 20:
            return {"n": 0, "net_bps": None}
        seuil = sorted(dec)[int(0.75 * len(dec))]
        nets = []
        t = 0
        oos = feats[coupe:]
        while t < len(oos) - horizon_pas:
            v = oos[t].get(cle)
            if isinstance(v, (int, float)) and not math.isnan(v) and abs(v) >= seuil:
                d = 1.0 if v > 0 else -1.0
                g = d * (oos[t + horizon_pas]["mid"] / oos[t]["mid"] - 1.0) * 1e4
                sp = oos[t]["spread_bps"] or 0.0
                nets.append(g - (fee_bps + sp))
                t += horizon_pas
            else:
                t += 1
        return {"n": len(nets), "net_bps": (round(sum(nets) / len(nets), 4) if nets else None)}

    r_l1 = net_oos("ofi_l1"); r_ml = net_oos("mlofi_integre")
    inc = (round(r_ml["net_bps"] - r_l1["net_bps"], 4)
           if isinstance(r_ml["net_bps"], (int, float)) and isinstance(r_l1["net_bps"], (int, float)) else UNMEASURABLE)
    verdict = "KILL"
    if r_ml["n"] < 20 or r_ml["net_bps"] is None:
        verdict = "MORE_DATA"
    elif r_ml["net_bps"] > 0:
        verdict = "OOS_POSITIF_A_FORWARD"
    return {"n_paires": len(feats), "niveaux": niveaux,
            "net_oos_L1": r_l1["net_bps"], "n_oos_L1": r_l1["n"],
            "net_oos_MLOFI": r_ml["net_bps"], "n_oos_MLOFI": r_ml["n"],
            "increment_multiniveaux_bps": inc, "verdict": verdict, "real_execution": False}


def _spread_bps(book: Mapping[str, Any]) -> float | None:
    b = _niv(book, "bid", 0); a = _niv(book, "ask", 0)
    m = _mid(book)
    return (a[0] - b[0]) / m * 1e4 if (b and a and m) else None


__all__ = ["ofi_niveau", "mlofi", "mlofi_integre", "depth_slope", "convexity", "experience_mlofi", "UNMEASURABLE"]
