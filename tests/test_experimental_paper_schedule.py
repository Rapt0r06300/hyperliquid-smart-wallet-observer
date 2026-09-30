"""AUD-045 — experimental-paper : politique de scheduling PINNÉE.

L'audit signalait « flag EXPERIMENTAL_PAPER actif mais worker potentiellement non schedulé ».
La politique réelle, désormais verrouillée : experimental-paper est un worker de profil RESEARCH
(runner réel `tools/experimental_paper_tick.py`), schedulable via `demarrer-tous research` — PAS
dans le socle CORE/harvest (son absence ne bloque jamais READY). Son tick est SELF-GATED par
`HYPERSMART_EXPERIMENTAL_PAPER` : sans le flag, il ne fait rien. Ce test rougit si cette politique
dérive (worker retiré du profil research, promu en core, ou tick qui ne consulte plus le flag).
0 réseau.
"""
from __future__ import annotations

from pathlib import Path

from hl_observer.ops import superviseur_collecteurs as SC

RACINE = Path(__file__).resolve().parents[1]


def test_experimental_paper_a_un_vrai_runner():
    e = next((c for c in SC.REGISTRE if c["nom"] == "experimental-paper"), None)
    assert e is not None, "experimental-paper absent du REGISTRE"
    assert (RACINE / e["script"]).is_file(), e["script"]


def test_experimental_paper_est_research_schedulable_pas_core(monkeypatch):
    assert SC.profil_collecteur("experimental-paper") == "research"
    assert "experimental-paper" not in SC.COLLECTEURS_CORE
    noms_research = {c["nom"] for c in SC.collecteurs_pour_profil("research")}
    assert "experimental-paper" in noms_research
    monkeypatch.delenv("HYPERSMART_EXPERIMENTAL_PAPER", raising=False)
    assert "experimental-paper" not in {c["nom"] for c in SC.collecteurs_pour_profil("harvest")}
    assert "experimental-paper" not in SC.collecteurs_requis_pour_run("harvest")
    monkeypatch.setenv("HYPERSMART_EXPERIMENTAL_PAPER", "1")
    assert "experimental-paper" in {c["nom"] for c in SC.collecteurs_pour_profil("harvest")}
    assert "experimental-paper" in SC.collecteurs_requis_pour_run("harvest")


def test_le_tick_ne_travaille_que_si_le_flag_est_actif():
    src = (RACINE / "tools" / "experimental_paper_tick.py").read_text(encoding="utf-8")
    assert "HYPERSMART_EXPERIMENTAL_PAPER" in src
    assert "experimental-paper.json" in src
    assert 'status="STARTING"' in src and 'status="OK"' in src and 'status="ERROR"' in src
    assert '"real_execution": False' in src


def test_worker_experimental_a_une_cadence_bornee_et_un_heartbeat():
    worker = next(c for c in SC.REGISTRE if c["nom"] == "experimental-paper")
    assert 1 <= int(worker["intervalle_s"]) <= 5
    assert worker["heartbeat"].endswith("experimental-paper.json")
    assert float(worker["limite_minutes"]) <= 2.0
