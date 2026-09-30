from hl_observer.ops.expected_gain_ranking import classer_actions, gain_attendu


def test_gain_attendu():
    assert gain_attendu({"valeur": 100.0, "proba": 0.5, "cout": 10.0}) == 40.0


def test_classement_decroissant():
    actions = [
        {"nom": "A", "valeur": 100.0, "proba": 0.2, "cout": 5.0},
        {"nom": "B", "valeur": 100.0, "proba": 0.9, "cout": 10.0},
        {"nom": "C", "valeur": 50.0, "proba": 0.5, "cout": 30.0},
    ]
    r = classer_actions(actions)
    assert [a["nom"] for a in r] == ["B", "A", "C"]
    assert r[0]["gain_attendu"] == 80.0 and r[-1]["gain_attendu"] == -5.0
