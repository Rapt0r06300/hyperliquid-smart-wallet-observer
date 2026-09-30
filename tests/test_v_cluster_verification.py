"""CLUSTER V (V1-V12) — VÉRIFICATION du chemin LIVE. Discipline dure : chaque test doit ÉCHOUER si
la propriété qu'il vérifie est violée (sinon c'est un test vide — le péché que V11 dénonce).

On vérifie ici ce qui est AUTOMATISABLE dans le sandbox sur le code LIVE lu en entier
(edge_net_v12 + v12_decision_pipeline + filter_pipeline + freshness + feature_normalize). Ce qui
exige le RUNTIME (dashboard live) ou WINDOWS (suite complète, mutation testing exhaustif) est
délégué aux tests existants cités et au rapport docs/audit/V1-V12_VERIFICATION.md. PAPER only."""
from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from hl_observer.edge.edge_net_v12 import EdgeNetV12Inputs, estimate_edge_net_v12
from hl_observer.execution.freshness_cut import frais_pour_envoi
from hl_observer.features.feature_normalize import zscore_roulant
from hl_observer.gating.filter_pipeline import ContexteDecision, appliquer_filtres
from hl_observer.pipeline.v12_decision_pipeline import (
    V12DecisionPipelineConfig, _appliquer_gardes,
)

ROOT = Path(__file__).resolve().parents[1]
PORTE = ROOT / "src" / "hl_observer" / "pipeline" / "v12_decision_pipeline.py"
PORTE_SRC = PORTE.read_text(encoding="utf-8")


# ============================ V1 — chaque garde est ATTEINT sur le chemin LIVE ============================

