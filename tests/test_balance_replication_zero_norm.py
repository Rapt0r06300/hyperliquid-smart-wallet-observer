from hl_observer.copy_fidelity.balance_replication import cosine_similarity


def test_cosine_similarity_zero_norm_is_zero() -> None:
    assert cosine_similarity({"BTC:L": 0.0}, {"BTC:L": 1.0}) == 0.0
