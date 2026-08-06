"""[hyperlab] Sous-systeme operationnel HyperSmart.

API cablee : data_plane (medaillon Bronze/Silver/Gold + catalogue Data Mesh), collectors (supervision +
resilience), dlq (quarantaine), master (orchestrateur unique quick/full/deep/maximum/resume), qui tire
strategies (Copy-Vault / Lead-Lag / Cross-Venue), paper_engine (moteur unique, enveloppe 1000 USD),
validation (CPCV/PBO/DSR/SPA/ablation), report (rapport simple) et live_ready (OFFLINE_READY != LIVE)."""
from . import collectors  # noqa: F401
from . import data_plane  # noqa: F401
from . import dlq  # noqa: F401
from . import master  # noqa: F401
