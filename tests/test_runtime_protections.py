"""Protections IDEA portées du legacy vers le runtime canonique.

Deux exigences : chaque garde fonctionne **depuis `src/hl_observer`** (donc depuis le runtime officiel), et
son comportement reste **équivalent** à l'ancêtre `tools/` — sinon on aurait deux vérités qui divergent en
silence, ce qui est pire qu'un seul module mal placé.

Paper only : 0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.runtime import protections as P  # noqa: E402


# ═══════════════ IDEA-9 : dédup qui survit au crash ═══════════════
def test_la_dedup_survit_au_redemarrage(tmp_path):
    d1 = P.DedupDurable(tmp_path / "dedup")
    assert d1.vu("e1") is False
    d1.marquer("e1")
    d2 = P.DedupDurable(tmp_path / "dedup")          # nouveau process : l'etat vient du disque
    assert d2.vu("e1") is True


def test_filtrer_rend_les_doublons_au_lieu_de_les_jeter(tmp_path):
    d = P.DedupDurable(tmp_path / "dedup")
    evs = [{"event_id": "a"}, {"event_id": "b"}, {"event_id": "a"}]
    nouveaux, doublons = d.filtrer(evs)
    assert [e["event_id"] for e in nouveaux] == ["a", "b"]
    assert [e["event_id"] for e in doublons] == ["a"]


def test_un_evenement_sans_identite_nest_pas_declare_doublon(tmp_path):
    d = P.DedupDurable(tmp_path / "dedup")
    nouveaux, doublons = d.filtrer([{"x": 1}, {"x": 1}])
    assert len(nouveaux) == 2 and doublons == []      # sans identite, on ne peut rien affirmer


# ═══════════════ IDEA-10 : une panne laisse une trace ═══════════════
def test_les_incidents_bloquants_interdisent_la_promotion(tmp_path):
    j = P.JournalIncidents(tmp_path / "operational")
    j.enregistrer("WS_GAP", detail="120 ms")
    assert j.resume()["promotion_interdite"] is False
    j.enregistrer("DATA_MISSING", detail="scanner casse")
    r = j.resume()
    assert r["promotion_interdite"] is True and r["par_type"]["DATA_MISSING"] == 1


# ═══════════════ IDEA-36 : ledger corrompu ═══════════════
def test_chaque_ligne_invalide_est_localisee(tmp_path):
    f = tmp_path / "ledger.jsonl"
    f.write_text('{"ok":1}\nPAS DU JSON\n{"ok":2}\n[1,2]\n', encoding="utf-8")
    r = P.scanner_ledger(f)
    assert r["statut"] == "CORROMPU" and r["n_erreurs"] == 2
    assert [e["ligne"] for e in r["erreurs"]] == [2, 4]
    assert r["promotion_autorisee"] is False


def test_un_ledger_absent_nest_pas_une_corruption(tmp_path):
    r = P.scanner_ledger(tmp_path / "rien.jsonl")
    assert r["statut"] == "ABSENT" and r["promotion_autorisee"] is True


# ═══════════════ IDEA-71 : une source externe ne crée jamais un signal ═══════════════
def test_le_sanity_cross_source_nautorise_jamais_un_signal():
    coherent = P.sanity_cross_source({"hl": 100.0, "bin": 100.02})
    divergent = P.sanity_cross_source({"hl": 100.0, "bin": 130.0})
    assert coherent["coherent"] is True and divergent["coherent"] is False
    for r in (coherent, divergent):
        assert r["signal_autorise"] is False          # TOUJOURS, quelle que soit la coherence


def test_une_seule_source_nest_pas_comparable():
    r = P.sanity_cross_source({"hl": 100.0})
    assert r["statut"] == "NON_COMPARABLE" and r["coherent"] is None


# ═══════════════ IDEA-78 : manifeste ═══════════════
def test_hors_depot_git_letat_est_inconnu_et_non_reproductible(tmp_path):
    m = P.manifeste_execution(tmp_path)
    assert m["git_dirty"] is None and m["reproductible"] is False
    assert "INCONNU" in m["avertissement"]


def test_le_manifeste_porte_le_contexte_fourni(tmp_path):
    m = P.manifeste_execution(tmp_path, campagne="alpha5", fees_bps=4.5)
    assert m["contexte"]["campagne"] == "alpha5" and m["real_execution"] is False


# ═══════════════ IDEA-79 : panne ≠ marché calme ═══════════════
def test_une_panne_de_collecte_nest_pas_un_marche_calme():
    panne = P.etat_ingestion(n_nouveaux_evenements=0, erreur_scanner="curseur casse")
    calme = P.etat_ingestion(n_nouveaux_evenements=0)
    assert panne["sante"] == "ROUGE" and panne["promotion_autorisee"] is False
    assert calme["sante"] == "VERTE" and calme["promotion_autorisee"] is True


def test_un_compte_inconnu_est_rouge_pas_vert():
    r = P.etat_ingestion(n_nouveaux_evenements=None)
    assert r["sante"] == "ROUGE" and r["promotion_autorisee"] is False


# ═══════════════ IDEA-80 : verrou synthétique ═══════════════
def test_une_donnee_synthetique_ne_promeut_jamais():
    v = P.verrou_synthetique({"data_origin": "SYNTHETIC", "verdict": "PASS_FORWARD_PAPER"})
    assert v["violation"] is True and v["verdict_corrige"] == "SHADOW_SYNTHETIQUE"


def test_une_donnee_reelle_qui_promeut_nest_pas_une_violation():
    v = P.verrou_synthetique({"data_origin": "REAL", "verdict": "PASS_FORWARD_PAPER"})
    assert v["violation"] is False and v["verdict_corrige"] == "PASS_FORWARD_PAPER"


def test_du_synthetique_en_shadow_est_legitime():
    v = P.verrou_synthetique({"data_origin": "SYNTHETIC", "verdict": "SHADOW"})
    assert v["violation"] is False


# ═══════════════ la couture ═══════════════
def test_le_verrou_global_bloque_sur_ledger_corrompu(tmp_path):
    (tmp_path / "ledger.jsonl").write_text('{"a":1}\nCASSE\n', encoding="utf-8")
    r = P.controler_avant_promotion(tmp_path)
    assert r["promotion_autorisee"] is False and "LEDGER_CORROMPU" in r["raisons"]


def test_le_verrou_global_bloque_sur_incident_et_sur_synthetique(tmp_path):
    P.JournalIncidents(tmp_path / "operational").enregistrer("PNL_UNTRUSTED", detail="divergence")
    r = P.controler_avant_promotion(
        tmp_path, verdicts=[{"data_origin": "SYNTHETIC", "verdict": "PASS_FORWARD_PAPER"}])
    assert r["promotion_autorisee"] is False
    assert "INCIDENT_BLOQUANT" in r["raisons"] and "PROMOTION_SUR_DONNEE_SYNTHETIQUE" in r["raisons"]


def test_un_run_sain_autorise_la_promotion(tmp_path):
    (tmp_path / "ledger.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    r = P.controler_avant_promotion(tmp_path, verdicts=[{"data_origin": "REAL", "verdict": "PASS"}])
    assert r["promotion_autorisee"] is True and r["raisons"] == []


# ═══════════════ équivalence avec l'ancêtre legacy ═══════════════
def test_equivalence_avec_le_legacy_ingestion_et_synthetique():
    """Si canonique et legacy divergent un jour, ce test tombe — deux verites valent moins qu'une."""
    legacy = pytest.importorskip("garde_fous_recherche")
    for kwargs in ({"n_nouveaux_evenements": 0}, {"n_nouveaux_evenements": None},
                   {"n_nouveaux_evenements": 0, "erreur_scanner": "boom"},
                   {"n_nouveaux_evenements": 12}):
        a = P.etat_ingestion(**kwargs)
        b = legacy.etat_ingestion(**kwargs)
        assert (a["sante"], a["promotion_autorisee"]) == (b["sante"], b["promotion_autorisee"])
    for verdict in ({"data_origin": "SYNTHETIC", "verdict": "PASS_FORWARD_PAPER"},
                    {"data_origin": "REAL", "verdict": "PASS"},
                    {"data_origin": "SYNTHETIC", "verdict": "SHADOW"}):
        assert P.verrou_synthetique(verdict)["violation"] == legacy.verrou_synthetique(verdict)["violation"]


def test_equivalence_avec_le_legacy_scanner_ledger(tmp_path):
    legacy = pytest.importorskip("pnl_verite")
    f = tmp_path / "l.jsonl"
    f.write_text('{"a":1}\nCASSE\n{"b":2}\n', encoding="utf-8")
    a, b = P.scanner_ledger(f), legacy.scanner_ledger(f)
    assert (a["n_erreurs"], a["promotion_autorisee"]) == (b["n_erreurs"], b["promotion_autorisee"])


def test_securite_aucun_appel_reel():
    src = (RACINE / "src" / "hl_observer" / "runtime" / "protections.py").read_text(encoding="utf-8")
    for interdit in ('"/exchange"', "'/exchange'", "requests.get", "requests.post", "import websocket",
                     "websockets.connect", "eth_account", "Account.from_key", "private_key"):
        assert interdit not in src, "appel interdit dans protections: %s" % interdit
