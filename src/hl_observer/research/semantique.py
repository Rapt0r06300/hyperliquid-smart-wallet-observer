r"""#1 — LA COUCHE SÉMANTIQUE — *contre le faux négatif que j'ai avoué ne pas pouvoir garantir.*

═══════════════════════════════════════════════════════════════════════════════════════════════
LE PROBLÈME
═══════════════════════════════════════════════════════════════════════════════════════════════

Tout le moissonneur est **regex + mots-clés**. Un papier qui décrit **le même concept avec
d'autres mots** passe à travers.

    « avoiding trades right before the counterparty acts »  == sélection adverse
    « the chance our resting order gets executed »          == probabilité de fill
    « penalising deviation from a target book »             == terme d'inventaire

***Aucun de ces trois ne contient nos mots-clés. Le grep les rate. C'est LE faux négatif.***

═══════════════════════════════════════════════════════════════════════════════════════════════
CE QU'ON FAIT — et ce qu'on **n'affirme PAS**
═══════════════════════════════════════════════════════════════════════════════════════════════

Deux niveaux, du meilleur au plus modeste :

  1. **Si un vrai modèle d'embeddings est installé** (`sentence-transformers`), on l'utilise :
     comparaison de SENS. *Gratuit, local, sans clé.*

  2. **Sinon** — et c'est le cas par défaut — on tombe sur une **similarité LEXICALE** : cosinus
     sur des n-grammes de caractères + recouvrement de tokens, contre des **descriptions-ancres**
     de nos concepts (rédigées, elles, dans un vocabulaire riche).

    🚩 ***Ce n'est PAS un embedding neuronal.*** C'est une approximation lexicale-sémantique.
    Elle attrape les paraphrases proches (mêmes racines, synonymes partiels), **pas** les
    reformulations totales. *Je le dis clairement pour ne pas te vendre plus que ce que c'est.*

Le rôle de cette couche : **repêcher ce que le grep a raté**, pas remplacer le grep. Un texte
que le grep ignore mais qui ressemble sémantiquement à un de nos trous mérite un second regard.

PUR : aucun réseau. Aucun ordre réel.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any, Mapping
from hl_observer.ops.echec_silencieux import noter as _noter_echec

# ═══════════════════════════════════════════════════════════════════════════════════════════════
# LES ANCRES — *nos concepts, décrits richement, pour que la similarité ait de quoi mordre.*
# ═══════════════════════════════════════════════════════════════════════════════════════════════
ANCRES: dict[str, str] = {
    "fill_probability": (
        "probability that a resting limit order gets executed filled at a distance from mid "
        "queue position depth intensity of arrivals whether our passive order trades"
    ),
    "adverse_selection": (
        "getting filled precisely when wrong informed counterparty picks off stale quotes "
        "toxic order flow the market moves against us right after our passive fill markout"
    ),
    "market_impact": (
        "our own order pushes the price against us slippage cost of trading size square root "
        "law temporary permanent price concession execution shortfall"
    ),
    "inventory_control": (
        "penalising deviation from a target inventory skewing quotes around a reservation price "
        "holding risk optimal spread balancing exposure Avellaneda Stoikov Gueant"
    ),
    "funding_carry": (
        "delta neutral holding long spot short perpetual collecting the funding payment basis "
        "between perpetual and spot cash and carry contango"
    ),
    "liquidation_flow": (
        "forced selling when a leveraged position is closed by the exchange cascade of "
        "liquidations margin call predictable non discretionary directional flow"
    ),
    "overfit_validation": (
        "the backtest looks great but does not survive out of sample data leakage from the "
        "future purged embargo walk forward multiple testing deflated sharpe curve fitting"
    ),
    "backtest_live_parity": (
        "replaying a recorded period should reproduce what actually happened live if the two "
        "diverge one of them is lying reconciliation deterministic"
    ),
    "leg_risk": (
        "one leg of a spread trade executes and the other does not leaving unhedged directional "
        "exposure atomic simultaneous execution of both legs failed leg"
    ),
    "sizing_ruin": (
        "how much to bet Kelly criterion fraction of capital risk of ruin volatility targeting "
        "position sizing that survives a losing streak"
    ),
    "queue_double_count": (
        "counting a trade and the book decrease twice makes fills happen too early do not double "
        "count subtract cumulative traded quantity"
    ),
    "signal_freshness": (
        "the data feed went silent and we kept acting on stale information age of the signal "
        "watermark event time versus processing time staleness detection"
    ),
}

_STOP = frozenset("""
the a an of and or to in on for with from that this is are be as at by we our it its their they
""".split())

_MOT = re.compile(r"[a-z][a-z]+")


def _tokens(t: str) -> list[str]:
    return [m for m in _MOT.findall((t or "").lower()) if m not in _STOP and len(m) > 2]


def _trigrammes(t: str) -> dict[str, int]:
    """Vecteur de fréquence de 3-grammes de caractères. *Attrape les racines communes.*"""
    s = re.sub(r"\s+", " ", (t or "").lower())
    v: dict[str, int] = {}
    for i in range(max(0, len(s) - 2)):
        g = s[i:i + 3]
        if g.strip():
            v[g] = v.get(g, 0) + 1
    return v


def _cosinus(a: Mapping[str, int], b: Mapping[str, int]) -> float:
    if not a or not b:
        return 0.0
    inter = set(a) & set(b)
    num = sum(a[k] * b[k] for k in inter)
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return num / (na * nb) if na and nb else 0.0


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


# ── le modèle neuronal, SI présent (jamais installé de force) ──────────────────────────────────
_MODELE: Any = None
_MODELE_TENTE = False


def _modele() -> Any:
    """Charge `sentence-transformers` **s'il est là**. Sinon `None` — *on ne l'installe pas.*"""
    global _MODELE, _MODELE_TENTE
    if _MODELE_TENTE:
        return _MODELE
    _MODELE_TENTE = True
    try:
        from sentence_transformers import SentenceTransformer  # noqa: PLC0415

        _MODELE = SentenceTransformer("all-MiniLM-L6-v2")
    except Exception:  # noqa: BLE001
        _MODELE = None            # pas installé -> on utilisera la voie lexicale, **et on le DIT**
    return _MODELE


_ANCRES_TRI = {k: _trigrammes(v) for k, v in ANCRES.items()}
_ANCRES_TOK = {k: set(_tokens(v)) for k, v in ANCRES.items()}


@dataclass(frozen=True, slots=True)
class Semantique:
    concept: str
    score: float          # 0..1
    methode: str          # "neuronal" | "lexical"

    def as_dict(self) -> dict[str, Any]:
        return {"concept_le_plus_proche": self.concept, "similarite": round(self.score, 3),
                "methode": self.methode}


def plus_proche(texte: str) -> Semantique:
    """Le concept de NOTRE bot dont ce texte est **sémantiquement le plus proche**.

    ***Sert à REPÊCHER ce que le grep a raté*** — pas à remplacer le grep.
    """
    t = texte or ""
    m = _modele()
    if m is not None:
        try:
            import numpy as _np  # noqa: PLC0415

            vt = m.encode(t[:2000], normalize_embeddings=True)
            best, bs = "", -1.0
            for k, desc in ANCRES.items():
                va = m.encode(desc, normalize_embeddings=True)
                s = float(_np.dot(vt, va))
                if s > bs:
                    best, bs = k, s
            return Semantique(best, max(0.0, bs), "neuronal")
        except Exception:  # noqa: BLE001
            _noter_echec("hl_observer/research/semantique.py:192")

    tri = _trigrammes(t)
    tok = set(_tokens(t))
    best, bs = "", 0.0
    for k in ANCRES:
        s = 0.6 * _cosinus(tri, _ANCRES_TRI[k]) + 0.4 * _jaccard(tok, _ANCRES_TOK[k])
        if s > bs:
            best, bs = k, s
    return Semantique(best, bs, "lexical")


# au-dessus de ce seuil (voie lexicale), le texte "ressemble" assez pour un second regard
SEUIL_REPECHAGE = 0.14


def merite_un_second_regard(texte: str, *, deja_vu_par_grep: bool) -> tuple[bool, Semantique]:
    """🔑 Le grep a-t-il raté quelque chose qui **ressemble** à un de nos trous ?

    *Si le grep l'a déjà pris, inutile. Sinon, et si ça ressemble assez : on le repêche.*
    """
    s = plus_proche(texte)
    if deja_vu_par_grep:
        return False, s
    seuil = 0.30 if s.methode == "neuronal" else SEUIL_REPECHAGE
    return (s.score >= seuil), s


def diagnostic() -> dict[str, Any]:
    """*On ne fait pas semblant d'avoir un modèle neuronal si on ne l'a pas.*"""
    presente = _modele() is not None
    return {
        "methode_active": "neuronal (sentence-transformers)" if presente else "lexical",
        "franchise": (
            "✅ Modèle d'embeddings neuronal détecté et utilisé."
            if presente else
            "🚩 **Pas de modèle neuronal installé** → voie **lexicale** (n-grammes + tokens). "
            "*Elle attrape les paraphrases proches, PAS les reformulations totales.* Pour "
            "activer le sémantique complet, gratuit et local : `pip install sentence-transformers`."
        ),
        "n_ancres": len(ANCRES),
        "role": ("Repêcher ce que le grep a raté — un texte qui ressemble à un de nos trous "
                 "sans en contenir les mots-clés. **Ne remplace pas le grep.**"),
    }


__all__ = ["ANCRES", "SEUIL_REPECHAGE", "Semantique",
           "diagnostic", "merite_un_second_regard", "plus_proche"]
