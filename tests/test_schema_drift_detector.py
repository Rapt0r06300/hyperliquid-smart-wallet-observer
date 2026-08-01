"""[pépite 255] schema drift detector : champ disparu / type changé / enum nouveau → quarantaine."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.data_contract.schema_drift_detector import detecter   # noqa: E402


def test_pas_de_drift():
    ref = {"price": "str", "qty": "str", "side": "str"}
    assert detecter(ref, dict(ref))["action"] == "OK"


def test_champ_disparu_et_type_modifie():
    ref = {"price": "str", "qty": "str"}
    obs = {"price": "float"}                       # qty disparu + price type changé
    r = detecter(ref, obs)
    raisons = {a["type"] for a in r["anomalies"]}
    assert r["action"] == "QUARANTAINE" and {"CHAMP_DISPARU", "TYPE_MODIFIE"} <= raisons


def test_enum_nouveau():
    ref = {"side": "str"}
    r = detecter(ref, {"side": "str"}, enums_connus={"side": {"BUY", "SELL"}}, enums_observes={"side": "XXX"})
    assert r["drift"] is True and any(a["type"] == "ENUM_NOUVEAU" for a in r["anomalies"])
