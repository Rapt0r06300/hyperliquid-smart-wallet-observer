"""BOT-READY CLI — lit le dernier RECAP + les verrous testnet et délègue le barème à
loop_readiness. Ce qu'on verrouille : parsing tolérant, dérivation HONNÊTE (suite verte =
preuve des invariants gardés par des tests nommés ; suite rouge = deny-by-default), et le
plafond testnet (jamais le réel). Aucune donnée réseau, aucun ordre."""
from __future__ import annotations

import importlib.util
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod(nom: str):
    chemin = RACINE / "tools" / ("%s.py" % nom)
    spec = importlib.util.spec_from_file_location(nom, chemin)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


BR = _mod("bot_ready")

_RECAP_VERT = """## Étapes

| Étape | Statut | Durée | Détail |
|---|---|---|---|
| securite | OK | 21 s | no_real_execution_capable_package: ok |
| tests | OK | 414 s | 5746 passed |
| cablage | OK | 1 s | garde-fous importes |
| donnees | OK | 5 s | rapport |

 "couverture_pct": 92.0,
"""


def _ecrire(tmp_path, recap: str, *, verrous=True):
    (tmp_path / "RECAP-COMPLET.md").write_text(recap, encoding="utf-8")
    if verrous:
        (tmp_path / ".env.example").write_text(
            "REAL_MAINNET_TRADING=false\nTESTNET_ONLY=true\n", encoding="utf-8")


def test_recap_tout_vert_avec_verrous_donne_A_et_N2(tmp_path):
    _ecrire(tmp_path, _RECAP_VERT)
    r = BR.collecter(tmp_path)
    assert r.grade == "A" and r.no_real_trade_intact is True
    assert r.niveau_autonomie == BR.LR.NIVEAU_TESTNET      # testnet, JAMAIS le réel
    assert r.real_execution is False


def test_sans_verrous_testnet_on_plafonne_a_N1(tmp_path):
    _ecrire(tmp_path, _RECAP_VERT, verrous=False)
    r = BR.collecter(tmp_path)
    assert r.niveau_autonomie == BR.LR.NIVEAU_PAPER


def test_securite_en_echec_force_F_et_N0(tmp_path):
    _ecrire(tmp_path, _RECAP_VERT.replace("| securite | OK", "| securite | ECHEC"))
    r = BR.collecter(tmp_path)
    assert r.grade == "F" and r.niveau_autonomie == BR.LR.NIVEAU_OBSERVE


def test_tests_rouges_rendent_les_invariants_gardes_deny_by_default(tmp_path):
    """Suite rouge -> on NE dérive PAS pnl/coût/kill-switch (ils sont gardés par des tests qui,
    justement, ne sont pas tous verts). Score conservateur, autonomie retombée à N0."""
    _ecrire(tmp_path, _RECAP_VERT.replace("| tests | OK", "| tests | ECHEC"))
    r = BR.collecter(tmp_path)
    assert r.dimensions["pnl_reconcilie"]["score"] == 0.0
    assert r.dimensions["portes_cout_actives"]["score"] == 0.0
    assert r.niveau_autonomie == BR.LR.NIVEAU_OBSERVE


def test_pas_de_recap_du_tout_deny_by_default(tmp_path):
    # aucun RECAP -> sécurité non prouvée -> gate dur -> F / N0. Jamais un score optimiste.
    r = BR.collecter(tmp_path)
    assert r.grade == "F" and r.niveau_autonomie == BR.LR.NIVEAU_OBSERVE
