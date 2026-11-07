"""AlinaSync : rapatriement des fills des lanes GitHub via un `gh` simulé."""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from tools.telecharger_fills_lanes_github import telecharger_et_fusionner


def _cp(rc=0, out="", err=""):
    return SimpleNamespace(returncode=rc, stdout=out, stderr=err)


def _fill(tid, t, obs):
    return {"vault": "0xV", "coin": "BTC", "time": t, "tid": tid, "oid": 100 + tid,
            "px": "1.0", "sz": "1.0", "side": "B", "source": "LIVE_POLL",
            "isSnapshot": False, "observed_at_ms": obs}


def test_telecharge_et_fusionne_via_gh_simule(tmp_path: Path) -> None:
    runs_json = json.dumps([
        {"databaseId": 111, "status": "completed", "conclusion": "success"},
        {"databaseId": 222, "status": "completed", "conclusion": "failure"},   # ignoré
        {"databaseId": 333, "status": "completed", "conclusion": "success"},
    ])

    def gh(args, cwd):
        if args[:1] == ["--version"]:
            return _cp(0, "gh version 2.x")
        if args[:2] == ["run", "list"]:
            return _cp(0, runs_json)
        if args[:2] == ["run", "download"]:
            rid = args[2]
            dest = Path(args[args.index("-D") + 1])
            dest.mkdir(parents=True, exist_ok=True)
            # un artefact de lane = un dossier contenant vault_fills_poll.jsonl
            f = dest / f"poll-fills-shard-0" / "vault_fills_poll.jsonl"
            f.parent.mkdir(parents=True, exist_ok=True)
            tid = 1 if rid == "111" else 2
            f.write_text(json.dumps(_fill(tid, 1000 + tid, 1100 + tid)) + "\n", encoding="utf-8")
            return _cp(0)
        return _cp(1, "", "cmd inconnue")

    res = telecharger_et_fusionner(tmp_path, gh=gh, limite_runs=3)
    assert res["statut"] == "OK"
    assert res["runs"] == 2                         # 111 et 333 (pas le failure 222)
    assert res["fusion"]["total_final"] == 2        # tids 1 et 2 fusionnes
    cible = tmp_path / "runtime" / "data" / "vault_fills_poll.jsonl"
    tids = sorted(json.loads(l)["tid"] for l in cible.read_text(encoding="utf-8").splitlines())
    assert tids == [1, 2]


def test_fail_soft_si_gh_absent(tmp_path: Path) -> None:
    def gh(args, cwd):
        raise FileNotFoundError("gh introuvable")

    res = telecharger_et_fusionner(tmp_path, gh=gh)
    assert res["statut"] == "gh_indisponible"       # non bloquant
    assert res["fusion"] is None
