"""[ANALYSER items 2 & 4] Le laboratoire, en mode session, n'analyse QUE les artefacts CATALOGUÉS de la
session COMPLETE (aucun scan global de la racine), et NAMESPACE ses sorties par run_id + hash + SHA git.
Un fichier de données NON catalogué (autre session/archive/log) est IGNORÉ. 0 réseau.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import lab_alpha as LA          # noqa: E402
from hl_observer.ops import session_catalog as SC    # noqa: E402


def _ecrire_events(p: Path, coin: str, n: int):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for i in range(n):
            fh.write(json.dumps({"coin": coin, "ts_ms": 1000 + i, "px": 100.0 + i, "mid": 100.0 + i,
                                 "signe": 1 if i % 2 == 0 else -1, "sz": 0.3}) + "\n")


def _session_complete(root, run_id, *, n_catalogue=20):
    dossier = SC.chemin_session(root, run_id)
    # artefact CATALOGUÉ (sera analysé)
    _ecrire_events(dossier / "hl" / "allmids.jsonl", "BTC", n_catalogue)
    # fichier de données NON catalogué dans la session (orphelin d'une autre origine) -> doit être ignoré
    _ecrire_events(dossier / "hl" / "ORPHELIN_autre_session.jsonl", "ZZZ", 999)
    c = SC.CatalogueSession(root, run_id)
    c.demarrer(git_head="deadbeef", horloge=lambda: 1000.0)
    c.enregistrer_source(SC.EntreeSource("allmids-collector", "HYPERLIQUID", "allMids",
                                         chemin="hl/allmids.jsonl"))
    # NB : on ne catalogue PAS l'orphelin -> la cloture le verrait comme orphelin ; ici on teste le SCOPE
    #      d'analyse, donc on retire l'orphelin avant cloture puis on le remet pour le test de scope.
    orph = dossier / "hl" / "ORPHELIN_autre_session.jsonl"
    sauve = orph.read_bytes()
    orph.unlink()
    c.cloturer(writers_arretes=True, horloge=lambda: 1001.0)
    orph.write_bytes(sauve)                                  # remis APRÈS cloture (simule une pollution)
    return dossier


def test_analyse_scopee_a_la_session_ignore_le_reste(tmp_path):
    _session_complete(tmp_path, "run-scope-1", n_catalogue=20)
    # un fichier de données à la RACINE (hors session) qui ne doit JAMAIS entrer dans l'analyse.
    _ecrire_events(tmp_path / "runtime" / "replay" / "vieux.jsonl", "YYY", 500)
    session_dir = SC.chemin_session(tmp_path, "run-scope-1")
    res = LA.lancer_lab(racine=tmp_path, session_dir=session_dir, budget=1, source="REEL",
                        min_episodes=5)
    # seuls les 20 events catalogués sont lus — ni l'orphelin (999) ni le fichier racine (500).
    assert res["events"] == 20, res["events"]
    assert res["inventaire"].get("scope") == "SESSION"
    # sorties NAMESPACÉES par run_id + manifeste (run_id + data_hash + git SHA).
    ns_dir = tmp_path / "runtime" / "reports" / "backtest_replay" / "run-scope-1"
    assert ns_dir.is_dir()
    manifeste = json.loads((ns_dir / "manifeste_run.json").read_text(encoding="utf-8"))
    assert manifeste["run_id"] == "run-scope-1" and manifeste["git_head"] == "deadbeef"
    assert manifeste["data_hash"] and manifeste["real_execution"] is False
    # le shard est nommé avec le hash+SHA (jamais un shard générique réutilisable).
    shards = list(ns_dir.glob("events_shard.*.jsonl"))
    assert shards and manifeste["data_hash"] in shards[0].name


def test_mode_racine_reste_disponible_sans_session(tmp_path):
    # sans session_dir : comportement historique (scan de la racine) — non cassé.
    _ecrire_events(tmp_path / "runtime" / "replay" / "d.jsonl", "BTC", 12)
    res = LA.lancer_lab(racine=tmp_path, budget=1, source="REEL", min_episodes=5)
    assert res["inventaire"].get("scope") != "SESSION"      # scan global (pas de scope session)
