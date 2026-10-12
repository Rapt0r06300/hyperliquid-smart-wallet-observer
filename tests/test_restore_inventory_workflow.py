from pathlib import Path


def test_restore_inventory_is_published_by_github_hosted_workflow():
    root = Path(__file__).parents[1]
    workflow = root / ".github" / "workflows" / "publish-restore-inventory.yml"
    text = workflow.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert "schedule:" in text
    assert "runs-on: ubuntu-latest" in text
    assert "contents: write" in text
    assert "timeout-minutes: 60" in text
    assert "tools/build_restore_inventory.py" in text
    assert "gh release create" in text
    assert "--latest=false" in text
    assert "self-hosted" not in text
    assert "lfs" not in text.lower()
