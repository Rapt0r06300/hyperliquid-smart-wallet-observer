"""LOT 11 — orchestrateur 14h + mécanismes HL natifs prouvés sans réseau (Flo 25/07)."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _mod(nom, rel):
    s = importlib.util.spec_from_file_location(nom, _ROOT / rel)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


R = _mod("recherche_14h", "tools/recherche_14h.py")
M = _mod("recherche_14h_mecanismes", "tools/recherche_14h_mecanismes.py")


# ── protocole / phases ──
def test_phases_et_embargos():
    assert R.phase_courante(0) == "A_DECOUVERTE"
    assert R.phase_courante(5.5 * 3600) == "EMBARGO_1"
    assert R.phase_courante(8 * 3600) == "B_VALIDATION"
    assert R.phase_courante(10.5 * 3600) == "EMBARGO_2"
    assert R.phase_courante(12 * 3600) == "C_HOLDOUT"
    assert R.phase_courante(14 * 3600) == "FINI"


def test_exclut_episode_qui_traverse_une_frontiere():
    assert R.traverse_frontiere(4.9 * 3600, 5.1 * 3600) is True     # traverse la fin de A
    assert R.traverse_frontiere(2 * 3600, 3 * 3600) is False        # reste dans A


def test_dix_mecanismes_natifs_figes():
    assert len(R.MECANISMES) == 10 and len(set(R.MECANISMES)) == 10
    assert set(R.MECANISMES) == set(M.DETECTEURS)


def test_criteres_candidat_stricts():
    assert R.CRIT["dsr_min"] == 0.95 and R.CRIT["pbo_max"] == 0.20 and R.CRIT["pf_min"] == 1.2
    assert R.CRIT["min_episodes"] == 30 and R.CRIT["cout_stress_pct"] == 50


# ── isolation / identité ──
def test_status_sans_run(tmp_path):
    assert R.statut(tmp_path) == {"actif": False}


def test_arret_exige_run_id_signe(tmp_path):
    (R._run_root(tmp_path)).mkdir(parents=True)
    (R._run_root(tmp_path) / "ACTIVE.json").write_text(json.dumps({"run_id": "r14h-ABC", "rundir": str(tmp_path)}),
                                                       encoding="utf-8")
    assert R.arreter(tmp_path, "mauvais")["arret"] == "REFUSE"      # run_id non signé -> refus
    assert R.arreter(tmp_path, "r14h-ABC")["arret"] == "OK"         # bon run_id -> arrêt


def test_projection_disque_plancher_2go(tmp_path):
    assert R.projection_disque_octets(tmp_path) >= 2 * 1024**3


def test_dry_run_ne_cree_aucun_run(tmp_path):
    out = R.demarrer(tmp_path, dry_run=True)
    assert out["mode"] == "DRY_RUN" and "PRECHECK" in out
    assert not (R._run_root(tmp_path) / "ACTIVE.json").exists()     # aucun chrono, aucun fichier de run


# ── détecteurs natifs (synthétique) ──
def _l2(coin, ts, bid, ask, bsz, asz):
    return {"coin": coin, "ts_wall_ms": ts, "bids": [[bid, bsz]], "asks": [[ask, asz]]}


def test_ofi_detecte_pression_directionnelle():
    l2 = [_l2("BTC", 0, 100, 100.1, 10, 10), _l2("BTC", 1000, 100, 100.1, 40, 5)]   # bid depth explose
    sig = M._ofi(l2, {}, 1)
    assert sig and sig[0]["sens"] == 1                              # pression acheteuse


def test_microprice_penche():
    # ask_sz >> bid_sz -> microprice proche du bid -> dev < 0 -> sens -1 (pression vendeuse au touch)
    sig = M._queue_microprice([_l2("ETH", 0, 100.0, 100.10, 1, 100)])
    assert sig and sig[0]["sens"] == -1


def test_mesurer_phase_deny_by_default_sur_data_absente(tmp_path):
    R.ISO.preparer(tmp_path)
    res = M.mesurer_phase(tmp_path)                                 # aucune data -> tous n=0, aucun crash
    assert set(res) == set(M.DETECTEURS) and all(v.get("n", 0) == 0 for v in res.values())
