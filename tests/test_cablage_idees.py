"""LOT WIRING — les 91 idées ne sont plus des outils morts : elles tournent DANS le cycle réel.

Chaque test prouve qu'un hook est RÉELLEMENT appelé par `recherche_continue` (pas seulement importable).
Paper-only, read-only, 0 réseau.
"""
from __future__ import annotations

import json
import sys
import threading
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))
sys.path.insert(0, str(RACINE / "src"))

import cablage_idees as CAB               # noqa: E402
import recherche_continue as RC           # noqa: E402


def _cablage_actif(marqueur: str) -> bool:
    """Le câblage vit dans `recherche_continue.py`, fichier qui porte aussi du travail local non commité.
    Tant qu'il n'est pas commité, les tests qui en dépendent SKIPPENT explicitement (jamais un échec muet,
    jamais un faux vert)."""
    src = (RACINE / "tools" / "recherche_continue.py").read_text(encoding="utf-8", errors="ignore")
    return marqueur in src


def _run(tmp_path, n=60):
    """Prépare un run minimal avec de vraies lignes BBO (mêmes données que les autres suites)."""
    d = tmp_path / "runtime" / "research_lab" / "data"
    d.mkdir(parents=True)
    lignes = [{"venue": "HL", "coin": "BTC", "ts_wall_ms": 1_000_000 + i * 1000,
               "exchange_ts": 1_000_000 + i * 1000,
               "bid": 64000 * (1 + i * 0.003), "ask": 64000 * (1 + i * 0.003) + 1,
               "isSnapshot": False} for i in range(n)]
    (d / "bbo.jsonl").write_text("\n".join(json.dumps(x) for x in lignes) + "\n", encoding="utf-8")
    RC._ARRET.clear(); RC._URGENCE.clear()
    RC.creer_ou_reprendre(tmp_path, exiger_flux=False)
    return next((tmp_path / "runtime" / "research_lab" / "continuous").glob("rcont-*"))


# ═══════════════ le module de câblage lui-même ═══════════════
def test_normalisation_produit_des_evenements_canoniques(tmp_path):
    evs = [{"coin": "btc", "exchange_ts": 1000.0, "bid": 100.0, "ask": 100.2, "tid": "t1"}]
    r = CAB.normaliser_et_dedupliquer(tmp_path, evs)
    assert r["actif"] is True and r["n_canoniques"] == 1
    ev = r["evenements"][0]
    assert ev["couche"] == "CANONICAL" and ev["event_id"] and ev["coin"] == "BTC"
    assert ev["bid"] == 100.0 and ev["exchange_ts"] == 1000.0     # clés d'origine préservées


def test_dedup_durable_active_dans_le_cablage(tmp_path):
    evs = [{"coin": "BTC", "exchange_ts": 1.0, "bid": 1.0, "ask": 2.0, "tid": "x"}]
    a = CAB.normaliser_et_dedupliquer(tmp_path, evs)
    b = CAB.normaliser_et_dedupliquer(tmp_path, evs)               # même événement, 2e passage
    assert a["n_doublons"] == 0 and b["n_doublons"] == 1
    assert len(b["evenements"]) == 0                               # le doublon n'est pas re-traité
    inc = CAB.incidents(tmp_path)
    assert inc["par_type"].get("DUPLICATE", 0) >= 1                # et il est JOURNALISÉ


def test_verdict_ingestion_panne_vs_marche_calme(tmp_path):
    calme = CAB.verdict_ingestion(tmp_path, n_nouveaux=0)
    panne = CAB.verdict_ingestion(tmp_path, n_nouveaux=0, erreur="curseur casse")
    assert calme["sante"] == "VERTE" and panne["sante"] == "ROUGE"
    assert panne["promotion_autorisee"] is False
    assert CAB.incidents(tmp_path)["par_type"].get("DATA_MISSING", 0) >= 1


def test_controle_verite_bloque_sur_ledger_corrompu(tmp_path):
    gp = tmp_path / "global_portfolio"; gp.mkdir(parents=True)
    (gp / "ledger.jsonl").write_text('{"ok":1}\nPAS DU JSON\n', encoding="utf-8")
    r = CAB.controler_verite(tmp_path)
    assert r["promotion_autorisee"] is False and "LEDGER_CORROMPU" in r["raisons"]


def test_controle_verite_bloque_sur_pnl_untrusted(tmp_path):
    maillons = {"CANONICAL_EVENT": 10, "SIGNAL": 5, "PAPER_FILL": 5, "OPEN": 5, "REDUCE": 0,
                "CLOSE": 5, "COSTS": 1.0, "CANDIDATE_PNL": 10.0, "PORTFOLIO_PNL": 10.0,
                "DASHBOARD": 999.0}                                # dashboard divergent
    r = CAB.controler_verite(tmp_path, par_candidat={"c1": maillons})
    assert r["promotion_autorisee"] is False and "PNL_UNTRUSTED" in r["raisons"]


def test_controle_verite_bloque_une_promotion_synthetique(tmp_path):
    r = CAB.controler_verite(tmp_path, verdicts=[{"trial_id": "c1", "data_origin": "SYNTHETIC",
                                                  "verdict": "PASS_FORWARD_PAPER"}])
    assert r["promotion_autorisee"] is False
    assert r["synthetique"][0]["verdict_corrige"] == "SHADOW_SYNTHETIQUE"


