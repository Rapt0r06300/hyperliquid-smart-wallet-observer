# CLAUDE_TASKS_LATEST — registre machine (scan structurel)

Scan REEL de src/ + tests/. `done_wired` = module + test + appelant reel (branche).
Ne prouve PAS le runtime/live (trace a part). Regenerer : `python tools/claude_tasks_scan.py`.

| statut | n |
|---|---|
| done_wired | 25 |
| coded_unwired | 49 |
| coded_untested | 67 |
| untraced | 449 |

meta : 1733 modules, 1560 tests, 5074 edges d'import.
