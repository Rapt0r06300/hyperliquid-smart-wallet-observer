# HyperSmart Archive Manifest

Included:

- `hyper_smart_observer/`
- `tests/`
- `docs/`
- `tools/`
- examples and project metadata

Excluded:

- `logs/`
- `data/`
- SQLite DB/WAL/SHM files
- archives
- caches
- virtualenvs
- `.env`

The clean archive script audits the ZIP after creation and fails if runtime files are present.
