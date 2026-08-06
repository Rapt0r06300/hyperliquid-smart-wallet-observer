# CLAUDE_TASKS_LATEST — registre machine (scan structurel)

Scan REEL de src/ + tests/. `done_wired` = module + test + appelant reel (branche).
Ne prouve PAS le runtime/live (trace a part). Regenerer : `python tools/claude_tasks_scan.py`.

| statut | n |
|---|---|
| done_wired | 22 |
| coded_unwired | 51 |
| coded_untested | 63 |
| untraced | 454 |

meta : 1728 modules, 1552 tests, 5068 edges d'import.
