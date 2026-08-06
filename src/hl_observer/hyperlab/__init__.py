"""[hyperlab] Sous-systeme operationnel HyperSmart.

API cablee : data_plane (medaillon + catalogue Data Mesh), collectors (supervision + resilience), dlq,
master (orchestrateur unique quick/full/deep/maximum/resume) et lanes (integrateur session validee),
qui tirent strategies (Copy-Vault / Lead-Lag / Cross-Venue), paper_engine (moteur unique, enveloppe
1000 USD), normalization, replay (parite + reconciliation 5 vues), cross_venue_exec, calibration,
session, leakage, validation et report. live_ready pose l'invariant OFFLINE_READY != LIVE_READY."""
from . import collectors  # noqa: F401
from . import data_plane  # noqa: F401
from . import dlq  # noqa: F401
from . import lanes  # noqa: F401
from . import master  # noqa: F401
