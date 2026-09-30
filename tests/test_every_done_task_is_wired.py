"""[Bloc 3/4] Gate d'HONNETETE : toute tache marquee `done_wired` dans le registre machine est
REELLEMENT branchee (au moins un module cite le code, a un appelant reel) ET testee, et tous les modules
cites existent sur disque. Empeche de declarer DONE sans preuve structurelle. Le runtime/live E2E est
verifie par des gates dediees (live_ready, pipeline E2E). Regenerer : `python tools/claude_tasks_scan.py`."""
import json
import os


def _root_and_rows():
    here = os.path.dirname(os.path.abspath(__file__))
    root = here
    for _ in range(6):
        p = os.path.join(root, "CLAUDE_TASKS.jsonl")
        if os.path.exists(p):
            rows = [json.loads(line) for line in open(p, encoding="utf-8") if line.strip()]
            return root, rows
        root = os.path.dirname(root)
    raise AssertionError("CLAUDE_TASKS.jsonl introuvable — lancer tools/claude_tasks_scan.py")


ROOT, ROWS = _root_and_rows()
_VALID = {"done_wired", "coded_unwired", "coded_untested", "untraced"}


def test_done_wired_implique_appelant_et_test():
    faux = [r["code"] for r in ROWS
            if r["status"] == "done_wired" and not (r["wired"] and r["tested"] and r["n_modules"] > 0)]
    assert not faux, "done_wired sans appelant/test (interdit): %s" % faux


def test_statuts_tous_valides():
    bad = [r["code"] for r in ROWS if r["status"] not in _VALID]
    assert not bad, "statuts invalides: %s" % bad


def test_modules_cites_existent_reellement():
    missing = []
    for r in ROWS:
        for m in r.get("modules", []):
            if not os.path.exists(os.path.join(ROOT, m)):
                missing.append(m)
    assert not missing, "modules cites mais inexistants: %s" % missing[:8]


def test_registre_couvre_les_590():
    assert len(ROWS) == 590, "le registre doit couvrir 590 taches, vu %d" % len(ROWS)
