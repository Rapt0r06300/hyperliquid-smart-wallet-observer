"""[pépite 247] child attribution engine : répartir qté/frais/slippage aux intents sources déterministe."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.child_attribution_engine import attribuer   # noqa: E402


def test_repartition_prorata():
    contribs = [{"module": "a", "montant": 30.0}, {"module": "b", "montant": 10.0}]
    r = attribuer(contribs, qte_totale=4.0, frais_total=0.8, slippage_total=0.4)
    parts = {p["module"]: p for p in r["parts"]}
    assert parts["a"]["qte"] == 3.0 and parts["b"]["qte"] == 1.0   # 75% / 25%
    assert r["controle_qte"] == 4.0


def test_contributions_nulles():
    assert attribuer([{"module": "a", "montant": 0.0}], qte_totale=1.0, frais_total=0.0, slippage_total=0.0)["parts"] == "UNMEASURABLE"


def test_totaux_invalides():
    assert attribuer([{"module": "a", "montant": 1.0}], qte_totale=None, frais_total=0.0, slippage_total=0.0)["parts"] == "UNMEASURABLE"
