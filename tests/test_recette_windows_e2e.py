"""[items 11 & 12] Recette Windows DÉTERMINISTE des deux fichiers maîtres, au niveau des ENTRÉES CLI que
les .cmd appellent réellement :

  collecte (heartbeats + artefacts) → session COMPLETE (preuve d'arrêt) → analyser_session.main
  (sélection + checksums + run_id émis) → lab_alpha.main --session-dir (analyse EXCLUSIVE de cette
  session) → rapport NEUF namespacé par run_id, code de sortie 0, ZÉRO donnée d'une autre session.

C'est la preuve, côté code, de ce que Flo vérifiera par les deux double-clics. 0 réseau, 0 ordre.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import analyser_session as AS      # noqa: E402
from hl_observer.ops import lab_alpha as LA             # noqa: E402
from hl_observer.ops import session_catalog as SC       # noqa: E402
from hl_observer.ops import session_harvest as SH       # noqa: E402


def _ecrire_events(p: Path, coin: str, n: int):
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for i in range(n):
            fh.write(json.dumps({"coin": coin, "ts_ms": 1000 + i, "px": 100.0 + i, "mid": 100.0 + i,
                                 "signe": 1 if i % 2 == 0 else -1, "sz": 0.3}) + "\n")


def _session_complete(root, run_id, *, coin, n, debut):
    dossier = SC.chemin_session(root, run_id)
    _ecrire_events(dossier / "hl" / "allmids.jsonl", coin, n)
    c = SC.CatalogueSession(root, run_id)
    c.demarrer(git_head="cafe1234", horloge=lambda: float(debut))
    c.enregistrer_source(SC.EntreeSource("allmids-collector", "HYPERLIQUID", "allMids",
                                         chemin="hl/allmids.jsonl"))
    v = c.cloturer(writers_arretes=True, horloge=lambda: float(debut + 1))
    assert v["statut"] == SC.STATUT_COMPLETE
    return dossier


def test_recette_complete_deux_fichiers_maitres(tmp_path, capsys):
    # 1) DEUX sessions COMPLETE : une ancienne (autre coin) + la récente (celle à analyser).
    _session_complete(tmp_path, "run-ancienne", coin="ZZZ", n=8, debut=1000)
    _session_complete(tmp_path, "run-recente", coin="BTC", n=24, debut=9000)

    # 2) PORTE ANALYSER (ce que fait le .cmd) : sélection + checksums + émission du run_id.
    code_sel = AS.main(["--root", str(tmp_path), "--emit-run-id"])
    out = capsys.readouterr().out
    assert code_sel == 0 and "verdict=GO" in out
    sel = tmp_path / "runtime" / "reports" / "backtest_replay" / "SESSION_SELECTIONNEE.txt"
    run_id = sel.read_text(encoding="utf-8").strip()
    assert run_id == "run-recente"                          # la COMPLETE la plus récente, pas l'ancienne

    # 3) LAB scopé à CETTE session (ce que fait le .cmd avec --session-dir).
    session_dir = SC.chemin_session(tmp_path, run_id)
    code_lab = LA.main(["--root", str(tmp_path), "--session-dir", str(session_dir),
                        "--budget", "1", "--source", "REEL", "--max-ram-events", "0"])
    assert code_lab == 0                                     # code de sortie 0 (run réussi)

    # 4) RAPPORT NEUF namespacé par run_id + manifeste (run_id + hash + SHA git).
    ns = tmp_path / "runtime" / "reports" / "backtest_replay" / run_id
    assert (ns / "RAPPORT_LATEST.md").is_file()
    manifeste = json.loads((ns / "manifeste_run.json").read_text(encoding="utf-8"))
    assert manifeste["run_id"] == "run-recente" and manifeste["git_head"] == "cafe1234"
    # 5) ZÉRO donnée d'une autre session : le shard ne contient que les 24 events de run-recente.
    shard = next(ns.glob("events_shard.*.jsonl"))
    n_shard = sum(1 for _ in shard.open(encoding="utf-8"))
    assert n_shard == 24


def test_recette_analyser_refuse_si_aucune_complete(tmp_path, capsys):
    # une session ACTIVE seule -> la porte ANALYSER refuse (NO_GO, code 2) : rien n'est analysé.
    SC.CatalogueSession(tmp_path, "run-active").demarrer()
    assert AS.main(["--root", str(tmp_path), "--emit-run-id"]) == 2
    assert "NO_GO" in capsys.readouterr().out
    assert not (tmp_path / "runtime" / "reports" / "backtest_replay" / "SESSION_SELECTIONNEE.txt").exists()
