"""#292b — LES 11 GATES DE `risk_engine_v3`, ENFIN SUR LE CHEMIN D'ENTREE.

🔴 LE CONSTAT :

    > ***Les 11 gates qui auraient pu EMPECHER la perte ne servaient qu'a l'EXPLIQUER apres coup.***

Leur seul appelant etait `analysis/negative_pnl_auditor.py` -- **l'AUTOPSIE**.
*Une capacite presente, un chainon manquant, et le seul temoin est le medecin legiste.*
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from hl_observer.decision_engine.noyau_unique import (
    ETAT_SESSION_NON_FOURNI,
    NO_TRADE,
    REFUS_SESSION_EN_HALTE,
    Contexte,
    decider,
)
from hl_observer.risk.session_gate import (
    MOTIF_ETAT_NON_FOURNI,
    MOTIF_OK,
    MOTIF_SESSION_EN_HALTE,
    EtatSession,
    etat_session_courant,
    evaluer_session,
    publier_etat_session,
    reinitialiser,
)

SRC = Path(__file__).resolve().parents[1] / "src" / "hl_observer"


@pytest.fixture(autouse=True)
def _propre():
    reinitialiser()
    yield
    reinitialiser()


# ════════════════════════════════════════════════════════════════════════════════════════════
# 1. LE DISJONCTEUR
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_une_session_qui_PERD_LOURD_est_mise_en_HALTE() -> None:
    """***Un disjoncteur qui se laisse convaincre par un bon argument n'est pas un disjoncteur.***"""
    v = evaluer_session(EtatSession(
        net_pnl_usdc=-9999.0,        # perte massive
        total_decisions=100, accepted=50,
        negative_events=40, positive_events=10,
        profit_factor_net=0.2, consecutive_losses=15,
    ))
    assert v.bloque
    assert v.motif == MOTIF_SESSION_EN_HALTE
    assert v.gates_declenches, "au moins un gate BLOQUANT doit se declencher"
    assert "ne rouvre la porte" in v.detail


def test_le_disjoncteur_lit_le_BON_champ_et_ne_le_DEVINE_pas() -> None:
    """🔴🔴 **LE BUG QUE J'AI COMMIS DANS MON PROPRE GARDE-FOU.**

    J'avais ecrit `getattr(g, "blocks", False)`. **Le champ s'appelle `blocks_new_entries`.**
    -> `getattr` rendait TOUJOURS `False` -> ***aucun gate ne bloquait jamais.***
    Le disjoncteur etait branche... **et MORT**.

    ***J'ai reproduit EXACTEMENT la maladie que je repare.***
    (Comme le voyant soude, le garde-fou affame, les 7 anti-overfit sans appelant.)

    Ce test verrouille le nom du champ. *Un garde-fou qui devine le nom d'un champ est un
    garde-fou qui finira par mentir.*
    """
    import dataclasses

    from hl_observer.risk.risk_engine_v3 import V19RiskGate, evaluate_v19_risk_gates

    champs = {f.name for f in dataclasses.fields(V19RiskGate)}
    assert "blocks_new_entries" in champs, "le champ qui BLOQUE a change de nom"
    assert "blocks" not in champs, "🔴 c'est CE nom que j'avais devine, et il n'existe pas"

    # et la decision expose la verite faisant AUTORITE : on la LIT, on ne la reconstruit pas
    d = evaluate_v19_risk_gates(
        net_pnl_usdc=-9999.0, total_decisions=100, accepted=50,
        negative_events=40, positive_events=10, fee_drag_ratio=0.9,
        stale_reason_count=50, edge_negative_count=50, edge_sentinel_count=10,
        orphan_close_count=20, profit_factor_net=0.2, consecutive_losses=15,
    )
    assert hasattr(d, "allow_new_entries")
    assert d.allow_new_entries is False, "une session qui perd lourd doit INTERDIRE les entrees"
    assert any(g.triggered and g.blocks_new_entries for g in d.gates)


def test_une_session_SAINE_laisse_passer() -> None:
    v = evaluer_session(EtatSession(
        net_pnl_usdc=5.0, total_decisions=100, accepted=10,
        negative_events=3, positive_events=7,
        profit_factor_net=2.0, consecutive_losses=0,
    ))
    assert not v.bloque and v.motif == MOTIF_OK


def test_une_session_VIERGE_ne_peut_pas_etre_jugee() -> None:
    v = evaluer_session(EtatSession())
    assert not v.bloque and "vierge" in v.detail


