from __future__ import annotations

import pytest

from tools.verify_copy_vault_closure_matrix import _criteria


def test_matrix_cli_accepts_only_exact_positive_json_integers() -> None:
    criterion = _criteria(
        [{"criterion_id": "runs", "required_kinds": ["github_hosted"], "min_distinct_runs": 2}]
    )[0]

    assert criterion.min_distinct_runs == 2


@pytest.mark.parametrize("value", [True, False, "2", 1.9, 0, -1, None])
def test_matrix_cli_rejects_truncated_or_invalid_run_counts(value: object) -> None:
    with pytest.raises(ValueError, match="positive JSON integer"):
        _criteria(
            [{"criterion_id": "runs", "required_kinds": ["github_hosted"], "min_distinct_runs": value}]
        )
