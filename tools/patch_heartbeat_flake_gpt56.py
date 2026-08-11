from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "tests" / "test_recherche_continue_launcher_resilience.py"

OLD = '''        deadline = time.time() + 2.0
        while not heartbeat_path.exists() and time.time() < deadline:
            time.sleep(0.02)
        first = json.loads(heartbeat_path.read_text(encoding="utf-8"))
        time.sleep(1.1)
        second = json.loads(heartbeat_path.read_text(encoding="utf-8"))
        assert first["etat_ui"] == "ACTIF"
        assert second["ui_tick"] > first["ui_tick"]
        assert second["ts"] > first["ts"]
        assert thread.is_alive()
'''

NEW = '''        deadline = time.monotonic() + 2.0
        while not heartbeat_path.exists() and time.monotonic() < deadline:
            time.sleep(0.02)
        assert heartbeat_path.exists(), "dashboard heartbeat was never created"
        first = json.loads(heartbeat_path.read_text(encoding="utf-8"))

        # A hosted CI runner is not a real-time scheduler: sleeping exactly 1.1 s
        # can wake before the dashboard thread gets its next time slice. Poll the
        # observable heartbeat instead, with a hard deadline, so the test still
        # proves liveness without depending on scheduler precision.
        advance_deadline = time.monotonic() + 3.0
        second = first
        while second["ui_tick"] <= first["ui_tick"] and time.monotonic() < advance_deadline:
            time.sleep(0.05)
            second = json.loads(heartbeat_path.read_text(encoding="utf-8"))

        assert first["etat_ui"] == "ACTIF"
        assert second["ui_tick"] > first["ui_tick"]
        assert second["ts"] > first["ts"]
        assert second["ts"] - first["ts"] <= 3.0
        assert thread.is_alive()
'''


def main() -> None:
    text = PATH.read_text(encoding="utf-8")
    if NEW in text:
        print("HEARTBEAT_TEST_ALREADY_PATCHED")
        return
    if OLD not in text:
        raise SystemExit("heartbeat test marker changed; refusing broad edit")
    text = text.replace(OLD, NEW, 1)
    PATH.write_text(text, encoding="utf-8", newline="\n")
    print("HEARTBEAT_TEST_PATCHED")


if __name__ == "__main__":
    main()
