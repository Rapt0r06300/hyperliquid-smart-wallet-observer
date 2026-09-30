from __future__ import annotations

import importlib


def test_copy_vault_book_loader_import_froid_sans_cycle() -> None:
    loader = importlib.import_module("hl_observer.backtesting.copy_vault_book_loader")
    executable = importlib.import_module("hl_observer.backtesting.copy_vault_executable")
    assert callable(loader.load_observed_books)
    assert executable.load_observed_books is loader.load_observed_books
    assert loader.MAX_TARGET_LAG_MS == executable.MAX_TARGET_LAG_MS
    assert (
        loader.CHECKPOINT_COLLECTOR_PROTOCOL
        == executable.CHECKPOINT_COLLECTOR_PROTOCOL
    )
