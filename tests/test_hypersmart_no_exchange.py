from pathlib import Path


def test_hypersmart_source_has_no_forbidden_exchange_path_literal():
    forbidden = "/" + "exchange"
    source_files = Path("hyper_smart_observer").rglob("*.py")

    offenders = [
        str(path)
        for path in source_files
        if forbidden in path.read_text(encoding="utf-8", errors="ignore")
    ]

    assert offenders == []
