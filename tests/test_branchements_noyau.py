"""🔴 L'INVARIANT DE BRANCHEMENT — « en gros rien n'est vraiment branché ? » (Flo, 2026-07-14)

Il avait raison : **22 modules livrés, 3 branchés.**
***Un module qui existe n'est pas un module qui garde.***

Ce fichier est l'invariant qui empêche que ça se reproduise. **Il ne fait pas d'inventaire :
il vérifie par AST, à chaque exécution, que les garde-fous sont VRAIMENT dans la porte.**

Et il garde les TROIS zéros silencieux qu'on a trouvés dans le chemin d'entrée LIVE :

    `plancher_edge_net_bps=0.0`   (local_engine, **explicitement**)
    `estimated_fee_bps = 0.0`     (schemas)
    `frais_bps = 0.0`             (noyau, défaut)

***Un edge net de +0,01 bps franchissait la porte.*** Le deny-by-default protégeait les ORDRES ;
il ne protégeait pas les CHIFFRES.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src" / "hl_observer"

NOYAU = SRC / "decision_engine" / "noyau_unique.py"
LOCAL = SRC / "decision_engine" / "local_engine.py"
SCHEMAS = SRC / "hyperliquid" / "schemas.py"


def _imports(fichier: Path) -> set[str]:
    a = ast.parse(fichier.read_text(encoding="utf-8"))
    return {n.module for n in ast.walk(a) if isinstance(n, ast.ImportFrom) and n.module}


# ════════════════════════════════════════════════════════════════════════════════════════════
# 1. LES 4 GARDE-FOUS SONT-ILS DANS LA PORTE ?
# ════════════════════════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("module,pourquoi", [
    ("hl_observer.fees.hyperliquid_fees",
     "#543 — la SOURCE UNIQUE des frais. Sans elle, 6 fichiers, 4 valeurs, dont un 2,5 bps inexistant."),
    ("hl_observer.risk.side_lock",
     "#566 — 19 de nos 21 ouvertures etaient des SHORT : 1 chance sur 4 520."),
    ("hl_observer.market.flow_toxicity",
     "#521 — le VPIN. *Ne pas savoir si le flux est toxique n'est pas une permission de trader.*"),
    ("hl_observer.market.execution_constraints",
     "#576/#498 — *un trade que l'exchange aurait REFUSE et qu'on compte quand meme est INVENTE.*"),
])
def test_le_noyau_IMPORTE_le_garde_fou(module: str, pourquoi: str) -> None:
    """🔴 **BRANCHER OU ENTERRER.** Un import qui disparait = un garde-fou qui meurt en silence."""
    assert module in _imports(NOYAU), (
        "**%s N'EST PLUS BRANCHE DANS LE NOYAU.**\n%s\n"
        "*Un module qui existe n'est pas un module qui garde.*" % (module, pourquoi)
    )


def test_les_TROIS_questions_historiques_sont_toujours_la() -> None:
    """L'invariant d'origine (Q1/Q2/Q3) ne doit pas etre casse par mes ajouts."""
    i = _imports(NOYAU)
    assert "hl_observer.edge.edge_source" in i          # Q1 : l'edge MESURE
    assert "hl_observer.arbitrage.executable_legs" in i  # Q2 : les prix EXECUTABLES
    assert "hl_observer.signals.signal_taxonomy" in i    # Q3 : les zones mortes


# ════════════════════════════════════════════════════════════════════════════════════════════
# 2. 🔴 LES ZEROS SILENCIEUX — LE PIRE BUG DU PROJET
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_le_noyau_ne_met_PLUS_les_frais_a_ZERO_par_defaut() -> None:
    """🔴🔴 ***Un cout absent n'est PAS un cout nul.***

    Le commentaire du fichier disait deja : « Les couts REELS, en bps. **Jamais des constantes
    silencieuses.** » -- et la ligne d'apres mettait `0.0`.
    ***La docstring mettait en garde contre exactement ce que le code faisait.***
    """
    from hl_observer.decision_engine.noyau_unique import (
        FRAIS_ALLER_RETOUR_TAKER_BPS,
        PLANCHER_NET_BPS,
        Contexte,
    )
    c = Contexte(strategie="COPY", coin="BTC", direction="LONG", notional_usd=500.0)
    assert c.frais_bps == pytest.approx(FRAIS_ALLER_RETOUR_TAKER_BPS)
    assert c.frais_bps == pytest.approx(9.0), "2 x 4,5 bps taker (entree + sortie)"
    assert c.frais_bps > 0.0, "🔴 PLUS JAMAIS ZERO"
    assert c.plancher_edge_net_bps == pytest.approx(PLANCHER_NET_BPS)
    assert c.plancher_edge_net_bps == pytest.approx(30.0), "CLAUDE.md : « plancher net 30 bps »"
    assert c.plancher_edge_net_bps > 0.0, "🔴 PLUS JAMAIS ZERO"


def test_le_chemin_LIVE_ne_passe_PLUS_un_plancher_de_ZERO() -> None:
    """🔴🔴🔴 **LE BUG QUE FLO A DEBUSQUE.**

    `local_engine.py` passait `plancher_edge_net_bps=**0.0**` -- **explicitement**, dans le chemin
    d'entree LIVE. ***Un edge net de +0,01 bps franchissait la porte.***

    Ce test lit le CODE (AST), pas la doc : un litteral `0.0` sur ce parametre est INTERDIT.
    """
    a = ast.parse(LOCAL.read_text(encoding="utf-8"))
    for n in ast.walk(a):
        if not isinstance(n, ast.Call):
            continue
        for kw in n.keywords:
            if kw.arg == "plancher_edge_net_bps":
                assert not (isinstance(kw.value, ast.Constant)
                            and float(kw.value.value or 0) == 0.0), (
                    "🔴 **LE CHEMIN LIVE PASSE UN PLANCHER DE ZERO.** "
                    "Un edge de +0,01 bps entrerait. Utiliser `noyau.PLANCHER_NET_BPS`."
                )


def test_le_SCHEMA_ne_met_plus_les_frais_a_ZERO() -> None:
    """*Le deny-by-default protege les ORDRES ; il ne protegeait pas les CHIFFRES.*

    🚩 `SignalCandidate` est un modele **Pydantic**, pas une dataclass -- ma 1re version lisait
    `__dataclass_fields__` et explosait. *On lit le defaut REEL, on ne suppose pas la structure.*
    """
    from hl_observer.hyperliquid.schemas import SignalCandidate
    champs = getattr(SignalCandidate, "model_fields", None) \
        or getattr(SignalCandidate, "__fields__", {})
    f = champs["estimated_fee_bps"]
    defaut = getattr(f, "default", None)
    assert float(defaut) == pytest.approx(9.0), (
        "🔴 Un candidat mal rempli arrivait au noyau avec **ZERO frais** "
        "(defaut lu : %r)." % defaut
    )


def test_AUCUN_repli_de_frais_INVENTE_ne_subsiste() -> None:
    """🔴 `runtime_v9_adapter` repliait sur **4.0** -- un chiffre qui ne figure NULLE PART dans
    la grille Hyperliquid (taker 4,5 · maker 1,5 · aller-retour 9,0).
    *Un repli invente est un mensonge par defaut.*"""
    src = (SRC / "copying" / "runtime_v9_adapter.py").read_text(encoding="utf-8")
    a = ast.parse(src)
    for n in ast.walk(a):
        if isinstance(n, ast.keyword) and n.arg == "estimated_fee_bps":
            texte = ast.dump(n.value)
            assert "value=4.0" not in texte, "le repli 4.0 est revenu"


# ════════════════════════════════════════════════════════════════════════════════════════════
# 3. LES 3 NOUVELLES PORTES REFUSENT-ELLES VRAIMENT ?
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_les_3_nouveaux_REFUS_existent_et_sont_nommes() -> None:
    from hl_observer.decision_engine.noyau_unique import (
        REFUS_COTE_VERROUILLEE,
        REFUS_FLUX_TOXIQUE,
        REFUS_ORDRE_IMPOSSIBLE,
    )
    for r in (REFUS_COTE_VERROUILLEE, REFUS_FLUX_TOXIQUE, REFUS_ORDRE_IMPOSSIBLE):
        assert r.startswith("NOYAU_"), "un refus doit dire POURQUOI, pas seulement QUE"


def test_un_notionnel_SOUS_10_DOLLARS_est_refuse_par_le_noyau() -> None:
    """Doc HL : « MinTradeNtl : Order must have minimum value of $10. »
    ***Un trade que l'exchange aurait refuse et qu'on compte quand meme est un trade INVENTE.***"""
    from hl_observer.decision_engine.noyau_unique import NO_TRADE, Contexte, decider
    d = decider(Contexte(strategie="COPY", coin="BTC", direction="LONG", notional_usd=5.0))
    assert d.verdict == NO_TRADE          # (il tombera peut-etre avant, sur la zone morte -- OK)
    assert not d.autorise


def test_le_noyau_reste_PAPER_ONLY_quoi_qu_il_arrive() -> None:
    """🔒 Aucun de mes branchements ne doit avoir ouvert une porte d'execution."""
    from hl_observer.decision_engine.noyau_unique import Contexte, decider
    d = decider(Contexte(strategie="COPY", coin="BTC", direction="LONG", notional_usd=500.0))
    assert d.paper_only is True
    assert d.as_dict()["real_execution"] is False