# ════════════════════════════════════════════════════════════════════════════════════════════
# 2. 🔴 UN ETAT ABSENT N'EST PAS UN ETAT SAIN
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_un_etat_NON_FOURNI_est_SIGNALE_pas_suppose_sain() -> None:
    """*On ne pretend PAS que la session va bien. On le DIT.*"""
    v = evaluer_session(None)
    assert v.motif == MOTIF_ETAT_NON_FOURNI
    assert "n'est pas un etat sain" in v.detail
    assert not v.bloque, "on ne bloque pas tout, mais on laisse une trace INDELEBILE"


def test_le_noyau_SIGNALE_quand_l_etat_manque() -> None:
    d = decider(Contexte(strategie="COPY", coin="BTC", direction="LONG", notional_usd=500.0))
    assert ETAT_SESSION_NON_FOURNI in d.signalements, (
        "le noyau doit LAISSER UNE TRACE quand l'etat de session n'est pas fourni"
    )


# ════════════════════════════════════════════════════════════════════════════════════════════
# 3. 🔴 LE DISJONCTEUR PASSE **AVANT** TOUT LE RESTE
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_une_session_en_HALTE_bloque_AVANT_meme_de_regarder_l_edge() -> None:
    """🔴 **LE TEST QUI COMPTE.** Il passe en gate 0 : avant la famille, avant l'edge, avant les prix.

    *Si la session est en halte, AUCUN edge, si beau soit-il, ne rouvre la porte.*
    """
    publier_etat_session(EtatSession(
        net_pnl_usdc=-9999.0, total_decisions=100, accepted=50,
        negative_events=40, positive_events=10,
        profit_factor_net=0.2, consecutive_losses=15,
    ))
    d = decider(Contexte(strategie="COPY", coin="BTC", direction="LONG", notional_usd=500.0,
                         etat_session=etat_session_courant()))
    assert d.verdict == NO_TRADE
    assert d.raison == REFUS_SESSION_EN_HALTE, (
        "le disjoncteur doit tomber AVANT la zone morte, l'edge et les prix"
    )
    assert not d.autorise


def test_le_ledger_est_la_SEULE_source_de_l_etat() -> None:
    """*Un disjoncteur qui recalcule le PnL est un DEUXIEME PnL* -- et on a deja vu ce que deux
    tables d'edge produisent."""
    assert etat_session_courant() is None
    e = EtatSession(net_pnl_usdc=42.0, total_decisions=1)
    publier_etat_session(e)
    assert etat_session_courant() is e
    reinitialiser()
    assert etat_session_courant() is None, "on ne melange JAMAIS deux sessions (#286)"


# ════════════════════════════════════════════════════════════════════════════════════════════
# 4. 🔒 L'INVARIANT : le chemin d'entree LIVE DOIT fournir l'etat
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_le_noyau_IMPORTE_le_disjoncteur() -> None:
    a = ast.parse((SRC / "decision_engine" / "noyau_unique.py").read_text(encoding="utf-8"))
    mods = {n.module for n in ast.walk(a) if isinstance(n, ast.ImportFrom) and n.module}
    assert "hl_observer.risk.session_gate" in mods, (
        "🔴 **LES 11 GATES SONT DEBRANCHES DU NOYAU.** Ils redeviendraient une AUTOPSIE."
    )


def test_le_chemin_LIVE_FOURNIT_l_etat_de_session() -> None:
    """🔴 **BRANCHER OU ENTERRER.** Si `local_engine` ne fournit plus l'etat, les 11 gates
    redeviennent ce qu'ils etaient : *un medecin legiste.*"""
    src = (SRC / "decision_engine" / "local_engine.py").read_text(encoding="utf-8")
    a = ast.parse(src)
    mods = {n.module for n in ast.walk(a) if isinstance(n, ast.ImportFrom) and n.module}
    assert "hl_observer.risk.session_gate" in mods

    trouve = any(
        isinstance(n, ast.keyword) and n.arg == "etat_session"
        for n in ast.walk(a)
    )
    assert trouve, (
        "🔴 **`local_engine` ne passe plus `etat_session` au noyau.** "
        "Les 11 gates redeviennent une autopsie."
    )


def test_les_gates_ne_sont_PLUS_seulement_dans_l_AUTOPSIE() -> None:
    """Le constat d'origine : `evaluate_v19_risk_gates` n'avait qu'UN appelant --
    `analysis/negative_pnl_auditor.py`. **Il en a maintenant un dans le chemin d'ENTREE.**"""
    appelants = []
    for f in SRC.rglob("*.py"):
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if "evaluate_v19_risk_gates" in src and f.name != "risk_engine_v3.py":
            appelants.append(f.name)
    assert "session_gate.py" in appelants, (
        "les 11 gates doivent etre appeles par le DISJONCTEUR, pas seulement par l'autopsie"
    )
    assert len(appelants) >= 2, "l'autopsie ET le disjoncteur"
