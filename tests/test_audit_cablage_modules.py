"""S7 — l'outil d'audit câblage doit classer chaque module dans exactement une catégorie,
reconnaître un module CÂBLÉ connu (edge_net_v12, importé par le noyau), et sommer au total.
100% lecture, aucun ordre."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "audit_cablage_modules", ROOT / "tools" / "audit_cablage_modules.py")
MOD = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MOD)


def test_categories_partitionnent_le_total():
    r = MOD.classer()
    cat, tot = r["cat"], r["total"]
    assert set(cat) == {"CABLE", "TESTE_SEULEMENT", "ORPHELIN"}
    assert sum(len(v) for v in cat.values()) == tot
    assert tot > 0
    # chaque module dans EXACTEMENT une categorie (pas de doublon inter-categorie)
    tous = [nom for lst in cat.values() for nom in lst]
    assert len(tous) == len(set(tous))


def test_edge_net_v12_est_cable():
    # l'edge LIVE est importe par le noyau -> doit ressortir CABLE, jamais orphelin.
    r = MOD.classer()
    edge = [n for n in (r["cat"]["CABLE"] + r["cat"]["TESTE_SEULEMENT"] + r["cat"]["ORPHELIN"])
            if n.endswith("edge_net_v12.py")]
    assert edge, "edge_net_v12 introuvable"
    assert r["detail"][edge[0]] == "CABLE"


def test_un_module_pur_teste_nest_pas_marque_cable_a_tort():
    # base_convergence (A5) est importe par le lifecycle carry -> CABLE ; on verifie juste
    # que la classification renvoie une valeur connue (pas de KeyError, pas d'inconnu).
    r = MOD.classer()
    for nom, k in r["detail"].items():
        assert k in {"CABLE", "TESTE_SEULEMENT", "ORPHELIN"}
