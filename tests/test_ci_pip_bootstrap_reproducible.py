from pathlib import Path


def test_github_workflows_do_not_upgrade_pip_to_an_unpinned_latest_release() -> None:
    workflows = sorted(Path(".github/workflows").glob("*.yml"))
    assert workflows, "no GitHub Actions workflows found"

    offenders = [
        path.as_posix()
        for path in workflows
        if "python -m pip install --upgrade pip" in path.read_text(encoding="utf-8")
    ]

    assert offenders == [], (
        "CI bootstrap must be reproducible: replace unpinned `pip install --upgrade pip` "
        f"in {offenders} with an exact pip version."
    )
