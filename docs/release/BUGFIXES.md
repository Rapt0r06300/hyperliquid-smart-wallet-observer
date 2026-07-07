# HyperSmart — Registre des bugs réels corrigés

_2026-07-01. Corrections côté Windows (fichiers complets/valides)._

| # | Bug | Fichier | Cause | Correction |
|---|---|---|---|---|
| 1 | Import circulaire | `risk/microstructure_guard.py` | `risk/__init__` → microstructure_guard → `signals.depth_spread_gate` → retour dans risk (cycle) | Import paresseux de `DepthSpreadConfig`/`depth_spread_gate` dans la fonction |
| 2 | Forward-ref non résolu | `hyperliquid/rest_info_client.py` | Annotation `"CollectionRecorder | None"` sans import (F821) | Bloc `if TYPE_CHECKING: from ... import CollectionRecorder` |
| 3 | Crash import Python 3.10 | `copy_mode/copy_session_controller.py` | `from enum import StrEnum` (StrEnum ajouté en 3.11) sans garde | Pattern gardé `try: from enum import StrEnum / except ImportError: class StrEnum(str, Enum)` |

## Faux positifs (NON corrigés — artefacts sandbox)
Les « invalid-syntax / EOF » signalés par ruff/py_compile/pytest **dans le sandbox** sur
`ui/routes.py`, `simulation/log_metrics.py`, `risk/microstructure_guard.py`,
`hyperliquid/rest_info_client.py` sont dus à la **troncature du mount** : les fichiers sont
complets et valides côté Windows (run `pytest -q` = 2080 passed). Aucune action requise.
