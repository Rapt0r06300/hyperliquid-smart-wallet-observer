import os
import json
import subprocess
import sys
import glob

def check_fixtures():
    print("--- Checking Fixtures ---")
    fixture_dir = "tests/fixtures/hypersmart"
    expected_fixtures = [
        "leader_shortlist_valid.json",
        "leader_shortlist_too_many.json",
        "invalid_truncated_addresses.json",
        "info_clearinghouse_state_prev.json",
        "info_clearinghouse_state_curr_open_long.json",
        "info_clearinghouse_state_curr_close_long.json",
        "info_user_fills_open_long.json",
        "info_user_fills_close_long_with_closed_pnl.json",
        "info_open_orders_context_only.json",
        "info_all_mids.json",
        "ws_user_fills_snapshot.json",
        "ws_user_fills_update.json",
        "ws_user_events_update.json",
        "no_trade_examples.json",
        "backtest_delta_sequence.json"
    ]

    missing = []
    for f in expected_fixtures:
        path = os.path.join(fixture_dir, f)
        if not os.path.exists(path):
            missing.append(f)
        else:
            try:
                with open(path, 'r') as handle:
                    json.load(handle)
                print(f"OK: {f}")
            except Exception as e:
                print(f"FAIL (JSON): {f} - {e}")
                missing.append(f)

    if missing:
        print(f"Missing or broken fixtures: {missing}")
        return False
    return True

def run_contract_tests():
    print("\n--- Running Contract Tests ---")
    env = os.environ.copy()
    env["PYTHONPATH"] = os.getcwd()

    # Use glob to find files because subprocess doesn't expand wildcards by default
    test_files = glob.glob("tests/test_hypersmart_contract_*.py")
    if not test_files:
        print("ERROR: No contract test files found.")
        return False

    result = subprocess.run(
        [sys.executable, "-m", "pytest"] + test_files,
        env=env,
        capture_output=True,
        text=True
    )
    print(result.stdout)
    if result.returncode != 0:
        print(result.stderr)
        return False
    return True

def main():
    print("=== HYPERSMART HANDOFF READINESS CHECK ===\n")
    fixtures_ok = check_fixtures()
    tests_ok = run_contract_tests()

    if fixtures_ok and tests_ok:
        print("\nSUCCESS: All fixtures and contract tests are ready for handoff.")
        sys.exit(0)
    else:
        print("\nFAILURE: Handoff pack is incomplete or failing tests.")
        sys.exit(1)

if __name__ == "__main__":
    main()
