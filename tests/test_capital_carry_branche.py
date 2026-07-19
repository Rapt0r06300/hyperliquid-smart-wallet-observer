"""LA MARGE DYNAMIQUE EST-ELLE VRAIMENT ALIMENTÉE ? — le test qui manquait ce matin.

CE QUI S'EST PASSÉ (19/07). J'ai livré une « marge dynamique » censée déployer le capital au
lieu de laisser 92 % dormir. J'ai écrit le module, ses 10 tests, le câblage, le commit. Puis,
en relisant un notional par hasard, j'ai vu **75 $** — la valeur par défaut. Elle n'avait
JAMAIS agi.

La cause : je l'avais branchée sur `simulation.paper_ledger.equity_courante(...)`, une fonction
qui **n'existe pas**. L'import levait une ImportError, avalée par un `except Exception`, et on
retombait sur une variable d'environnement que le lanceur ne pose nulle part -> `None` ->
marge par défaut.

Mes 10 tests passaient tous : ils testaient la FONCTION de sizing, jamais son ALIMENTATION.
C'est la maladie du projet dans sa forme la plus pure — « mention ≠ porte » — et je l'ai
commise le jour même où je la traquais partout ailleurs.

Ces tests ferment ce trou : ils vérifient que le capital ARRIVE, pas qu'il serait bien utilisé
s'il arrivait.
"""
from __future__ import annotations

import json

import pytest

from hl_observer.funding import carry_paper_runtime as runtime


@pytest.fixture(autouse=True)
def _env_propre(monkeypatch):
    monkeypatch.delenv(runtime.ENV_CAPITAL, raising=False)
    yield


def test_le_capital_est_lu_dans_l_etat_moteur(tmp_path):
    """La source PRINCIPALE : l'équity que le runtime écrit lui-même."""
    d = tmp_path / "runtime" / "data"
    d.mkdir(parents=True)
    (d / "ui_simulation_state.json").write_text(json.dumps({"equity_usdt": 1234.5}),
                                                encoding="utf-8")
    assert runtime._capital_disponible(tmp_path) == 1234.5


def test_repli_sur_la_variable_d_environnement(tmp_path, monkeypatch):
    monkeypatch.setenv(runtime.ENV_CAPITAL, "2000")
    assert runtime._capital_disponible(tmp_path) == 2000.0


def test_capital_INCONNU_rend_None_et_n_invente_RIEN(tmp_path):
    """RÈGLE DURE : inventer un capital, c'est inventer une taille de position, donc un PnL.
    Aucune source lisible -> None -> le sizing retombe sur sa marge par défaut, explicitement."""
    assert runtime._capital_disponible(tmp_path) is None


def test_un_etat_moteur_ILLISIBLE_ne_fait_pas_planter(tmp_path):
    d = tmp_path / "runtime" / "data"
    d.mkdir(parents=True)
    (d / "ui_simulation_state.json").write_text("{ ceci n'est pas du json", encoding="utf-8")
    assert runtime._capital_disponible(tmp_path) is None


def test_une_equity_ABSURDE_est_ecartee(tmp_path):
    """Une équity nulle ou négative n'est pas un capital : on ne dimensionne pas dessus."""
    d = tmp_path / "runtime" / "data"
    d.mkdir(parents=True)
    for valeur in (0, -100, "mille", None):
        (d / "ui_simulation_state.json").write_text(json.dumps({"equity_usdt": valeur}),
                                                    encoding="utf-8")
        assert runtime._capital_disponible(tmp_path) is None, valeur


def test_LA_PREUVE_le_capital_change_VRAIMENT_la_taille(tmp_path):
    """LE TEST QUI AURAIT ATTRAPÉ LE BUG : on ne verifie pas que la fonction de sizing est
    correcte (c'est deja fait ailleurs) -- on verifie que le capital ARRIVE jusqu'a elle."""
    from hl_observer.funding.carry_positions_store import charger_gestionnaire, tick_multi_sur_disque

    decision = {"coin": "HYPE", "viable": True, "funding_bps_h": 0.125, "base_bps": -1.5,
                "levier": 1.5, "cout_entree_bps": 12.47, "liquidite_spot_usd": 150_000.0,
                "marge_ratio": 0.667, "levier_max": 10.0}
    inputs = {"coin": "HYPE", "perp_px": 61.0, "levier_utilise": 1.5, "marge_ratio": 0.667}
    mesures = {"HYPE": {"decision": decision, "inputs": inputs, "funding": 0.125, "prix": 61.0}}

    # capital INCONNU -> defaut
    tick_multi_sur_disque(tmp_path / "sans", mesures, now_ms=1_800_000_000_000, max_slots=12,
                          capital_usd=runtime._capital_disponible(tmp_path / "sans"))
    sans = charger_gestionnaire(tmp_path / "sans").ouvertes["HYPE"]["notional_usdt"]

    # capital LISIBLE dans l'etat moteur -> la position doit grossir
    racine = tmp_path / "avec"
    (racine / "runtime" / "data").mkdir(parents=True)
    (racine / "runtime" / "data" / "ui_simulation_state.json").write_text(
        json.dumps({"equity_usdt": 1000.0}), encoding="utf-8")
    tick_multi_sur_disque(racine, mesures, now_ms=1_800_000_000_000, max_slots=12,
                          capital_usd=runtime._capital_disponible(racine))
    avec = charger_gestionnaire(racine).ouvertes["HYPE"]["notional_usdt"]

    assert sans == 75.0, "sans capital connu, on garde le comportement par defaut"
    assert avec > sans * 4, (
        "LE CAPITAL N'ARRIVE PAS JUSQU'AU SIZING : notional %s au lieu d'etre agrandi. "
        "C'est exactement le bug du 19/07 -- un module branche sur une fonction fantome." % avec)
