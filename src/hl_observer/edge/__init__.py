"""Edge remaining, decay, and copy degradation calculations."""
from hl_observer.edge.edge_calculator import EdgeNetInputs, EdgeNetResult, apply_time_decay, compute_net_edge
from hl_observer.edge.edge_net_v12 import EdgeNetV12Estimate, EdgeNetV12Inputs, estimate_edge_net_v12
from hl_observer.edge.margin_of_safety import MarginOfSafetyConfig, MarginOfSafetyDecision, evaluate_margin_of_safety

__all__ = [
    "EdgeNetInputs",
    "EdgeNetResult",
    "EdgeNetV12Estimate",
    "EdgeNetV12Inputs",
    "MarginOfSafetyConfig",
    "MarginOfSafetyDecision",
    "apply_time_decay",
    "compute_net_edge",
    "estimate_edge_net_v12",
    "evaluate_margin_of_safety",
]
