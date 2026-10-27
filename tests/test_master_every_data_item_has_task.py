"""[Bloc 3] Gate : chaque item DATA (et AUD, BUG) possede une entree dans le registre MACHINE
CLAUDE_TASKS.jsonl. Empeche qu'un item de donnee existe sans tache tracee. Regenerer le registre :
`python tools/claude_tasks_scan.py`."""
import json
import os


def _codes():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    p = os.path.join(root, "docs", "archive", "root-history", "CLAUDE_TASKS.jsonl")
    if not os.path.exists(p):
        raise AssertionError("Snapshot historique CLAUDE_TASKS.jsonl introuvable")
    return {json.loads(line)["code"] for line in open(p, encoding="utf-8") if line.strip()}


CODES = _codes()


def test_les_120_data_ont_une_tache():
    manquants = ["DATA-%03d" % i for i in range(1, 121) if "DATA-%03d" % i not in CODES]
    assert not manquants, "DATA sans tache: %s" % manquants


def test_les_390_aud_ont_une_tache():
    manquants = ["AUD-%03d" % i for i in range(1, 391) if "AUD-%03d" % i not in CODES]
    assert not manquants, "AUD sans tache: %s" % manquants


def test_les_80_bug_ont_une_tache():
    manquants = ["BUG-%03d" % i for i in range(1, 81) if "BUG-%03d" % i not in CODES]
    assert not manquants, "BUG sans tache: %s" % manquants
