from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from hl_observer.ops import preuve_de_vie as PV
from tools import collecter_allmids as ALLMIDS
from tools import collecter_userfills_vaults as USERFILLS
from tools import heartbeat_collecteur as HB


def test_heartbeat_new_wrapper_pid_resets_previous_session_counters(tmp_path: Path):
    HB.battre(tmp_path, "source", pid=101, n_ecrites=50, souscription_ack=True)
    current = HB.battre(tmp_path, "source", pid=202, n_ecrites=1, souscription_ack=False)

    assert current["pid"] == 202
    assert current["n_passes"] == 1
    assert current["n_ecrites_cumul"] == 1
    assert current["souscription_ack"] is False


def test_allmids_real_response_writes_canonical_wrapper_heartbeat(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ALLMIDS.os, "getppid", lambda: 4242)

    count = ALLMIDS.une_passe(tmp_path, post_allmids=lambda: {"BTC": "65000", "HYPE": "40"})
    heartbeat = HB.lire(tmp_path, "allmids-collector")

    assert count == 2
    assert heartbeat["pid"] == 4242
    assert heartbeat["n_ecrites_cumul"] == 1
    assert heartbeat["souscription_ack"] is True


def test_allmids_rest_readiness_does_not_invent_exchange_subscription():
    source = next(item for item in PV.SOURCES_HARVEST if item.nom == "allmids-collector")
    proof = PV.preuve_source(
        source,
        {"pid": 9, "ts_ms": 1000, "n_ecrites_cumul": 1, "dernier_exchange_ts": None},
        now_ms=1001,
        pid_vivant=lambda pid: pid == 9,
    )

    assert proof.sain
    assert proof.souscription_ack
    assert proof.horodatages_presents


def test_userfills_bridge_writes_ack_and_real_message_count(tmp_path: Path, monkeypatch):
    USERFILLS._HEARTBEAT_WS.update({
        "messages": 2,
        "fills": 3,
        "acks": 1,
        "reconnects": 0,
        "drops": 0,
        "dernier_exchange_ts": 123456,
    })
    monkeypatch.setattr(USERFILLS.os, "getppid", lambda: 5252)
    monkeypatch.setattr(USERFILLS.VI, "heartbeat", lambda *_args, **_kwargs: None)

    async def stop_after_write(_seconds):
        raise RuntimeError("test-stop")

    monkeypatch.setattr(USERFILLS.asyncio, "sleep", stop_after_write)
    with pytest.raises(RuntimeError, match="test-stop"):
        asyncio.run(USERFILLS._heartbeat(tmp_path, {}))

    heartbeat = HB.lire(tmp_path, "userfills-live")
    assert heartbeat["pid"] == 5252
    assert heartbeat["n_ecrites_cumul"] == 2
    assert heartbeat["dernier_exchange_ts"] == 123456
    assert heartbeat["souscription_ack"] is True


def test_launcher_reconciles_collectors_and_cleans_up_failed_warmup():
    launcher = Path("LANCER_HYPERSMART.cmd").read_text(encoding="utf-8", errors="replace")

    marker = "Une ancienne boucle peut sortir juste apres le changement du marqueur de session."
    assert marker in launcher
    assert launcher.count("call :demarrer_collecteurs") >= 3
    warmup_failure = launcher.split("DATA_NOT_READY : allMids/BBO/userFills", 1)[1].split(
        "[READY_CORE] OK", 1
    )[0]
    assert "call :stop_impl" in warmup_failure
