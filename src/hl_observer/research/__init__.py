"""Research / evidence helpers.

Everything in this package is context/offline only.  It must never create a
paper intent, never sign, never route an order, and never sit in the hot path.
"""

from hl_observer.research.ollama_advisor import (
    OllamaAdvisorConfig,
    OllamaAdvisorResult,
    advise_from_summary,
    advise_json_from_summary,
)
from hl_observer.research.ollama_status import OllamaStatus, ollama_status
from hl_observer.research.ollama_preflight import OllamaPreflight, run_ollama_preflight
from hl_observer.research.ollama_signal_rater import (
    OllamaSignalRaterConfig,
    OllamaSignalRating,
    rate_signal_candidate,
)

__all__ = [
    "OllamaAdvisorConfig",
    "OllamaAdvisorResult",
    "OllamaPreflight",
    "OllamaSignalRaterConfig",
    "OllamaSignalRating",
    "OllamaStatus",
    "advise_from_summary",
    "advise_json_from_summary",
    "ollama_status",
    "rate_signal_candidate",
    "run_ollama_preflight",
]
