from __future__ import annotations

EXPLORER_REQUEST_WEIGHT = 40
BLOCK_LIST_EXTRA_LIMIT_PER_BLOCK = 1


def estimate_explorer_weight(requests: int, blocks: int = 0) -> int:
    return max(0, requests) * EXPLORER_REQUEST_WEIGHT + max(0, blocks) * BLOCK_LIST_EXTRA_LIMIT_PER_BLOCK

