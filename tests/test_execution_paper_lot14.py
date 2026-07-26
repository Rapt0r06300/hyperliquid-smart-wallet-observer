"""LOT14 #5-#9 — exécution deux jambes, REDUCE proportionnel, data-missing, réconciliation, registre/PBO."""
from __future__ import annotations

import random

from hl_observer.experimental import execution_paper as EP
from hl_observer.experimental import reconciliation_paper as REC
from hl_observer.experimental import registre_essais as REG
from hl_observer.research_parallel import validation as VAL


# ── #5 dislocation deux jambes ──
def test_pnl_deux_jambes_somme_exacte():
    jambes = [{"venue": "HL", "side": -1, "entry_px": 100.2, "exit_px": 100.0, "size_usd": 50, "fee_bps": 4.5},
              {"venue": "BIN", "side": 1, "entry_px": 100.0, "exit_px": 100.05, "size_usd": 50, "fee_bps": 4.5}]
    r = EP.pnl_deux_jambes(jambes)
    assert r["n_jambes"] == 2
    somme = round(sum(j["realized_usd"] for j in r["jambes"]), 6)
    assert r["realized_usd"] == somme, "PnL total = somme EXACTE des jambes"
    # jambe short HL gagne (prix baisse), jambe long BIN gagne (prix monte)
    assert r["jambes"][0]["realized_usd"] > -1 and r["jambes"][1]["realized_usd"] > -1


# ── #6 copy-vault REDUCE proportionnel ──
def test_reduce_proportionnel_ferme_la_fraction():
    pos = {"notional_usd": 100.0, "sens": 1, "prix_entree": 100.0}
    r = EP.reduce_proportionnel(pos, taille_leader_avant=10.0, taille_leader_apres=6.0,
                                prix_sortie=100.1, cout_sortie_bps=5.0)
    assert r["action"] == "REDUCE" and r["ratio_restant"] == 0.6
    assert abs(r["notional_ferme_usd"] - 40.0) < 1e-6 and abs(r["notional_residuel_usd"] - 60.0) < 1e-6
    assert r["frais_partie_fermee_usd"] > 0                      # frais SEULEMENT sur la partie fermée


def test_close_integral_seulement_si_leader_quasi_zero():
    pos = {"notional_usd": 100.0, "sens": 1, "prix_entree": 100.0}
    r = EP.reduce_proportionnel(pos, taille_leader_avant=10.0, taille_leader_apres=0.2,
                                prix_sortie=100.1, cout_sortie_bps=5.0)   # ratio 0.02 <= 0.05
    assert r["action"] == "CLOSE_INTEGRAL" and r["notional_residuel_usd"] == 0.0


def test_snapshot_incomplet_ne_cloture_pas():
    ok, motif = EP.snapshot_complet_ok({"complet": False}, "BTC", ts_entree_ms=0, now_ms=1000)
    assert ok is False and motif == "SNAPSHOT_INCOMPLET"
    # snapshot complet mais antérieur à l'entrée -> refus
    ok2, motif2 = EP.snapshot_complet_ok({"complet": True, "ts_ms": 50}, "BTC", ts_entree_ms=100, now_ms=200)
    assert ok2 is False and motif2 == "SNAPSHOT_ANTERIEUR_ENTREE"
    ok3, _ = EP.snapshot_complet_ok({"complet": True, "ts_ms": 150}, "BTC", ts_entree_ms=100, now_ms=160)
    assert ok3 is True


# ── #7 donnée manquante ──
def test_data_missing_grace_puis_timeout():
    pos = {"ts_derniere_donnee_ms": 0, "ts_ouverture_ms": 0, "prix_entree": 100.0}
    assert EP.politique_data_missing(pos, now_ms=60_000, grace_ms=120_000)["action"] == "ATTENDRE"
    r = EP.politique_data_missing(pos, now_ms=200_000, grace_ms=120_000)
    assert r["action"] == "SORTIE" and r["raison"] == "DATA_MISSING_TIMEOUT"
    assert r["mark_conservateur"] == 100.0 and r["slippage_stress_bps"] > 0


# ── #8 réconciliation ──
def test_reconciliation_coherente_dans_tolerance():
    ledger = [{"kind": "OPEN", "strategie": "cross_venue", "coin": "BTC"},
              {"kind": "CLOSE", "strategie": "cross_venue", "coin": "BTC", "realized_net_pnl_usdc": 0.50},
              {"kind": "CLOSE", "strategie": "copy_vault", "coin": "SOL", "realized_net_pnl_usdc": -0.20}]
    r = REC.auditer(ledger, realise_store_usd=0.30, realise_statut_usd=0.30)
    assert r["coherent"] is True and abs(r["realized_total_ledger_usd"] - 0.30) < 1e-9


def test_reconciliation_detecte_ecart():
    ledger = [{"kind": "CLOSE", "strategie": "cv", "coin": "BTC", "realized_net_pnl_usdc": 1.0}]
    r = REC.auditer(ledger, realise_store_usd=0.5, realise_statut_usd=1.0)     # store diverge de 0,50
    assert r["coherent"] is False and r["ecart_ledger_store_usd"] == 0.5


# ── #9 registre + DSR tous essais + PBO surappris ──
def test_registre_append_only_et_dsr_tous_essais(tmp_path):
    REG.enregistrer(tmp_path, {"family": "OFI", "variant": "top5", "result": "KILL", "pass_kill": "KILL", "sharpe": -0.3})
    REG.enregistrer(tmp_path, {"family": "OFI", "variant": "top1", "result": "KILL", "pass_kill": "KILL", "sharpe": 0.1})
    essais = REG.charger(tmp_path)
    assert len(essais) == 2 and all(e["preregistration_ts"] for e in essais)
    sh = REG.sharpes_tous_essais(essais)
    assert sh == [-0.3, 0.1], "le DSR reçoit TOUS les essais (KILL compris), pas seulement les gagnants"


def test_pbo_discrimine_surappris_vs_robuste():
    # ROBUSTE : une variante domine PARTOUT (IS et OOS) -> PBO bas (~0). SURAPPRIS : 6 variantes de pur
    # bruit -> la meilleure IS n'a aucune raison de tenir OOS -> PBO nettement plus élevé. Le PBO DISCRIMINE.
    robuste = {"gagnante": [5.0] * 16, "b": [-1.0] * 16, "c": [-2.0] * 16}
    pbo_robuste = VAL.pbo_cscv(robuste, s=8)["pbo"]
    rng = random.Random(3)
    bruit = {"v%d" % k: [rng.gauss(0, 1) for _ in range(16)] for k in range(6)}
    pbo_bruit = VAL.pbo_cscv(bruit, s=8)["pbo"]
    assert pbo_robuste == 0.0, "une vraie stratégie robuste -> PBO ~0"
    assert pbo_bruit > pbo_robuste, "le sur-ajustement (bruit) a un PBO nettement plus élevé -> détecté"
