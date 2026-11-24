from __future__ import annotations

import json

import tools.alina_autonomous_lab as alina_lab


def test_check_annonce_la_barriere_github_hosted_et_paper(capsys) -> None:
    rc = alina_lab.main(["check"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == "alina.autonomous_lab_entrypoint.v4"
    assert payload["control_schema"] == "alina.self_hosted_control.v1"
    assert payload["return_schema"] == "alina.self_hosted_return.v1"
    assert payload["self_hosted_ready_in_code"] is False
    assert payload["legacy_self_hosted_surface"] == "DISABLED_BY_POLICY"
    assert payload["execution_boundary"] == "github-hosted-only"
    assert payload["compact_return_ready_in_code"] is True
    assert payload["max_data_route"] == "src/hl_observer/datasets/max_data_router.py"
    assert payload["target_net_usd_per_day"] == 5.0
    assert "target_net_usd_per_family" not in payload
    assert payload["paper_only"] is True
    assert payload["real_execution"] is False


def test_control_self_hosted_est_bloque_sans_delegation(capsys, monkeypatch) -> None:
    def fail_if_called(_args):
        raise AssertionError("le contrôle self-hosted legacy ne doit pas être délégué")

    monkeypatch.setattr(alina_lab.self_hosted_control, "main", fail_if_called)
    rc = alina_lab.main(["control", "--", "--control", "job.json"])
    assert rc == 2
    assert "ALINA_SELF_HOSTED_CONTROL_DISABLED" in capsys.readouterr().out


def test_return_delegue_au_module_de_retour_compact(monkeypatch) -> None:
    seen: list[list[str]] = []

    def fake_main(args):
        seen.append(list(args))
        return 19

    monkeypatch.setattr(alina_lab.self_hosted_return, "main", fake_main)
    rc = alina_lab.main(["return", "--", "--result-dir", "resultats"])
    assert rc == 19
    assert seen == [["--", "--result-dir", "resultats"]]
