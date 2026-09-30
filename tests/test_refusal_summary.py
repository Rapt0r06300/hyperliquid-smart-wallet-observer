"""#45 — le résumé des refus dit POURQUOI rien ne s'ouvre, sans rien inventer."""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.ops.refusal_summary import resumer_refus


def _journal(tmp_path, decisions):
    p = Path(tmp_path) / "runtime" / "data"
    p.mkdir(parents=True, exist_ok=True)
    with (p / "carry_hype_paper_decisions.jsonl").open("w", encoding="utf-8") as fh:
        for d in decisions:
            fh.write(json.dumps({"decision": d}) + "\n")


def test_pas_de_journal_reponse_honnete(tmp_path):
    r = resumer_refus(str(tmp_path))
    assert r["n_decisions"] == 0 and "laisse le bot tourner" in r["message"]


def test_top_motif_identifie(tmp_path):
    _journal(tmp_path, [{"viable": False, "motif": "BREAK_EVEN_TROP_LENT"}] * 7
             + [{"viable": False, "motif": "SPOT_ILLIQUIDE"}] * 2
             + [{"viable": True}])
    r = resumer_refus(str(tmp_path))
    assert r["n_decisions"] == 10 and r["n_acceptees"] == 1 and r["n_refusees"] == 9
    assert r["top_motifs"][0][0] == "BREAK_EVEN_TROP_LENT"
    assert "BREAK_EVEN_TROP_LENT" in r["message"]


def test_aucun_refus(tmp_path):
    _journal(tmp_path, [{"viable": True}] * 3)
    r = resumer_refus(str(tmp_path))
    assert r["n_refusees"] == 0 and "aucun refus" in r["message"]
