"""Sous-systeme operationnel HyperLab.

Les sous-modules restent accessibles depuis ``hl_observer.hyperlab`` mais sont
charges a la demande. Ainsi, une brique legere comme ``calibration`` ne depend
pas des bibliotheques optionnelles du plan de donnees.
"""

from importlib import import_module
from types import ModuleType

__all__ = (
    "calibration",
    "collectors",
    "cross_venue_exec",
    "data_mesh_catalog",
    "data_plane",
    "dlq",
    "lanes",
    "leakage",
    "live_ready",
    "master",
    "medallion_store",
    "moteur_paper_unique",
    "normalization",
    "replay_parite",
    "report",
    "session",
    "strategies",
    "validation",
)


def __getattr__(name: str) -> ModuleType:
    if name not in __all__:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(f"{__name__}.{name}")
    globals()[name] = module
    return module


def __dir__() -> list[str]:
    return sorted((*globals(), *__all__))
