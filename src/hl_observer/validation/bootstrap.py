from __future__ import annotations


def minimum_sample_ok(sample_count: int, minimum: int = 30) -> bool:
    return sample_count >= minimum
