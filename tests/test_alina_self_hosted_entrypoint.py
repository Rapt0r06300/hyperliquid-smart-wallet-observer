from __future__ import annotations

import json

import tools.alina_autonomous_lab as alina_lab


def test_check_annonce_le_plan_de_controle_self_hosted(capsys) -> None:
    rc = alina_lab.main(["check"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "alina.autonomous_lab_entrypoint.v3"
    assert payload["control_schema"] == "alina.self_hosted_control.v1"
    assert payload["return_schema"] == "alina.self_hosted_return.v1"
    assert payload["self_hosted_ready_in_code"] is True
    assert payload["compact_return_ready_in_code"] is True
    assert payload["paper_only"] is True
    assert payload["real_execution"] is False


def test_control_delegue_au_module_securise(monkeypatch) -> None:
    seen: list[list[str]] = []

    def fake_main(args):
        seen.append(list(args))
        return 17

    monkeypatch.setattr(alina_lab.self_hosted_control, "main", fake_main)
    rc = alina_lab.main(["control", "--", "--control", "job.json"])
    assert rc == 17
    assert seen == [["--", "--control", "job.json"]]


def test_return_delegue_au_module_de_retour_compact(monkeypatch) -> None:
    seen: list[list[str]] = []

    def fake_main(args):
        seen.append(list(args))
        return 19

    monkeypatch.setattr(alina_lab.self_hosted_return, "main", fake_main)
    rc = alina_lab.main(["return", "--", "--result-dir", "resultats"])
    assert rc == 19
    assert seen == [["--", "--result-dir", "resultats"]]
