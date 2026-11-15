"""L'executeur paper en avant — il tient un livre de comptes, donc il doit etre incorruptible.

DIFFERENCE AVEC LE PROTOCOLE GELE : celui-ci REJOUE l'histoire posterieure au gel ; l'executeur
DECIDE au fil du temps, sa decision etant ecrite AVANT que le resultat n'existe. C'est la
difference entre « la strategie aurait gagne » et « la strategie a gagne ».

Les trois refus verrouilles ici sont ceux qui fabriqueraient un PnL faux.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))


def _mod():
    spec = importlib.util.spec_from_file_location("paper_carry_inverse",
                                                  RACINE / "tools" / "paper_carry_inverse.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_le_livre_se_charge_vide_quand_le_schema_ne_correspond_PAS(tmp_path):
    """Un fichier d'un autre schema ne doit pas etre lu comme un grand livre : on repart propre
    plutot que d'interpreter des champs qui n'ont pas le meme sens."""
    m = _mod()
    f = tmp_path / "livre.json"
    f.write_text(json.dumps({"_schema": "autre.chose.v9", "positions": [{"coin": "FAUX"}]}),
                 encoding="utf-8")
    livre = m.charger_livre(f)
    assert livre["_schema"] == m.SCHEMA
    assert livre["positions"] == []


def test_un_fichier_illisible_ne_fait_PAS_perdre_le_programme(tmp_path):
    m = _mod()
    f = tmp_path / "livre.json"
    f.write_text("{ ceci n'est pas du json", encoding="utf-8")
    assert m.charger_livre(f)["positions"] == []


def test_la_sauvegarde_est_ATOMIQUE(tmp_path):
    """Un livre de comptes a moitie ecrit vaut pire que pas de livre : on ecrit un .tmp puis on
    remplace."""
    m = _mod()
    f = tmp_path / "sous" / "livre.json"
    livre = m.charger_livre(f)
    livre["positions"].append({"coin": "BTC", "sens": "LONG", "instant_h": 1, "notionnel": 10.0})
    m.sauver_livre(f, livre)
    assert json.loads(f.read_text(encoding="utf-8"))["positions"][0]["coin"] == "BTC"
    assert not f.with_name(f.name + ".tmp").exists()      # le temporaire a bien ete consomme


def test_les_conventions_sont_celles_du_protocole_GELE():
    """Un executeur qui laisserait regler l'horizon apres avoir vu le resultat transformerait la
    mesure en recherche. Ces valeurs ne sont pas des options."""
    m = _mod()
    assert (m.HORIZON_H, m.FENETRE_H, m.K) == (96, 96, 3)


def test_le_cout_n_est_PAS_le_slippage_suppose_de_2_bps():
    """Le slippage a ete MESURE a ~4,2 bps sur 80 000 cas. Reprendre 2 bps retirerait 15 % du
    net sans que rien ne le signale."""
    m = _mod()
    assert m.SLIPPAGE_DEFAUT_BPS > 3.5
    assert m.TAKER_BPS == 4.5


def test_aucune_surface_d_execution_dans_l_executeur():
    """« Paper » doit etre vrai dans le code, pas seulement dans le nom."""
    source = (RACINE / "tools" / "paper_carry_inverse.py").read_text(encoding="utf-8")
    for interdit in ("urlopen", "requests.", "private_key", "sign(", "exchange.order"):
        assert interdit not in source, f"surface d'execution suspecte : {interdit}"
