import pytest

from hl_observer.ops.canonical_paper_intent_chain import STRATEGIES_ACTIVES, chaine_famille
from hl_observer.ops.paper_canonique import ScopeViolation


def test_chaque_famille_active_traverse_la_chaine_canonique():
    assert len(STRATEGIES_ACTIVES) == 3
    for fam in STRATEGIES_ACTIVES:
        c = chaine_famille(fam)
        assert c["intent"]["strategy"] == fam
        assert c["ordre"]["strategy"] == fam and c["ordre"]["real_execution"] is False
        assert c["fill"]["type"] == "FILL" and c["fill"]["real_execution"] is False
        assert c["fill"]["strategy"] == fam and c["intent"]["real_execution"] is False


def test_une_famille_disabled_ne_peut_pas_entrer_dans_la_chaine():
    with pytest.raises(ScopeViolation):
        chaine_famille("carry")


def test_le_side_et_le_notional_sont_preserves_de_bout_en_bout():
    c = chaine_famille(STRATEGIES_ACTIVES[0], side=-1, notional_usd=75.0, prix=123.0)
    assert c["intent"]["side"] == -1 and c["ordre"]["side"] == -1 and c["fill"]["side"] == -1
    assert c["fill"]["notional_usd"] == 75.0 and c["fill"]["prix"] == 123.0
