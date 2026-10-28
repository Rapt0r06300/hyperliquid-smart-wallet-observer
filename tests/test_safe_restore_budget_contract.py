from __future__ import annotations

import re

import pytest

from tools import restore_alina, sync_complete_clone


@pytest.mark.parametrize(
    "module",
    [restore_alina, sync_complete_clone],
    ids=["restore", "sync"],
)
def test_safe_download_budget_default_is_eight_gib_and_reported_by_cli(
    module, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exc_info:
        module.main(["--help"])

    assert exc_info.value.code == 0
    help_text = " ".join(capsys.readouterr().out.split())
    option_start = help_text.rindex("--max-download-gib")
    next_option = help_text.find(" --", option_start + 1)
    option_help = help_text[option_start:next_option if next_option >= 0 else None]
    assert re.search(r"default\s+8(?:\s+GiB)?\b", option_help, re.IGNORECASE)
