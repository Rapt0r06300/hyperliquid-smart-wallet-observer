from __future__ import annotations

import sys
from types import SimpleNamespace

from hl_observer.ops import registre_pids as reg


def test_cmd_path_and_belongs_to_root(monkeypatch, tmp_path) -> None:
    assert reg._cmd({"cmd": "abc"}) == "abc"
    assert reg._cmd({"CommandLine": "def"}) == "def"
    assert reg._cmd({}) == ""
    normal = reg._normalise_path_text(tmp_path)
    assert normal
    assert reg._belongs_to_root({"cmd": "anything"}, None) is True
    root = str(tmp_path.resolve())
    assert reg._belongs_to_root({"cmd": f'python "{root}/script.py"'}, tmp_path) is True
    assert reg._belongs_to_root({"cwd": root}, tmp_path) is True
    assert reg._belongs_to_root({"exe": root + "/python.exe"}, tmp_path) is True
    assert reg._belongs_to_root({"cmd": "other"}, tmp_path) is False


def test_pid_signature_and_registry_building(tmp_path) -> None:
    root = str(tmp_path.resolve())
    procs = [
        {"pid": 10, "cmd": f"python {root}/persistent_poll_runner.py"},
        {"pid": 11, "cmd": "persistent_poll_runner other-copy"},
        {"pid": "bad", "cmd": f"{root}/ia_shadow_runner"},
    ]
    assert reg._pid_par_signature(procs, ("persistent_poll_runner",), root=tmp_path) == 10
    assert reg._pid_par_signature(procs, ("missing",), root=tmp_path) is None
    built = reg.construire_registre(
        procs,
        cmd_pid=1,
        run_id="r",
        commit="sha",
        collecteurs={"a": 20, "bad": "x"},
        now_ms=123.9,
        root=tmp_path,
    )
    assert built["ts_ms"] == 123
    assert built["composants"]["cmd"]["pid"] == 1
    assert built["composants"]["poller"]["pid"] == 10
    assert built["collecteurs"] == {"a": 20}
    assert built["run_id"] == "r"


def test_atomic_write_read_and_pid_collection(monkeypatch, tmp_path) -> None:
    target = tmp_path / "nested" / "data.json"
    assert reg._ecrire_atomique(target, '{"x":1}') is True
    assert target.read_text() == '{"x":1}'
    original_replace = reg.os.replace
    monkeypatch.setattr(reg.os, "replace", lambda *args: (_ for _ in ()).throw(OSError("fail")))
    assert reg._ecrire_atomique(tmp_path / "bad.json", "x") is False
    monkeypatch.setattr(reg.os, "replace", original_replace)

    register = {"composants": {"a": {"pid": 1}, "b": {"pid": "x"}, "c": "bad"}, "collecteurs": {"x": 2, "y": "3"}}
    assert reg.pids_enregistres(register) == {1, 2}
    assert reg.ecrire_registre(tmp_path, register) is True
    assert reg.lire_registre(tmp_path) == register
    (tmp_path / reg.REGISTRE_RELPATH).write_text("[]", encoding="utf-8")
    assert reg.lire_registre(tmp_path) == {}
    (tmp_path / reg.REGISTRE_RELPATH).write_text("{", encoding="utf-8")
    assert reg.lire_registre(tmp_path) == {}


def test_orphans_descendants_and_targeted_stop(tmp_path) -> None:
    root = str(tmp_path.resolve())
    procs = [
        {"pid": 1, "ppid": 0, "cmd": f"{root}/LANCER_HYPERSMART.cmd"},
        {"pid": 2, "ppid": 1, "cmd": "child"},
        {"pid": 3, "ppid": 2, "cmd": "grandchild"},
        {"pid": 4, "ppid": 0, "cmd": f"{root}/persistent_poll_runner"},
        {"pid": 5, "ppid": 0, "cmd": "persistent_poll_runner other-copy"},
    ]
    known = {1}
    orphans = reg.detecter_orphelins(procs, known, root=tmp_path)
    assert [row["pid"] for row in orphans] == [4]
    assert reg.cibles_arret({"composants": {"cmd": {"pid": 1}}}, procs) == {1, 2, 3}

    killed = []
    result = reg.arreter(
        tmp_path,
        procs=procs,
        killer=lambda pid: killed.append(pid) or pid != 2,
        registre={"composants": {"cmd": {"pid": 1}}},
    )
    assert result["cibles"] == [1, 2, 3]
    assert result["arretes"] == [1, 3]
    assert killed == [1, 2, 3]
    assert [row["pid"] for row in result["orphelins"]] == [4]

    def raising(pid):
        raise RuntimeError("unit")

    result = reg.arreter(tmp_path, procs=[{"pid": 1, "ppid": 0, "cmd": "x"}], killer=raising, registre={"composants": {"x": {"pid": 1}}})
    assert result["arretes"] == []


