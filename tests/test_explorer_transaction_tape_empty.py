from hl_observer.explorer.explorer_transaction_tape import format_explorer_tape


def test_format_explorer_tape_explains_empty_result() -> None:
    rendered = format_explorer_tape([])
    assert rendered.splitlines() == [
        "explorer transaction tape",
        "transactions: 0",
        "Explorer inspecte, mais aucune transaction structuree exploitable n'a ete extraite automatiquement.",
    ]
