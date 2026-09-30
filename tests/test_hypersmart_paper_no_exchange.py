from pathlib import Path


def test_hypersmart_paper_no_forbidden_exchange_path():
    forbidden = "/" + "exchange"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in Path("hyper_smart_observer").rglob("*.py")
    )

    assert forbidden not in source


def test_hypersmart_paper_no_signature_calls():
    source = "\n".join(
        path.read_text(encoding="utf-8").lower()
        for path in Path("hyper_smart_observer").rglob("*.py")
    )

    assert ".sign(" not in source
    assert "sign_request" not in source
