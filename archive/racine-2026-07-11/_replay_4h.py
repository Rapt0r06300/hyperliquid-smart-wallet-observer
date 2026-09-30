import sys, time, json, os
import multiprocessing as mp

sys.path.insert(0, "src")
from hl_observer.backtesting.scenario_search import search_over_db, load_jsonl


def run():
    NCPU = os.cpu_count() or 4
    JOBS = max(2, NCPU - 2)  # laisser 2 coeurs au serveur 48h
    cands = load_jsonl("runtime/scenarios/snap/candidates.jsonl")
    marks = load_jsonl("runtime/scenarios/snap/marks.jsonl")
    print("cpu_count", NCPU, "jobs", JOBS, "candidates", len(cands), "mark_rows", len(marks), flush=True)
    t = time.time()
    rep = search_over_db(
        cands, marks, "runtime/scenarios/scenarios.db",
        sample=None,            # balaie toute la DB 150M...
        max_seconds=4 * 3600,   # ...mais s'arrete a 4h en gardant le meilleur
        batch=5000, progress_every=5000,
        top_k=50, min_trades=20, jobs=JOBS, notional_usd=500.0,
    )
    rep["wall_seconds"] = round(time.time() - t, 1)
    with open("runtime/scenarios/replay_4h_report.json", "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    print("DONE evaluated=%d kept=%d robust=%d wall_s=%.0f -> runtime/scenarios/replay_4h_report.json"
          % (rep["scenarios_evaluated"], rep["scenarios_with_min_trades"],
             rep["robust_count"], rep["wall_seconds"]), flush=True)


if __name__ == "__main__":
    mp.freeze_support()
    run()
