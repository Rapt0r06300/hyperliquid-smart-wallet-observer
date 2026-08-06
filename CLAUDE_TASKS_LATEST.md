# CLAUDE_TASKS_LATEST — registre machine (scan structurel)

Scan REEL de src/ + tests/. `done_wired` = module + test + appelant reel (branche).
Ne prouve PAS le runtime/live (trace a part). Regenerer : `python tools/claude_tasks_scan.py`.

| statut | n |
|---|---|
| done_wired | 30 |
| coded_unwired | 50 |
| coded_untested | 75 |
| untraced | 435 |

meta : 1740 modules, 1564 tests, 5089 edges d'import.
