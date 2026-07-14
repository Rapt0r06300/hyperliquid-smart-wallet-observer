import sys, time, json, os
import multiprocessing as mp

sys.path.insert(0, "src")
from hl_observer.backtesting.scenario_search import search_over_db, load_jsonl

STOP_FILE = "runtime/scenarios/STOP_REPLAY"
REPORT_4H = "runtime/scenarios/replay_4h_report.json"
OUT = "runtime/scenarios/replay_open_report.json"


def run():
    NCPU = os.cpu_count() or 4
    JOBS = max(2, NCPU - 2)  # laisser 2 coeurs au serveur 48h
    # reprendre APRES ce que le run 4h a deja couvert (si son rapport existe)
    start_id = 0
    try:
        if os.path.exists(REPORT_4H):
            start_id = int(json.load(open(REPORT_4H, encoding="utf-8")).get("scenarios_evaluated") or 0)
    except Exception:
        start_id = 0
    try:
        if os.path.exists(STOP_FILE):
            os.remove(STOP_FILE)  # repartir sans un vieux signal STOP
    except Exception:
        pass
    cands = load_jsonl("runtime/scenarios/snap/candidates.jsonl")
    marks = load_jsonl("runtime/scenarios/snap/marks.jsonl")
    print("cpu_count", NCPU, "jobs", JOBS, "candidates", len(cands), "start_id", start_id,
          "=> tourne SANS limite de temps jusqu'au fichier", STOP_FILE, flush=True)
    t = time.time()
    rep = search_over_db(
        cands, marks, "runtime/scenarios/scenarios.db",
        sample=None, start_id=start_id,
        max_seconds=None,           # PAS de limite de temps
        stop_file=STOP_FILE,        # s'arrete quand ce fichier apparait
        batch=5000, progress_every=5000,
        top_k=50, min_trades=20, jobs=JOBS, notional_usd=500.0,
    )
    rep["wall_seconds"] = round(time.time() - t, 1)
    rep["start_id"] = start_id
    with open(OUT, "w", encoding="utf-8") as fh:
        json.dump(rep, fh, ensure_ascii=False, indent=2)
    print("DONE evaluated=%d robust=%d wall_s=%.0f -> %s" % (
        rep["scenarios_evaluated"], rep["robust_count"], rep["wall_seconds"], OUT), flush=True)


if __name__ == "__main__":
    mp.freeze_support()
    run()
