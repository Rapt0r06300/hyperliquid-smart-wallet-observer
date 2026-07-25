"""LOT 0 — RESEARCH_PARALLEL_V1 : isolation, crash, rollback prouvés sans réseau (Flo 25/07).

Prouve : (1) démarrage crée une arbo ISOLÉE (rien dans runtime/data) + identité run_id/config_hash/pid ;
(2) un plugin qui CRASHE est isolé (CRASH_ISOLE), les autres continuent, le superviseur vit ; (3) ledger
append-only tamponné provenance+checksum ; (4) archiveur DÉPLACE (jamais supprime) ; (5) rollback mou via
DISABLED ; (6) plafond 12 variantes ; (7) le labo n'écrit JAMAIS dans runtime/data (main intact).
"""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.research_parallel import isolation as ISO
from hl_observer.research_parallel import registre as REG
from hl_observer.research_parallel import superviseur as SUP


def _plugin(pid, fn, variantes=("v1",)):
    return REG.Plugin(id=pid, categorie="signal", variantes=variantes, tick=fn)


def test_demarrage_cree_arbo_isolee_et_identite(tmp_path):
    ident = SUP.demarrer(tmp_path, plugins=[_plugin("P", lambda c: [])])
    base = tmp_path / "runtime" / "research_lab"
    for d in ("data", "ledgers", "positions", "rapports", "logs", "archives"):
        assert (base / d).is_dir()
    assert ident["run_id"].startswith("lab-") and len(ident["config_hash"]) == 16
    assert (base / "run_identity.json").exists()
    # ISOLATION : runtime/data (main) n'existe PAS créé par le labo
    assert not (tmp_path / "runtime" / "data").exists()


def test_crash_d_un_plugin_est_isole_les_autres_continuent(tmp_path):
    def _sain(c):
        return [{"sig": 1}]
    def _casse(c):
        raise RuntimeError("boom labo")
    ident = SUP.demarrer(tmp_path, plugins=[_plugin("SAIN", _sain), _plugin("CASSE", _casse)])
    res = SUP.tick_tous(tmp_path, ident, {}, plugins=[_plugin("SAIN", _sain), _plugin("CASSE", _casse)])
    assert res["SAIN"]["statut"] == "OK" and res["SAIN"]["n"] == 1
    assert res["CASSE"]["statut"] == "CRASH_ISOLE" and "boom" in res["CASSE"]["erreur"]
    # l'erreur est journalisée dans le labo, le superviseur a battu le cœur (il vit)
    assert (tmp_path / "runtime" / "research_lab" / "logs" / "erreurs.jsonl").exists()
    assert (tmp_path / "runtime" / "research_lab" / "heartbeat.json").exists()


def test_ledger_append_only_provenance_checksum(tmp_path):
    ident = SUP.demarrer(tmp_path, plugins=[_plugin("P", lambda c: [])])
    ISO.ajouter_ledger(tmp_path, "P", [{"a": 1}], ident)
    ISO.ajouter_ledger(tmp_path, "P", [{"a": 2}], ident)          # append, pas d'écrasement
    lignes = [json.loads(l) for l in (tmp_path / "runtime" / "research_lab" / "ledgers" / "P.jsonl")
              .read_text(encoding="utf-8").splitlines()]
    assert len(lignes) == 2 and [l["a"] for l in lignes] == [1, 2]
    assert all(l["real_execution"] is False and l["run_id"] == ident["run_id"] for l in lignes)
    assert all(len(l["checksum"]) == 12 and "recu_mono_ns" in l for l in lignes)


def test_archiveur_deplace_jamais_supprime(tmp_path):
    base = ISO.preparer(tmp_path)
    p = base / "data" / "flux.jsonl"
    p.write_text("x\n" * 40000, encoding="utf-8")                 # > seuil
    for _ in range(3):
        p.write_text("y" * 60000 + "\n", encoding="utf-8")
        ISO.archiver_si_gros(tmp_path, "flux", seuil_octets=40000, max_travail=1)
    travail = list((base / "data").glob("flux_*.jsonl.gz"))
    archive = list((base / "archives").glob("flux_*.jsonl.gz"))
    assert len(travail) == 1 and len(archive) == 2, "set de travail borné, le reste ARCHIVÉ (rien perdu)"


def test_rollback_mou_via_DISABLED(tmp_path):
    ISO.preparer(tmp_path)
    (tmp_path / SUP.DISABLED_REL).write_text("stop", encoding="utf-8")
    assert SUP.est_desactive(tmp_path) is True
    assert SUP.demarrer(tmp_path, plugins=[])["desactive"] is True
    # boucle sort proprement immédiatement
    r = SUP.boucle(tmp_path, plugins=[], max_ticks=5)
    assert r["desactive"] is True


def test_boucle_tourne_puis_s_arrete_sur_DISABLED(tmp_path):
    calls = {"n": 0}
    def _tick(c):
        calls["n"] += 1
        return [{"ok": 1}]
    # 2 ticks puis on active DISABLED entre les ticks via contexte_fn
    def _ctx(root):
        if calls["n"] >= 2:
            (Path(root) / SUP.DISABLED_REL).write_text("stop", encoding="utf-8")
        return {}
    r = SUP.boucle(tmp_path, poll_s=0.0, contexte_fn=_ctx, plugins=[_plugin("P", _tick)], max_ticks=50)
    assert r.get("arret_propre") is True and r["ticks"] >= 2


def test_plafond_12_variantes(tmp_path):
    REG.reset_pour_tests()
    try:
        REG.enregistrer(_plugin("A", lambda c: [], variantes=tuple("abcdefgh")))   # 8
        REG.enregistrer(_plugin("B", lambda c: [], variantes=("i", "j", "k", "l")))  # +4 = 12 (ok)
        assert REG.total_variantes() == 12
        import pytest
        with pytest.raises(ValueError):
            REG.enregistrer(_plugin("C", lambda c: [], variantes=("m",)))           # 13 -> refus
    finally:
        REG.reset_pour_tests()


def test_config_hash_stable_et_sensible(tmp_path):
    h1 = ISO.config_hash(["A", "B"], {"x": 1})
    h2 = ISO.config_hash(["B", "A"], {"x": 1})       # ordre indifférent
    h3 = ISO.config_hash(["A", "B"], {"x": 2})       # param différent -> hash différent
    assert h1 == h2 and h1 != h3 and len(h1) == 16
