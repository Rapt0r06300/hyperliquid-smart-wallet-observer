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
        assert c["intent"]["intent_id"].startswith("paper-intent:")
        assert c["ordre"]["intent_id"] == c["intent"]["intent_id"]
        assert c["fill"]["intent_id"] == c["intent"]["intent_id"]
        assert c["fill"]["order_id"] == c["ordre"]["order_id"]
        assert c["position"]["position_id"] == c["fill"]["position_id"]
        assert c["ledger_open"]["position_id"] == c["position"]["position_id"]
        assert c["ledger_open"]["fill_id"] == c["fill"]["fill_id"]
        assert c["ledger_open"]["kind"] == "OPEN"
        assert c["ledger_open"]["lane"] == "MAIN"
        assert c["position"]["real_execution"] is False
        assert c["ledger_open"]["real_execution"] is False


def test_une_famille_disabled_ne_peut_pas_entrer_dans_la_chaine():
    with pytest.raises(ScopeViolation):
        chaine_famille("carry")


def test_le_side_et_le_notional_sont_preserves_de_bout_en_bout():
    c = chaine_famille(STRATEGIES_ACTIVES[0], side=-1, notional_usd=75.0, prix=123.0)
    assert c["intent"]["side"] == -1 and c["ordre"]["side"] == -1 and c["fill"]["side"] == -1
    assert c["fill"]["notional_usd"] == 75.0 and c["fill"]["prix"] == 123.0


def test_identifiants_deterministes_et_non_vides():
    a = chaine_famille(STRATEGIES_ACTIVES[0], coin="HYPE", side=1, notional_usd=25.0, prix=70.0)
    b = chaine_famille(STRATEGIES_ACTIVES[0], coin="HYPE", side=1, notional_usd=25.0, prix=70.0)
    for key in ("intent_id",):
        assert a["intent"][key]
        assert a["intent"][key] == b["intent"][key]
    assert a["ordre"]["order_id"] == b["ordre"]["order_id"]
    assert a["fill"]["fill_id"] == b["fill"]["fill_id"]
    assert a["position"]["position_id"] == b["position"]["position_id"]
