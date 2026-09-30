from __future__ import annotations

import json
import os

import pytest

import hl_observer.ops.superviseur_collecteurs as sup


def _collector(name: str = "c1") -> dict:
    return {
        "nom": name,
        "script": f"tools/{name}.py",
        "intervalle_s": 5,
        "args": ["--x", 1],
        "limite_minutes": 2.0,
    }


def test_switch_age_log_and_heartbeat(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv(sup.ENV_INTERRUPTEUR, raising=False)
    assert sup.actif()
    for disabled in ("0", "false", "non", "off"):
        monkeypatch.setenv(sup.ENV_INTERRUPTEUR, disabled)
        assert not sup.actif()
    monkeypatch.setenv(sup.ENV_INTERRUPTEUR, "1")
    assert sup.actif()

    assert sup.age_log_minutes(tmp_path, "missing", maintenant=100.0) is None
    log = tmp_path / "runtime" / "logs" / "c1.log"
    log.parent.mkdir(parents=True)
    log.write_text("x", encoding="utf-8")
    os.utime(log, (40.0, 40.0))
    assert sup.age_log_minutes(tmp_path, "c1", maintenant=100.0) == 1.0

    hb = tmp_path / "runtime" / "data" / "hb.json"
    hb.parent.mkdir(parents=True)
    hb.write_text("{}", encoding="utf-8")
    os.utime(hb, (70.0, 70.0))
    assert sup.age_vie_minutes(
        tmp_path,
        {"nom": "c1", "heartbeat": "runtime/data/hb.json"},
        maintenant=100.0,
    ) == 0.5
    assert sup.age_vie_minutes(
        tmp_path,
        {"nom": "c1", "heartbeat": "runtime/data/missing.json"},
        maintenant=100.0,
    ) == 1.0


def test_collector_state_and_commands(monkeypatch, tmp_path) -> None:
    collectors = [_collector("fresh"), _collector("dead")]
    monkeypatch.setattr(sup, "collecteurs_pour_profil", lambda profile: collectors)
    monkeypatch.setattr(sup, "profil_collecteur", lambda name: "core")
    monkeypatch.setattr(
        sup,
        "age_vie_minutes",
        lambda root, collector, maintenant=None: 1.0 if collector["nom"] == "fresh" else None,
    )
    rows = sup.etat_collecteurs(tmp_path, maintenant=100, profil="core")
    assert rows[0]["mort"] is False
    assert rows[0]["age_minutes"] == 1.0
    assert rows[1]["mort"] is True

    command = sup._commande_relance(_collector("alpha"))
    assert command[:6] == ["cmd", "/c", "start", "", "/b", "tools\\boucle_collecteur.cmd"]
    assert "tools\\alpha.py" in command
    direct = sup.commande_collecteur(_collector("alpha"))
    assert direct[:3] == ["cmd", "/c", "tools\\boucle_collecteur.cmd"]


def test_journal_roundtrip_invalid_and_internal_counter(tmp_path) -> None:
    assert sup._lire_journal(tmp_path) == {}
    path = tmp_path / sup.JOURNAL_RELPATH
    path.parent.mkdir(parents=True)
    path.write_text("[]", encoding="utf-8")
    assert sup._lire_journal(tmp_path) == {}
    path.write_text("{", encoding="utf-8")
    assert sup._lire_journal(tmp_path) == {}

    sup._ecrire_journal(tmp_path, {"a": {"x": 1}})
    assert sup._lire_journal(tmp_path) == {"a": {"x": 1}}
    before = sup.PANNES_INTERNES.get("unit", 0)
    sup._compter_panne_interne("unit")
    assert sup.PANNES_INTERNES["unit"] == before + 1


def test_semantic_failure_detection_and_fail_closed(tmp_path) -> None:
    from hl_observer.ops.preuve_de_vie import CAUSE_PANNE_TECHNIQUE

    state = type(
        "State",
        (),
        {
            "causes": (
                {"cause": CAUSE_PANNE_TECHNIQUE, "source": "broken"},
                {"cause": "MARCHE_CALME", "source": "healthy"},
                "invalid",
            )
        },
    )()
    assert sup._collecteurs_en_panne_semantique(
        tmp_path,
        1.0,
        diagnostic=lambda root, now_ms: state,
    ) == frozenset({"broken"})
    assert sup._collecteurs_en_panne_semantique(
        tmp_path,
        1.0,
        diagnostic=lambda root, now_ms: (_ for _ in ()).throw(RuntimeError("diag")),
    ) == frozenset()


def test_verifier_disabled_dead_restart_and_cooldown(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sup, "normaliser_profil", lambda profile: profile)
    monkeypatch.setattr(sup, "collecteurs_pour_profil", lambda profile: [_collector("c1")])
    monkeypatch.setattr(sup, "profil_collecteur", lambda name: "core")

    monkeypatch.setattr(sup, "actif", lambda: False)
    assert sup.verifier_et_relancer(tmp_path, profil="core")["actif"] is False

    monkeypatch.setattr(sup, "actif", lambda: True)
    monkeypatch.setattr(
        sup,
        "etat_collecteurs",
        lambda root, maintenant, profil: [
            {"nom": "c1", "age_minutes": None, "limite_minutes": 2.0, "mort": True}
        ],
    )
    monkeypatch.setattr(sup, "_collecteurs_en_panne_semantique", lambda *a, **k: frozenset())
    launched: list[list[str]] = []
    result = sup.verifier_et_relancer(
        tmp_path,
        maintenant=100.0,
        lanceur=lambda command, cwd: (launched.append(command) or True),
        cooldown_s=600,
        profil="core",
    )
    assert result["morts"] == ["c1"]
    assert result["relances"] == ["c1"]
    assert launched
    journal = sup._lire_journal(tmp_path)
    assert journal["c1"]["cause_relance"] == "mort"
    assert journal["c1"]["relances_total"] == 1

    result = sup.verifier_et_relancer(
        tmp_path,
        maintenant=101.0,
        lanceur=lambda command, cwd: True,
        cooldown_s=600,
        profil="core",
    )
    assert result["en_cooldown"] == ["c1"]


def test_atomic_pid_registry_and_lookup_helpers(tmp_path) -> None:
    assert sup._lire_pids(tmp_path) == {}
    payload = {"run_id": "r", "pids": {"c1": 10}}
    assert sup._ecrire_pids_atomique(tmp_path, payload)
    assert sup._lire_pids(tmp_path) == payload

    bad = tmp_path / sup.PIDS_RELPATH
    bad.write_text("[]", encoding="utf-8")
    assert sup._lire_pids(tmp_path) == {}
    bad.write_text("{", encoding="utf-8")
    assert sup._lire_pids(tmp_path) == {}

    c = _collector("alpha")
    procs = [
        {"pid": 10, "ppid": 1, "cmd": "cmd tools\\boucle_collecteur.cmd alpha tools\\alpha.py"},
        {"pid": 11, "ppid": 10, "cmd": "python tools\\alpha.py"},
        {"pid": 12, "ppid": 1, "cmd": "python other.py"},
    ]
    assert sup._pid_collecteur_existant(c, procs) == 10
    matches = sup._processus_du_collecteur(c, procs)
    assert [p["pid"] for p in matches] == [10, 11]
    logical, raw = sup._nombre_instances_logiques(c, procs)
    assert logical == 1 and raw == 2
    assert sup._nombre_instances_logiques(c, []) == (0, 0)


def test_parse_powershell_process_and_non_windows_shell(monkeypatch) -> None:
    assert sup._parse_ps_process("") == []
    assert sup._parse_ps_process("bad") == []
    one = json.dumps({"ProcessId": 1, "ParentProcessId": 0, "Name": "python.exe", "CommandLine": "x"})
    assert sup._parse_ps_process(one) == [{"pid": 1, "ppid": 0, "name": "python.exe", "cmd": "x"}]
    many = json.dumps([
        {"ProcessId": 2, "ParentProcessId": 1, "Name": "cmd.exe", "CommandLine": None},
        "ignored",
    ])
    assert sup._parse_ps_process(many) == [{"pid": 2, "ppid": 1, "name": "cmd.exe", "cmd": ""}]
    if os.name != "nt":
        assert sup._ps("echo x") == ""


def test_demarrer_un_unknown_and_success_updates_registry(tmp_path, monkeypatch) -> None:
    original = sup.REGISTRE
    monkeypatch.setattr(sup, "REGISTRE", [_collector("c1")])
    assert sup.demarrer_un(tmp_path, "missing", spawner=lambda c, root: 1) is None
    pid = sup.demarrer_un(tmp_path, "c1", spawner=lambda c, root: 123)
    assert pid == 123
    assert sup._lire_pids(tmp_path)["pids"]["c1"] == 123
    monkeypatch.setattr(sup, "REGISTRE", original)
