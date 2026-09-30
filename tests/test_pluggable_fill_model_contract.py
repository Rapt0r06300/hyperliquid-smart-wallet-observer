"""[ALL #98] pluggable FillModel contract : chaque type d'exécution fournit son modèle ; type sans modèle refusé."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.execution_core.pluggable_fill_model_contract import RegistreFillModels   # noqa: E402


class _ModeleFictif:
    def simuler(self, ordre):
        return {"prix_fill": ordre.get("prix"), "qte_remplie": ordre.get("qte"), "slippage_bps": 2.0}


def test_enregistrer_et_simuler():
    reg = RegistreFillModels()
    assert reg.enregistrer("MAKER", _ModeleFictif())["ok"] is True
    r = reg.simuler("MAKER", {"prix": 100.0, "qte": 1.0})
    assert r["ok"] is True and r["resultat"]["slippage_bps"] == 2.0


def test_type_sans_modele_refuse():
    reg = RegistreFillModels()
    r = reg.simuler("TAKER", {"prix": 100.0})
    assert r["ok"] is False and r["raison"] == "AUCUN_FILLMODEL_POUR_CE_TYPE"


def test_contrat_non_respecte_refuse():
    reg = RegistreFillModels()
    assert reg.enregistrer("MAKER", object())["ok"] is False   # pas de méthode simuler
