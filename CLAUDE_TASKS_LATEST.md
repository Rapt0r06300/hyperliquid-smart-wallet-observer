# CLAUDE_TASKS_LATEST — registre machine (scan structurel)

Scan REEL de src/ + tests/. `done_wired` = module + test + appelant reel (branche).
Ne prouve PAS le runtime/live (trace a part). Regenerer : `python tools/claude_tasks_scan.py`.

| statut | n |
|---|---|
| done_wired | 34 |
| coded_unwired | 47 |
| coded_untested | 83 |
| untraced | 426 |

meta : 1748 modules, 1569 tests, 5102 edges d'import.
