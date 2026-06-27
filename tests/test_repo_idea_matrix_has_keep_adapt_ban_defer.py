"""The repo idea matrix must classify ideas KEEP / ADAPT / BAN / DEFER and
link every analysed repo."""

from pathlib import Path

MATRIX = Path("docs/research/HYPERSMART_REPO_IDEA_MATRIX_FUSION.md")
REPOS = [
    "CloddsBot", "Harrier", "MrFadi", "polymarket_lp", "PolyWeather",
    "Composio", "PolyTerm", "mlmodelpoly", "polyrec", "backtesting",
    "polybot", "agents", "ightweight",
]


def test_matrix_has_all_four_statuses():
    text = MATRIX.read_text(encoding="utf-8")
    for status in ("KEEP", "ADAPT", "BAN", "DEFER"):
        assert status in text, f"matrix missing status: {status}"


def test_matrix_links_every_repo():
    text = MATRIX.read_text(encoding="utf-8")
    missing = [r for r in REPOS if r not in text]
    assert not missing, f"matrix missing repos: {missing}"
