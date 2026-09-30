import sys, time, json, os
import multiprocessing as mp

sys.path.insert(0, "src")
from hl_observer.backtesting.scenario_search import search_over_db, load_jsonl


def run():
    NCPU = os.cpu_count() or 4
    JOBS = max(2, NCPU - 2)  # laisser des coeurs au serveur 48h
    SAMPLE = 20000
    cands = load_jsonl("runtime/scenarios/snap/candidates.jsonl")
    marks = load_jsonl("runtime/scenarios/snap/marks.jsonl")
    print("cpu_count", NCPU, "jobs", JOBS, "candidates", len(cands), "mark_rows", len(marks), flush=True)
    t = time.time()
    rep = search_over_db(cands, marks, "runtime/scenarios/scenarios.db",
                         sample=SAMPLE, batch=SAMPLE, top_k=25, min_trades=20,
                         jobs=JOBS, notional_usd=500.0)
    el = time.time() - t
    thr = SAMPLE / el if el > 0 else 0.0
    print("elapsed_s", round(el, 1), "throughput_scen_per_s", round(thr, 1))
    print("evaluated", rep["scenarios_evaluated"], "with_min_trades", rep["scenarios_with_min_trades"],
          "robust_count", rep["robust_count"])
    if thr > 0:
        print("ETA_150M_hours", round(150_000_000 / thr / 3600, 1))
    best = rep.get("best_robust") or (rep["finalists"][0] if rep.get("finalists") else None)
    print("BEST_FINALIST", json.dumps(best, ensure_ascii=False)[:1400])
    json.dump(rep, open("runtime/scenarios/sample_report.json", "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("WROTE runtime/scenarios/sample_report.json", flush=True)


if __name__ == "__main__":
    mp.freeze_support()
    run()
