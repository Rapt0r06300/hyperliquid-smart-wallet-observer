from __future__ import annotations

from hyper_smart_observer.position_lifecycle.lifecycle_models import PositionLifecycle


def lifecycle_quality_score(lifecycle: PositionLifecycle) -> float:
    if not lifecycle.actions:
        return 0.0
    penalty = min(0.5, len(lifecycle.warnings) / max(1, len(lifecycle.actions)))
    return max(0.0, min(100.0, lifecycle.confidence * 100.0 * (1.0 - penalty)))
