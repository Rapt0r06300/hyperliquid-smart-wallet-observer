"""A8: vague de couverture d'orphelins (contrats figés → prêts à câbler).

Chaque test fige le comportement d'un module orphelin utile au risque/copy, pour
qu'il puisse être branché en confiance. Réf docs/audit/ORPHAN_MODULES_AUDIT.
"""

from __future__ import annotations

from hl_observer.clusters.crowding_detector import crowding_score
from hl_observer.edge.copy_degradation import entry_copy_degradation_bps
from hl_observer.risk.duplicate_order_guard import DuplicateOrderGuard
from hl_observer.risk.position_sizing import clamp_paper_size
from hl_observer.risk.reconciliation_guard import reconciliation_ok


def test_duplicate_order_guard_blocks_repeat_signal():
    g = DuplicateOrderGuard()
    assert g.check_and_mark("sig-1") is True
    assert g.check_and_mark("sig-1") is False   # doublon refusé
    assert g.check_and_mark("sig-2") is True


def test_reconciliation_guard_blocks_uncertain():
    assert reconciliation_ok(False) is True
    assert reconciliation_ok(True) is False     # incertitude → bloque


def test_crowding_score_saturates():
    assert crowding_score(0) == 0.0
    assert crowding_score(5, 5) == 1.0
    assert crowding_score(10, 5) == 1.0         # borné à 1.0 (trop de monde du même côté)
    assert 0 < crowding_score(2, 5) < 1


def test_copy_degradation_bps_sign_and_magnitude():
    # LONG copié 10 bps plus cher que le leader → dégradation positive (coûteuse)
    d = entry_copy_degradation_bps(side="long", leader_entry_price=100.0, copy_entry_price=100.1)
    assert round(d, 1) == 10.0
    # SHORT copié plus bas = aussi une dégradation positive
    s = entry_copy_degradation_bps(side="short", leader_entry_price=100.0, copy_entry_price=99.9)
    assert round(s, 1) == 10.0


def test_position_sizing_clamp():
    assert clamp_paper_size(100.0, max_size_usdc=40.0) == 40.0
    assert clamp_paper_size(-5.0, max_size_usdc=40.0) == 0.0
    assert clamp_paper_size(25.0, max_size_usdc=40.0) == 25.0