def test_processus_reels_success(monkeypatch) -> None:
    fake_processes = [
        SimpleNamespace(info={"pid": 1, "ppid": 0, "name": "p", "cmdline": ["python", "x"], "exe": None, "cwd": None}),
        SimpleNamespace(info={"pid": 2, "ppid": 1, "name": "bad", "cmdline": None, "exe": "e", "cwd": "c"}),
    ]

    class FakePsutil:
        @staticmethod
        def process_iter(fields):
            assert "cmdline" in fields
            return fake_processes

    monkeypatch.setitem(sys.modules, "psutil", FakePsutil)
    out = reg.processus_reels()
    assert out[0]["cmd"] == "python x"
    assert out[0]["exe"] == ""
    assert out[1]["cwd"] == "c"


def test_tuer_reel_psutil_and_os_fallback(monkeypatch) -> None:
    terminated = []

    class Proc:
        def __init__(self, pid):
            self.pid = pid

        def terminate(self):
            terminated.append(self.pid)

    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(Process=Proc))
    assert reg._tuer_reel(7) is True
    assert terminated == [7]

    class BadProc:
        def __init__(self, pid):
            raise RuntimeError("no psutil")

    monkeypatch.setitem(sys.modules, "psutil", SimpleNamespace(Process=BadProc))
    calls = []
    monkeypatch.setattr(reg.os, "kill", lambda pid, sig: calls.append((pid, sig)))
    assert reg._tuer_reel(8) is True
    assert calls == [(8, 15)]
    monkeypatch.setattr(reg.os, "kill", lambda *args: (_ for _ in ()).throw(OSError("no")))
    assert reg._tuer_reel(9) is False


def test_enregistrer_format_and_main(monkeypatch, tmp_path, capsys) -> None:
    import hl_observer.ops.superviseur_collecteurs as superviseur

    root = tmp_path.resolve()
    monkeypatch.setattr(reg, "processus_reels", lambda: [{"pid": 10, "cmd": f"{root}/persistent_poll_runner"}])
    monkeypatch.setattr(superviseur, "_lire_pids", lambda racine: {"pids": {"collector": 20}})
    stored = []
    monkeypatch.setattr(reg, "ecrire_registre", lambda racine, value: stored.append((racine, value)) or True)
    built = reg.enregistrer_depuis_disque(root, cmd_pid=1, run_id="R", commit="C")
    assert built["composants"]["cmd"]["pid"] == 1
    assert built["collecteurs"] == {"collector": 20}
    text = reg.format_registre(built)
    assert "run=R" in text and "collecteurs: 1" in text

    monkeypatch.setattr(reg, "enregistrer_depuis_disque", lambda root, run_id="": {"run_id": run_id, "composants": {}, "collecteurs": {}})
    assert reg.main(["enregistrer", str(root), "RID"]) == 0
    assert "run=RID" in capsys.readouterr().out

    monkeypatch.setattr(reg, "processus_reels", lambda: [])
    monkeypatch.setattr(reg, "arreter", lambda root, procs, killer: {"arretes": [1, 2], "orphelins": [3]})
    assert reg.main(["arreter", str(root)]) == 0
    assert "2 process" in capsys.readouterr().out

    monkeypatch.setattr(reg, "lire_registre", lambda root: {"run_id": "S", "composants": {}, "collecteurs": {}})
    assert reg.main(["status", str(root)]) == 0
    assert "run=S" in capsys.readouterr().out
