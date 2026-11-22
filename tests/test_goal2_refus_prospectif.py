"""H16 : un filtre ne réussit que s'il améliore le PnL TOTAL avec assez de couverture, sur données d'après le gel."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import goal2_refus_prospectif as R  # noqa: E402

J = 86_400_000


def _c(jour: int, usd: float, absorption: float, notionnel: float = 50_000.0, latence: int = 5_000) -> dict:
    return {"entree_ms": R.GEL_MS + jour * J + 3_600_000, "realized_usd": usd,
            "contexte": {"absorption_bps": absorption, "latence_ms": latence, "notionnel_leader_usd": notionnel}}


def test_un_filtre_qui_retire_les_perdants_reussit() -> None:
    cycles = []
    for j in range(6):
        cycles += [_c(j, -0.05, 8.0) for _ in range(12)] + [_c(j, 0.03 + 0.001 * k, 0.0) for k in range(20)]
    x = R.juger(cycles)["filtres"]["F1_deja_absorbe"]
    assert x["statut"] == "PROMISING" and x["refuses"] == 72 and x["pertes_evitees_usd"] > 0


def test_un_filtre_qui_ne_garde_presque_rien_echoue_meme_s_il_gagne() -> None:
    cycles = []
    for j in range(6):
        cycles += [_c(j, -0.05, 8.0) for _ in range(30)] + [_c(j, 0.03, 0.0) for _ in range(3)]
    assert R.juger(cycles)["filtres"]["F1_deja_absorbe"]["statut"] == "REJECTED"     # couverture 9 %


def test_trop_peu_de_jours_reste_more_data() -> None:
    cycles = [_c(0, -0.05, 8.0) for _ in range(80)] + [_c(0, 0.03, 0.0) for _ in range(80)]
    assert R.juger(cycles)["filtres"]["F1_deja_absorbe"]["statut"] == "MORE_DATA"


def test_contexte_absent_garde_la_copie() -> None:
    c = {"entree_ms": R.GEL_MS + J, "realized_usd": -1.0, "contexte": None}
    r = R.juger([c])
    assert r["contexte_absent"] == 1 and r["filtres"]["F4_union"]["refuses"] == 0


def test_rien_avant_le_gel_n_est_juge() -> None:
    tape = {"BTC": [(R.GEL_MS - 10 * 3_600_000 + k * 60_000, 100.0) for k in range(900)]}
    ligne = {"dir": "Open Long", "recu_ms": R.GEL_MS - 3_600_000 * 5, "vault": "0xa", "coin": "BTC", "sz": 1000, "px": 100.0,
             "oid": 1}
    assert R.cycles_de_base(Path("."), R.GEL_MS + 10 * 3_600_000, lignes=[ligne], tape=tape, tvl={"0xa": 1e6}) == []
