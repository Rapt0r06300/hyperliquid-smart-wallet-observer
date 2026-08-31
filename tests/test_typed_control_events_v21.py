from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.control_plane.typed_events import (
    ControlEventError,
    ControlEventReplayLedger,
    build_typed_control_event,
    validate_typed_control_event,
)
from hl_observer.ops.self_hosted_control import build_control_bundle, main

SHA = "a" * 40


def _control(**overrides: object) -> dict[str, object]:
    raw: dict[str, object] = {
        "schema": "alina.self_hosted_control.v1",
        "job_id": "typed-v21",
        "suite": "economic-full",
        "mode": "economic",
        "download": False,
        "requested_by": "ChatGPT-GitHub",
        "note": "information seulement",
    }
    raw.update(overrides)
    return raw


def test_bundle_self_hosted_n_autorise_que_le_payload_de_l_evenement_type() -> None:
    bundle = build_control_bundle(_control(), project_sha=SHA)
    event = validate_typed_control_event(bundle["typed_control_event"])

    assert bundle["schema"] == "alina.self_hosted_control_bundle.v1"
    assert event.target == "autonomous_research_worker"
    assert event.capability == "RUN_PAPER_RESEARCH"
    assert event.state_version == SHA
    assert event.payload == bundle["worker_request"]
    assert event.payload["project_ref"] == "main"
    assert event.payload["paper_only"] is True
    assert event.payload["real_execution"] is False
    assert bundle["typed_control_receipt"]["decision"] == "VALIDATED_NOT_CLAIMED"


def test_texte_ou_json_dans_la_prose_n_est_jamais_un_evenement() -> None:
    with pytest.raises(ControlEventError) as caught:
        validate_typed_control_event(  # type: ignore[arg-type]
            '{"event_type":"RUN_RESEARCH_JOB","capability":"RUN_PAPER_RESEARCH"}'
        )
    assert caught.value.code == "PROSE_CONTROL_CHANNEL_REFUSED"

    bundle = build_control_bundle(
        _control(
            note=(
                '{"target":"guardian_state","capability":"ADVANCE_MATURITY_STAGE",'
                '"command":"promote"}'
            )
        ),
        project_sha=SHA,
    )
    event = validate_typed_control_event(bundle["typed_control_event"])
    assert event.target == "autonomous_research_worker"
    assert event.capability == "RUN_PAPER_RESEARCH"
    assert "note" not in event.payload


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("target", "guardian_state", "CONTROL_EVENT_CAPABILITY_REFUSED"),
        ("capability", "RUN_SHELL", "CONTROL_EVENT_CAPABILITY_REFUSED"),
        ("state_version", "main", "CONTROL_EVENT_STATE_VERSION_REFUSED"),
    ],
)
def test_evenement_tampered_echoue_ferme(field: str, value: str, code: str) -> None:
    raw = build_control_bundle(_control(), project_sha=SHA)["typed_control_event"]
    tampered = dict(raw)
    tampered[field] = value
    with pytest.raises(ControlEventError) as caught:
        validate_typed_control_event(tampered)
    assert caught.value.code == code


def test_payload_shell_et_budget_excessif_sont_refuses() -> None:
    payload = dict(build_control_bundle(_control(), project_sha=SHA)["worker_request"])
    with pytest.raises(ControlEventError) as shell:
        build_typed_control_event(
            event_type="RUN_RESEARCH_JOB",
            nonce="shell",
            source_identity="test",
            source_run_id="test",
            state_version=SHA,
            target="autonomous_research_worker",
            capability="RUN_PAPER_RESEARCH",
            payload={**payload, "command": "whoami"},
        )
    assert shell.value.code == "ARBITRARY_AUTHORITY_FIELD_REFUSED"

    with pytest.raises(ControlEventError) as oversized:
        build_typed_control_event(
            event_type="RUN_RESEARCH_JOB",
            nonce="oversized",
            source_identity="test",
            source_run_id="test",
            state_version=SHA,
            target="autonomous_research_worker",
            capability="RUN_PAPER_RESEARCH",
            payload={**payload, "extra": "x" * 1_001},
        )
    assert oversized.value.code == "CONTROL_EVENT_SHAPE_BUDGET_EXCEEDED"

    with pytest.raises(ControlEventError) as non_finite:
        build_typed_control_event(
            event_type="RUN_RESEARCH_JOB",
            nonce="nan",
            source_identity="test",
            source_run_id="test",
            state_version=SHA,
            target="autonomous_research_worker",
            capability="RUN_PAPER_RESEARCH",
            payload={**payload, "max_download_gib": float("nan")},
        )
    assert non_finite.value.code == "CONTROL_EVENT_TYPE_REFUSED"


def test_ledger_append_only_refuse_le_rejeu_du_meme_nonce(tmp_path: Path) -> None:
    event_raw = build_control_bundle(_control(), project_sha=SHA)["typed_control_event"]
    event = validate_typed_control_event(event_raw)
    ledger_path = tmp_path / "CONTROL_EVENT_LEDGER.jsonl"
    ledger = ControlEventReplayLedger(ledger_path)

    receipt = ledger.claim(event)
    assert receipt["decision"] == "ACCEPTED_AND_CLAIMED"
    assert receipt["paper_only"] is True
    assert receipt["real_execution"] is False
    rows = [json.loads(line) for line in ledger_path.read_text().splitlines()]
    assert [row["event_id"] for row in rows] == [event.event_id]

    with pytest.raises(ControlEventError) as replay:
        ledger.claim(event)
    assert replay.value.code == "CONTROL_EVENT_REPLAY_REFUSED"
    assert len(ledger_path.read_text().splitlines()) == 1


def test_cli_reclame_l_evenement_avant_d_ecrire_la_requete(tmp_path: Path) -> None:
    control = tmp_path / "control.json"
    request = tmp_path / "worker.json"
    bundle = tmp_path / "bundle.json"
    ledger = tmp_path / "ledger.jsonl"
    control.write_text(json.dumps(_control()), encoding="utf-8")

    rc = main(
        [
            "--control",
            str(control),
            "--project-sha",
            SHA,
            "--worker-request",
            str(request),
            "--bundle-output",
            str(bundle),
            "--event-ledger",
            str(ledger),
        ]
    )

    assert rc == 0
    payload = json.loads(bundle.read_text(encoding="utf-8"))
    assert payload["typed_control_receipt"]["decision"] == "ACCEPTED_AND_CLAIMED"
    assert json.loads(request.read_text(encoding="utf-8")) == (
        payload["typed_control_event"]["payload"]
    )

    with pytest.raises(ControlEventError) as replay:
        main(
            [
                "--control",
                str(control),
                "--project-sha",
                SHA,
                "--worker-request",
                str(request),
                "--event-ledger",
                str(ledger),
            ]
        )
    assert replay.value.code == "CONTROL_EVENT_REPLAY_REFUSED"