def test_v1_toutes_les_portes_appelees_sur_le_chemin():
    appels = {n.func.id for n in ast.walk(ast.parse(PORTE_SRC))
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    for porte in ("estimate_edge_net_v12", "appliquer_filtres", "_appliquer_gardes",
                  "_etat_moteur", "_facteur_sizing"):
        assert porte in appels, f"porte non appelée sur le chemin LIVE : {porte}"


# ============================ V3 — coûts RÉELS et non nuls dans l'edge LIVE ============================

def test_v3_couts_coeur_non_nuls_par_defaut():
    cfg = V12DecisionPipelineConfig()
    assert cfg.spread_bps and cfg.spread_bps > 0
    assert cfg.slippage_bps and cfg.slippage_bps > 0
    assert cfg.fee_bps and cfg.fee_bps > 0            # anti fail-open : un coût nul ferait passer du bruit


def test_v3_cout_manquant_donne_no_trade():
    # fee absent -> non mesurable -> refus (on ne devine pas un coût)
    inp = EdgeNetV12Inputs(leader_reference_price=100.0, current_mid=100.0,
                           leader_expected_edge_bps=80.0, spread_bps=2.0, slippage_bps=2.0,
                           fee_bps=None, funding_estimate_bps=0.0)
    est = estimate_edge_net_v12(inp)
    assert est.measurable is False and est.accepted is False


# ============================ V4 — unités : les frais ne sont PAS comptés deux fois ============================

def test_v4_total_cout_est_la_somme_unique_des_composantes():
    inp = EdgeNetV12Inputs(leader_reference_price=100.0, current_mid=100.0,
                           leader_expected_edge_bps=80.0, spread_bps=2.0, slippage_bps=3.0,
                           fee_bps=4.5, funding_estimate_bps=1.0)
    est = estimate_edge_net_v12(inp)
    # chaque coût apparaît UNE fois ; total = somme exacte (pas de double comptage de frais)
    assert abs(est.total_cost_bps - sum(est.cost_breakdown_bps.values())) < 1e-9
    assert est.cost_breakdown_bps["fee_bps"] == 4.5     # frais comptés une seule fois


# ============================ V5 — l'edge est SOUSTRAIT et UTILISÉ (pas mesuré puis jeté) ============================

def test_v5_net_est_gross_moins_couts():
    inp = EdgeNetV12Inputs(leader_reference_price=100.0, current_mid=100.0,
                           leader_expected_edge_bps=80.0, spread_bps=2.0, slippage_bps=3.0,
                           fee_bps=4.5, funding_estimate_bps=0.0)
    est = estimate_edge_net_v12(inp)
    assert abs(est.net_edge_bps - (est.gross_edge_bps - est.total_cost_bps)) < 1e-9


def test_v5_net_negatif_jamais_accepte():
    inp = EdgeNetV12Inputs(leader_reference_price=100.0, current_mid=100.0,
                           leader_expected_edge_bps=3.0, spread_bps=2.0, slippage_bps=3.0,
                           fee_bps=4.5, funding_estimate_bps=0.0)  # coûts > edge -> net < 0
    est = estimate_edge_net_v12(inp)
    assert est.net_edge_bps < 0 and est.accepted is False


def test_v5_la_porte_passe_le_net_a_apply_delta_pas_une_constante():
    # anti-régression du bug historique "le LIVE mesurait puis JETAIT l'edge"
    assert "edge_remaining_bps=float(edge.net_edge_bps" in PORTE_SRC


# ============================ V6 — aucun garde AFFAMÉ (entrée absente -> abstention, pas refus) ============================

def test_v6_entrees_absentes_donnent_abstention_jamais_refus():
    # ctx minimal : seuls coin + univers. Tous les autres gardes DOIVENT s'abstenir, pas refuser.
    r = appliquer_filtres(ContexteDecision(coin="BTC", est_sortie=False, univers=("BTC", "ETH")))
    assert r.accepte is True, "un garde s'affame (refuse faute d'entrée) : interdit"
    assert not r.refus
    assert r.abstentions      # il DOIT y avoir des abstentions (les entrées absentes)


def test_v6_sortie_jamais_bloquee():
    r = appliquer_filtres(ContexteDecision(coin="DOGE", est_sortie=True, univers=("BTC", "ETH")))
    assert r.accepte is True   # une sortie risque-réductrice n'est jamais refusée


# ============================ V7 — fraîcheur/calibration : périmé/absent -> DENY (pas de défaut mort) ============================

def test_v7_fraicheur_inconnue_est_refusee():
    assert frais_pour_envoi(None) is False        # âge inconnu -> périmé (deny-by-default)
    assert frais_pour_envoi(10.0) is True         # frais
    assert frais_pour_envoi(10_000.0) is False    # trop vieux


# ============================ V8 — module mesuré FEED la décision (mention != porte) ============================

def test_v8_les_gardes_branches_ne_sont_plus_teste_seulement():
    manifest = json.loads((ROOT / "tools" / "audit_cablage_manifest.json").read_text(encoding="utf-8"))
    teste_seulement = {Path(p).stem for p in manifest["neufs"]["TESTE_SEULEMENT"]}
    for garde in ("universe_guard", "session_conditioning", "freshness_cut",
                  "structural_wallet_filter", "tick_quality_guard", "margin_reserve",
                  "crowding", "drawdown_scaling"):
        assert garde not in teste_seulement, f"{garde} branché mais encore testé-seulement ?"


# ============================ V10 — pas de lookahead résiduel (fenêtre CAUSALE) ============================

def test_v10_zscore_est_causal_le_futur_ne_change_pas_le_passe():
    base = [1.0, 2.0, 3.0, 2.5, 4.0]
    z_base = zscore_roulant(base, fenetre=20)
    modifie = list(base)
    modifie[-1] = 999.0                            # on change UNIQUEMENT le dernier point (le futur)
    z_mod = zscore_roulant(modifie, fenetre=20)
    # les z-scores AVANT le point modifié doivent être identiques (aucune fuite du futur)
    assert z_base[:-1] == z_mod[:-1]


# ============================ V11 — les tests VÉRIFIENT (discrimination, pas exécution vide) ============================

def test_v11_le_garde_DISCRIMINE_bon_vs_mauvais_input():
    cfg = V12DecisionPipelineConfig()
    from types import SimpleNamespace
    edge = __import__("hl_observer.edge.edge_net_v12", fromlist=["EdgeNetV12Estimate"]).EdgeNetV12Estimate(
        measurable=True, accepted=True, gross_edge_bps=50.0, total_cost_bps=0.0,
        net_edge_bps=50.0, threshold_bps=30.0)
    delta = SimpleNamespace(is_exit_or_reduce=False, coin="BTC", reason_codes=(), delta_id="d")
    propre = SimpleNamespace(market_mids={"BTC": 100.0, "ETH": 50.0}, observed_at_ms=10_000_000,
                             source_ts_ms=10_000_000 - 5_000, wallet="0x", reference_mids={},
                             edge_history_by_coin={}, wallet_stats=None)
    sale = SimpleNamespace(market_mids={"BTC": 100.0, "ETH": 50.0}, observed_at_ms=10_000_000,
                           source_ts_ms=10_000_000 - 600_000, wallet="0x", reference_mids={},
                           edge_history_by_coin={}, wallet_stats=None)  # signal périmé
    etat = {"capital": None, "marge_utilisee": None, "drawdown_frac": 0.0}
    out_ok, _ = _appliquer_gardes(edge, delta, 100.0, propre, cfg, etat)
    out_ko, _ = _appliquer_gardes(edge, delta, 100.0, sale, cfg, etat)
    # discrimination réelle : bon input -> edge intact ; mauvais input -> edge dégradé. Une mutation
    # qui neutraliserait le garde ferait échouer CET écart.
    assert out_ok is edge
    assert out_ko is not edge and out_ko.accepted is False


# ============================ V12 — la vérité complète = Windows (méta, documenté) ============================

def test_v12_sandbox_sans_reseau_documente():
    # Marqueur explicite : le sandbox ne peut PAS être la vérité complète (ni réseau ni UTF-8 fiable).
    # La suite complète tourne sous Windows via le lanceur unique (`LANCER_HYPERSMART.cmd audit`,
    # qui absorbe l'ancien TEST-AUDIT-complet.cmd). Ce test documente la limite.
    assert (ROOT / "LANCER_HYPERSMART.cmd").exists()