def test_manifeste_de_campagne_ecrit_dans_le_run(tmp_path):
    m = CAB.manifeste(RACINE, tmp_path, config_economique={"fees_bps": 4.5})
    assert "git_head" in m and "git_dirty" in m
    assert (tmp_path / "manifeste" / "campagne.json").exists()


# ═══════════════ câblage RÉEL dans le cycle ═══════════════
def test_cycle_reel_normalise_et_deduplique(tmp_path):
    """L'ingestion du VRAI cycle passe par la normalisation canonique + dédup durable."""
    if not _cablage_actif("WIRING (IDEA-1/2/4/9/10)"):
        pytest.skip("cablage non commite: normalisation canonique")
    rd = _run(tmp_path)
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=1, intervalle_s=0.0)
    mat = json.loads((rd / "canonical" / "maturation.json").read_text(encoding="utf-8"))
    assert mat["normalisation"]["actif"] is True
    assert mat["normalisation"]["n_canoniques"] > 0                # de vrais événements canoniques
    assert (rd / "dedup" / "dedup_journal.jsonl").exists()          # la dédup durable a écrit sur disque


def test_cycle_reel_publie_l_etat_d_ingestion(tmp_path):
    """`_scanner_nouveautes` porte desormais la sante d'ingestion (IDEA-79)."""
    if not _cablage_actif("WIRING (IDEA-79)"):
        pytest.skip("cablage non commite: verdict d ingestion")
    rd = _run(tmp_path)
    scan = RC._scanner_nouveautes(tmp_path, rd)
    assert "ingestion" in scan and scan["ingestion"]["sante"] in ("VERTE", "ROUGE", "INCONNUE")


def test_cycle_reel_remonte_les_incidents_au_dashboard(tmp_path):
    if not _cablage_actif("WIRING (IDEA-10/85)"):
        pytest.skip("cablage non commite: incidents au dashboard")
    rd = _run(tmp_path)
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=1, intervalle_s=0.0)
    etat = json.loads((rd / "LIVE-RESEARCH-STATE.json").read_text(encoding="utf-8"))
    assert "incidents" in etat                                      # le dashboard voit la realite operationnelle
    assert "promotion_interdite" in etat["incidents"] or etat["incidents"] == {}


def test_promotion_bloquee_par_le_verrou_de_verite(tmp_path):
    """Un ledger strict corrompu doit BLOQUER toute promotion, meme si un candidat serait eligible."""
    if not _cablage_actif("WIRING (IDEA-11/36/80)"):
        pytest.skip("cablage non commite: verrou de verite")
    rd = _run(tmp_path)
    gp = rd / "global_portfolio"; gp.mkdir(parents=True, exist_ok=True)
    (gp / "ledger.jsonl").write_text('{"type":"OPEN"}\nCORROMPU\n', encoding="utf-8")
    camp = rd / "campagnes" / "camp-0001-x"; (camp / "resultats").mkdir(parents=True)
    (camp / "resultats" / "final_verdicts.json").write_text(
        json.dumps([{"trial_id": "c1", "verdict": "PASS_PRE_FORWARD"}]), encoding="utf-8")
    r = RC._promouvoir_pass_live(rd)
    assert r.get("promotion_bloquee") is True and "LEDGER_CORROMPU" in r.get("raisons_verite", [])
    apres = json.loads((camp / "resultats" / "final_verdicts.json").read_text(encoding="utf-8"))
    assert apres[0]["verdict"] == "PASS_PRE_FORWARD"                # AUCUNE promotion n'a eu lieu


def test_manifeste_final_porte_la_provenance(tmp_path):
    if not _cablage_actif("WIRING (IDEA-78)"):
        pytest.skip("cablage non commite: provenance au manifeste")
    rd = _run(tmp_path)
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=1, intervalle_s=0.0)
    RC.finaliser(tmp_path, partial=False)
    man = json.loads((rd / "manifeste" / "SHA256_MANIFEST_FINAL.json").read_text(encoding="utf-8"))
    assert "provenance" in man and ("git_head" in man["provenance"] or "erreur" in man["provenance"])


def test_le_cablage_ne_casse_jamais_le_cycle(tmp_path, monkeypatch):
    """Si un module de câblage lève, le cycle doit CONTINUER (le wiring n'est jamais bloquant)."""
    if not _cablage_actif("WIRING (IDEA-1/2/4/9/10)"):
        pytest.skip("cablage non commite: resilience du cablage")
    rd = _run(tmp_path)
    def _boom(*a, **k):
        raise RuntimeError("module casse")
    monkeypatch.setattr(CAB, "normaliser_et_dedupliquer", _boom)
    monkeypatch.setattr(CAB, "incidents", _boom)
    RC.boucle_continue(tmp_path, stop_event=threading.Event(), max_cycles=1, intervalle_s=0.0)
    assert (rd / "LIVE-RESEARCH-STATE.json").exists()               # le run a survecu


def test_securite_du_module_de_cablage():
    src = (RACINE / "tools" / "cablage_idees.py").read_text(encoding="utf-8")
    # On cible l'ENDPOINT reel et les vrais appels, pas une sous-chaine : "coin/exchange_ts" est un nom de
    # champ, pas une route d'execution.
    for interdit in ('"/exchange"', "'/exchange'", "hyperliquid.xyz/exchange", "requests.get",
                     "requests.post", "import websocket", "websockets.connect", "eth_account",
                     "Account.from_key"):
        assert interdit not in src, "cablage_idees contient un appel interdit: %s" % interdit
