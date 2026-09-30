"""#14 / #292b — INVARIANT du DISJONCTEUR DE SESSION (les 11 gates V19).

Le noyau doit consulter le disjoncteur EN GATE 0 (avant famille/edge/prix) et BLOQUER réellement
quand la session est en halte — pas seulement l'importer. Anti-régression : si le disjoncteur est
retiré, déplacé après l'edge, ou réduit à moins de 11 gates, un test ci-dessous CASSE.
« Les 11 gates qui auraient pu EMPÊCHER la perte ne servaient qu'à l'EXPLIQUER après coup. »"""
from __future__ import annotations

import ast
from pathlib import Path

from hl_observer.decision_engine.noyau_unique import Contexte, REFUS_SESSION_EN_HALTE, decider
from hl_observer.risk.session_gate import EtatSession

ROOT = Path(__file__).resolve().parents[1]
NOYAU = ROOT / "src" / "hl_observer" / "decision_engine" / "noyau_unique.py"
RISK = ROOT / "src" / "hl_observer" / "risk" / "risk_engine_v3.py"


def _session_en_halte() -> EtatSession:
    return EtatSession(net_pnl_usdc=-9999.0, total_decisions=100, accepted=50,
                       negative_events=40, positive_events=10, profit_factor_net=0.2,
                       consecutive_losses=15)


def _ctx(**kw) -> Contexte:
    base = dict(strategie="FUNDING", coin="BTC", direction="LONG", notional_usd=500.0,
                signal_ms=9_999_999.0, signal_age_ms=500.0, leader_score=70.0, consensus_wallets=2.0,
                niveaux_achat=[(100.0, 1_000.0)], niveaux_vente=[(99.9, 1_000.0)],
                frais_bps=12.0, plancher_edge_net_bps=0.0)
    base.update(kw)
    return Contexte(**base)  # type: ignore[arg-type]


def test_porte_session_en_halte_bloque_via_le_noyau():
    """PORTE (fonctionnel) : une session en halte → REFUS via `decider()`, pas juste en isolation."""
    d = decider(_ctx(etat_session=_session_en_halte()))
    assert d.raison == REFUS_SESSION_EN_HALTE


def test_ordre_le_disjoncteur_passe_AVANT_la_famille():
    """GATE 0 : stratégie inconnue ET session en halte → c'est la HALTE qui l'emporte (session d'abord).
    Un disjoncteur qui se laisse doubler par un autre refus n'est pas en gate 0."""
    d = decider(_ctx(strategie="STRAT_INCONNUE_XYZ", etat_session=_session_en_halte()))
    assert d.raison == REFUS_SESSION_EN_HALTE


def test_le_noyau_IMPORTE_ET_APPELLE_evaluer_session():
    """MENTION → PORTE : importer ne suffit pas, il faut APPELER. Les deux sont exigés."""
    tree = ast.parse(NOYAU.read_text(encoding="utf-8"))
    importe = any(isinstance(n, ast.ImportFrom) and n.module and "session_gate" in n.module
                  for n in ast.walk(tree))
    appelle = any(isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id == "evaluer_session" for n in ast.walk(tree))
    assert importe, "le noyau doit importer session_gate"
    assert appelle, "le noyau doit APPELER evaluer_session (mention != porte)"


def test_il_y_a_vraiment_11_gates_v19():
    """« 11 gardes » doit être VRAI : 11 sites d'ajout de gate dans risk_engine_v3. Un gate retiré
    = un garde-fou mort → ce test casse."""
    n = RISK.read_text(encoding="utf-8").count("gates.append(")
    assert n == 11, f"attendu 11 gates V19, trouvé {n}"
