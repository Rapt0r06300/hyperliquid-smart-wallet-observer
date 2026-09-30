"""Le rapport RECHERCHE-14H doit contenir de VRAIS chiffres (plus de stub vide) : tableaux A/B/C par
mécanisme, verdicts KILL/CANDIDAT/DATA_MISSING, section sécurité."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from rapport_14h import construire_rapport  # noqa: E402


def _rundir(tmp_path: Path) -> Path:
    rd = tmp_path / "r14h-test"
    (rd / "ledger").mkdir(parents=True)
    (rd / "resultats").mkdir(parents=True)
    (rd / "run_identity.json").write_text(json.dumps({
        "run_id": "r14h-test", "pid": 1, "t0_wall_ms": 1785025138800, "read_only": True, "real_execution": False,
        "mecanismes": ["OFI_TOP1", "QUEUE_MICROPRICE", "LIQUIDATION_CASCADE_DEPTH"],
        "criteres": {"min_episodes": 30, "pf_min": 1.2, "dsr_min": 0.95, "pbo_max": 0.2, "cout_stress_pct": 50}}))
    (rd / "resultats" / "finalistes.json").write_text(json.dumps({"finalistes": ["OFI_TOP1", "QUEUE_MICROPRICE"]}))
    mesures = [
        {"phase": "A_DECOUVERTE", "elapsed_h": 4.9, "resultats": {
            "OFI_TOP1": {"n": 18208, "net_median_bps": -10.7, "pf": 0.006, "sharpe": -2.3},
            "QUEUE_MICROPRICE": {"n": 612, "net_median_bps": -12.9, "pf": 0.003, "sharpe": -2.4}}},
        {"phase": "B_VALIDATION", "elapsed_h": 9.9, "resultats": {
            "OFI_TOP1": {"n": 1692, "net_median_bps": -10.7, "pf": 0.015, "sharpe": -2.1},
            "QUEUE_MICROPRICE": {"n": 51, "net_median_bps": -12.9, "pf": 0.019, "sharpe": -2.1}}},
        {"phase": "C_HOLDOUT", "elapsed_h": 13.9, "resultats": {
            "OFI_TOP1": {"n": 10512, "net_median_bps": -10.9, "pf": 0.006, "sharpe": -2.4},
            "QUEUE_MICROPRICE": {"n": 398, "net_median_bps": -12.9, "pf": 0.004, "sharpe": -2.5}}}]
    (rd / "ledger" / "trials.jsonl").write_text("\n".join(json.dumps(m) for m in mesures))
    return rd


def test_rapport_contient_de_vrais_chiffres_et_verdicts(tmp_path):
    md = construire_rapport(_rundir(tmp_path))
    assert "généré par le moteur de mesure à H14" not in md, "plus de stub : de vrais chiffres"
    for section in ("C_HOLDOUT", "B_VALIDATION", "A_DÉCOUVERTE", "Verdict global", "Couverture"):
        assert section in md
    assert "-10.9" in md and "0.006" in md, "les net/PF réels figurent dans le tableau"
    assert "KILL" in md, "les mécanismes catastrophiques sont KILL"
    assert "DATA_MISSING" in md and "LIQUIDATION_CASCADE_DEPTH" in md, "un mécanisme sans donnée = DATA_MISSING honnête"
    assert "0 ordre réel" in md, "ligne sécurité présente"
    assert "A=1 · B=1 · C=1" in md and "total 3 essais" in md, "couverture comptée depuis les trials"


def test_candidat_si_pf_et_net_passent(tmp_path):
    rd = _rundir(tmp_path)
    # injecte un mécanisme qui SURVIT (PF>1.2, net>0) au holdout -> doit apparaître CANDIDAT, pas KILL
    mesures = [json.loads(l) for l in (rd / "ledger" / "trials.jsonl").read_text().splitlines()]
    for m in mesures:
        m["resultats"]["OFI_TOP1"] = {"n": 500, "net_median_bps": 6.0, "pf": 1.5, "sharpe": 1.1}
    (rd / "ledger" / "trials.jsonl").write_text("\n".join(json.dumps(m) for m in mesures))
    md = construire_rapport(rd)
    assert "CANDIDAT" in md and "OFI_TOP1" in md
