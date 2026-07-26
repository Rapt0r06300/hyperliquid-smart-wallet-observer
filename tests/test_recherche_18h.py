"""Tests du labo 18 h (sous-ensemble RÉEL des acceptations). Sécurité, durée/phases, resume idempotent,
catalogue (dupes/troncature), parité replay, futur rejeté, fast-screen ne promeut pas, direction opposée
REJOUÉE, purge, registre (préreg/résultat/retry/superseded), DSR tous essais, gate, ROI, watch."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import config_18h as CFG            # noqa: E402
import securite_18h as SEC          # noqa: E402
import catalogue_archives_18h as CAT  # noqa: E402
import validation_18h as V18        # noqa: E402
import recherche_18h_mecanismes as MEC  # noqa: E402
import replay_18h as RPL            # noqa: E402
import registre_18h as REG          # noqa: E402
import recherche_18h as ORCH        # noqa: E402
import rapport_18h as RAP           # noqa: E402


# ── sécurité ──
def test_zero_execution_reelle_dans_le_code_18h():
    # strict sur la CHAÎNE 18 h (mes fichiers) : 0 signature/clé/ordre/écriture réseau/seed
    root = Path(__file__).resolve().parents[1]
    findings = []
    for nom in ("config_18h", "securite_18h", "catalogue_archives_18h", "validation_18h",
                "recherche_18h_mecanismes", "replay_18h", "registre_18h", "recherche_18h", "rapport_18h"):
        findings += SEC.scanner_fichier(root / "tools" / (nom + ".py"))
    dangereux = [f for f in findings if f["categorie"] in ("SIGNATURE", "CLE_PRIVEE", "ORDRE", "APPEL_RESEAU_ECRITURE", "SEED")]
    assert dangereux == [], dangereux


def test_audit_chaine_18h_securise_pour_dry_run():
    # l'audit de la CHAÎNE réellement exécutée (18h + moteur réutilisé) ne signale AUCUN vrai appel dangereux
    root = Path(__file__).resolve().parents[1]
    a = SEC.auditer(root)
    assert a["securise"] is True, a["findings"][:10]


def test_config_limites_prudentes(tmp_path):
    lim = CFG.limites(str(tmp_path))
    assert set(("MAX_CPU_PERCENT", "MAX_RAM_GB", "MAX_WORKERS", "MIN_FREE_DISK_GB")) <= set(lim)
    assert lim["MAX_WORKERS"] >= 1 and lim["MAX_CPU_PERCENT"] <= 100


# ── durée / phases ──
def test_18h_duree_et_frontieres():
    assert ORCH.DUREE_TOTALE_S == 18 * 3600
    assert ORCH.phase_courante(0) == "PREFLIGHT"
    assert ORCH.phase_courante(3 * 3600) == "DISCOVERY"
    assert ORCH.phase_courante(6.5 * 3600) == "DEDUP_FREEZE"
    assert ORCH.phase_courante(9 * 3600) == "VALIDATION"
    assert ORCH.phase_courante(11.5 * 3600) == "AUDIT"
    assert ORCH.phase_courante(15 * 3600) == "HOLDOUT_FORWARD"
    assert ORCH.phase_courante(17.5 * 3600) == "FINALIZE"
    assert ORCH.phase_courante(18 * 3600) == "TERMINE"


def test_status_montre_elapsed_et_restant(tmp_path, monkeypatch):
    monkeypatch.setattr(ORCH, "RACINE", tmp_path)
    ident = {"run_id": "r18h-x", "t0_wall_ms": (__import__("time").time() - 3600) * 1000,
             "fin_prevue_wall_ms": 0, "rundir": str(tmp_path / "rd")}
    (tmp_path / ORCH.RUN_ROOT_REL).mkdir(parents=True)
    ORCH._active_path(tmp_path).write_text(json.dumps(ident))
    st = ORCH.statut(tmp_path)
    assert st["actif"] and st["elapsed_h"] >= 0.9 and st["reste_h"] <= 17.2


# ── catalogue ──
def test_catalogue_detecte_doublons_et_troncature(tmp_path):
    d = tmp_path / "runtime" / "data"
    d.mkdir(parents=True)
    # 2 lignes identiques (doublon) + pas de \n final (troncature)
    (d / "bbo.jsonl").write_text('{"coin":"BTC","ts_ms":1,"bid":100,"ask":101}\n'
                                 '{"coin":"BTC","ts_ms":1,"bid":100,"ask":101}')
    q = CAT.analyser_jsonl(d / "bbo.jsonl")
    assert q["doublons"] >= 1 and q["troncature"] is True
    resume = CAT.cataloguer(tmp_path, tmp_path / "rd", dossiers=("runtime/data",))
    assert resume["n_sources"] == 1


def test_catalogue_detecte_crossed_book(tmp_path):
    d = tmp_path / "runtime" / "data"
    d.mkdir(parents=True)
    (d / "x.jsonl").write_text('{"coin":"BTC","ts_ms":1,"bid":102,"ask":101}\n')  # bid>ask = croisé
    q = CAT.analyser_jsonl(d / "x.jsonl")
    assert q["crossed_book"] >= 1


# ── partitions / purge ──
def test_partitions_scellees_et_purge(tmp_path):
    split = V18.partitions_temporelles(0.0, 1_000_000.0, horizon_max_ms=10_000.0)
    # embargo autour des frontières -> un ts en zone d'embargo n'appartient à AUCUNE partition
    assert V18.partition_de(0.0, split) == "discovery"
    assert V18.partition_de(999_999.0, split) == "holdout"
    frontiere = split["discovery"][1] + 1  # juste après discovery, dans embargo_1
    assert V18.partition_de(frontiere, split) is None
    info = V18.sceller_split(tmp_path, split)
    assert (tmp_path / "partitions" / "DATA_SPLIT_MANIFEST.json").exists()
    assert len(info["sha256"]) == 64


# ── fast-screen / exact ──
def test_fast_screen_ne_peut_pas_promouvoir():
    r = MEC.fast_screen([{"gross_bps": 50.0} for _ in range(40)])
    assert r["peut_promouvoir"] is False
    assert set(("APPROXIMATE_ONLY", "NOT_VALIDATED", "NOT_ELIGIBLE_FOR_FORWARD")) <= set(r["drapeaux"])


def test_maker_risk_averse_plus_prudent_que_proba():
    ra = MEC.maker_risk_averse_fill(queue_devant_sz=100, volume_traversant_sz=60)   # flux < file -> 0
    pr = MEC.maker_probabiliste_fill(queue_devant_sz=100, volume_traversant_sz=60)  # proba > 0
    assert ra == 0.0 and pr > 0.0


# ── replay A/B / parité / direction ──
def test_parite_decision_hash():
    live = [{"coin": "BTC", "ts_ms": 1, "sens": 1, "action": "OPEN", "prix": 100.0}]
    assert RPL.parite(live, list(live))["parite"] is True
    diff = [{"coin": "BTC", "ts_ms": 1, "sens": -1, "action": "OPEN", "prix": 100.0}]
    p = RPL.parite(live, diff)
    assert p["parite"] is False and p["premier_divergent"] == 0


def test_direction_opposee_est_rejouee_pas_negation():
    # long gagne (prix monte) ; le short REJOUÉ perd VRAIMENT (recalcul par prix), pas -net
    eps = [{"entry_px": 100.0, "exit_px": 101.0, "size_usd": 100.0, "fee_bps": 2.0, "slippage_bps": 1.0}]
    ab = RPL.direction_ab(eps)
    lg = ab["continuation"]["net_median_bps"]
    sh = ab["reversion"]["net_median_bps"]
    # les deux paient les coûts -> sh != -lg (sinon ce serait une simple négation)
    assert lg is not None and sh is not None and abs(sh - (-lg)) > 1e-6


# ── registre ──
def test_registre_prereg_resultat_retry_superseded(tmp_path):
    e = REG.preenregistrer(tmp_path, {"family": "OFI", "variant": "top5", "params": {"h": 1000}})
    tid = e["trial_id"]
    # retry technique : même params -> MÊME trial_id
    e2 = REG.preenregistrer(tmp_path, {"family": "OFI", "variant": "top5", "params": {"h": 1000}})
    assert e2["trial_id"] == tid
    # résultat SANS préreg -> refusé
    import pytest
    with pytest.raises(ValueError):
        REG.enregistrer_resultat(tmp_path, "t-inconnu", {"sharpe": 0.1})
    REG.enregistrer_resultat(tmp_path, tid, {"sharpe": -0.3, "net_median_bps": -8, "pf": 0.5, "verdict": "KILL"})
    # correction -> nouveau trial_id + supersedes
    nv = REG.superseder(tmp_path, tid, {"family": "OFI", "variant": "top5b", "params": {"h": 1000, "fix": 1}})
    assert nv["trial_id"] != tid
    c = REG.compter(tmp_path)
    assert c["resultats"] == 1 and c["superseded"] == 1
    assert REG.sharpes_tous_resultats(tmp_path) == [-0.3]   # DSR reçoit TOUS les résultats (KILL compris)


# ── validation / gate ──
def test_walk_forward_purge_embargo():
    import random
    rng = random.Random(0)
    eps = [{"ts_ms": i * 1000, "net_bps": rng.gauss(-10, 2)} for i in range(200)]
    wf = V18.walk_forward(eps, k=4, embargo_ms=1000.0)                              # embargo court vs pas de 1 s
    assert wf["oos_net_median_bps"] is not None and wf["oos_net_median_bps"] < 0   # bruit négatif -> OOS négatif


def test_gate_research_only_si_holdout_non_vu():
    cand = {"n": 100, "net_median_oos_bps": 5.0, "net_moyen_oos_bps": 4.0, "holdout_vu": False}
    assert V18.gate(cand)["verdict"] == "RESEARCH_ONLY"


def test_gate_kill_si_net_negatif():
    cand = {"n": 100, "net_median_oos_bps": -8.0, "net_moyen_oos_bps": -7.0, "holdout_vu": True,
            "pf_oos": 0.4, "dsr": 0.1, "pbo": 0.9}
    assert V18.gate(cand)["verdict"] == "KILL"


def test_gate_pass_si_tout_vert():
    cand = {"n": 100, "net_median_oos_bps": 6.0, "net_moyen_oos_bps": 5.0, "holdout_vu": True,
            "pf_oos": 1.5, "dsr": 0.97, "pbo": 0.1, "ic_bas_bps": 1.0, "placebo_median_bps": 0.0,
            "stress_survit": True, "plateau": True, "un_seul_coin_dominant": False, "drawdown_borne": True,
            "capacite_non_nulle": True, "ledger_reconcilie": True, "securite_verte": True}
    assert V18.gate(cand)["verdict"] == "PASS_FORWARD_PAPER"


def test_cout_break_even():
    be = V18.cout_break_even(gross_bps=15.0, cout_bps=12.0)
    assert be["marge_bps"] == 3.0 and be["survit"] is True


# ── orchestrateur : dry-run + start + resume idempotent ──
def test_dry_run_pass_et_securise(tmp_path, monkeypatch):
    monkeypatch.setattr(ORCH, "RACINE", tmp_path)
    (tmp_path / "src").mkdir()
    (tmp_path / "tools").mkdir()
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    dr = ORCH.dry_run(tmp_path)
    assert dr["securite"]["securise"] is True
    assert "phases_18h" in dr and len(dr["phases_18h"]) == 7
    assert dr["securite_ligne"].startswith("0 ordre reel")


def test_start_cree_run_sous_overnight_18h_et_resume_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(ORCH, "RACINE", tmp_path)
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    r = ORCH.demarrer(tmp_path)
    assert r["start"] == "OK" and r["run_id"].startswith("r18h-")
    assert "overnight_18h" in r["rundir"]
    # un 2e start ne crée PAS de doublon
    r2 = ORCH.demarrer(tmp_path)
    assert r2["start"] == "DEJA_ACTIF"
    # resume idempotent, même run_id
    assert ORCH.reprendre(tmp_path)["run_id"] == r["run_id"]


def test_preservation_14h_intacte():
    # le 14h ne doit pas être référencé/écrasé par le 18h
    root = Path(__file__).resolve().parents[1]
    assert (root / "LANCER-RECHERCHE-14H.cmd").exists()
    assert (root / "tools" / "recherche_14h.py").exists()
    txt = (root / "tools" / "recherche_18h.py").read_text(encoding="utf-8")
    assert "overnight_18h" in txt and "overnight_14h" not in txt


def test_finalize_ecrit_rapport_et_manifeste(tmp_path, monkeypatch):
    monkeypatch.setattr(ORCH, "RACINE", tmp_path)
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    ORCH.demarrer(tmp_path)
    fin = ORCH.finaliser(tmp_path)
    assert fin["finalisation"] == "OK"
    assert (tmp_path / "RAPPORT-RECHERCHE-18H.md").exists()
    rd = tmp_path / ORCH.RUN_ROOT_REL
    manifs = list(rd.rglob("SHA256_MANIFEST_FINAL.json"))
    assert manifs and "code_sha" in json.loads(manifs[0].read_text())
