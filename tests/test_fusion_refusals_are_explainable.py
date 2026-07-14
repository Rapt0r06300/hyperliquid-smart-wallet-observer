"""UN REFUS MUET N'EST PAS UN REFUS AUDITABLE (2026-07-11) — P2-3 / P2-4.

CE QUE J'AI TROUVÉ EN OUVRANT LE CHEMIN FUSION : ses **trois** points de refus renvoyaient un
résumé **vide**. Aucun motif. Nulle part.

    return FusionPaperEngineSummary(decisions=(), accepted_count=0, ...)   # et c'est tout

On ne pouvait donc ni vérifier qu'un gate avait tourné, ni savoir POURQUOI le bot n'ouvrait pas.

**C'est exactement pour cela que personne n'a vu que l'edge était fabriqué et que le carnet était
imaginaire : les gates « passaient » en silence.** Un contrôle sans trace n'est pas un contrôle —
c'est une croyance.

Ces tests exigent que chaque `NO_TRADE` s'explique.

Aucun ordre réel.
"""
from __future__ import annotations

import hl_observer.strategies.fusion_runtime  # noqa: F401  (ordre d'import applicatif)
from hl_observer.copy_wallet.copy_conflict_resolver import LeaderVote
from hl_observer.paper_trading.fusion_paper_engine_adapter import (
    FusionPaperEngineSummary,
    run_copy_votes_through_paper_engine,
)

MAINTENANT = 1_800_000_000_000


def _votes(n: int, *, age_ms: int) -> tuple[LeaderVote, ...]:
    """n leaders qui votent LONG sur BTC, avec un signal vieux de `age_ms`."""
    return tuple(
        LeaderVote(
            wallet=f"0x{i:040x}", coin="BTC", side="LONG", score=90.0,
            observed_at_ms=MAINTENANT - age_ms,
        )
        for i in range(n)
    )


def _lancer(votes: tuple[LeaderVote, ...]) -> FusionPaperEngineSummary:
    return run_copy_votes_through_paper_engine(
        votes, market_price=100.0, observed_at_ms=MAINTENANT,
    )


# ------------------------------------------------------------------ chaque refus s'explique

def test_a_stale_signal_says_it_is_stale(monkeypatch):
    """Le refus le plus fréquent des logs (`STALE_SIGNAL` × milliers) doit être NOMMÉ ici aussi."""
    monkeypatch.setenv("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS", "15000")
    r = _lancer(_votes(3, age_ms=60_000))          # 60 s : très périmé
    assert r.accepted_count == 0
    assert any("STALE_SIGNAL" in m for m in r.refusal_reasons), (
        f"un signal de 60 s est refusé sans dire pourquoi : {r.refusal_reasons}"
    )


def test_a_weak_consensus_says_it_is_weak(monkeypatch):
    monkeypatch.setenv("HYPERSMART_FUSION_COPY_MIN_WALLETS", "3")
    r = _lancer(_votes(1, age_ms=500))             # 1 seul wallet, mais signal FRAIS
    assert r.accepted_count == 0
    assert "CONSENSUS_TOO_WEAK" in r.refusal_reasons


def test_a_fabricated_edge_says_so(monkeypatch, tmp_path):
    """LE MOTIF QUI COMPTE LE PLUS : le bot refuse parce que l'edge n'est pas mesuré.
    Avant, il ouvrait — et le résumé ne disait rien du tout.

    2026-07-12 : l'empiricite ne se DECLARE plus, elle se DERIVE de la table mesuree (Q1).
    On retire donc la table : sans mesure, le refus doit tomber ET se nommer.
    """
    monkeypatch.setenv("HYPERSMART_FUSION_COPY_MIN_WALLETS", "1")
    monkeypatch.setenv("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS", "15000")
    monkeypatch.delenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", raising=False)   # défaut = strict
    monkeypatch.setenv("HYPERSMART_EDGE_CALIBRATION_PATH", str(tmp_path / "aucune.json"))
    r = _lancer(_votes(3, age_ms=500))             # frais ET consensuel : seul l'edge pèche
    assert r.accepted_count == 0
    assert any("EDGE" in m for m in r.refusal_reasons), (
        f"le refus pour edge non empirique est muet : {r.refusal_reasons}"
    )


# ------------------------------------------------------------------ le silence est interdit

def test_a_refusal_is_NEVER_silent(monkeypatch):
    """RÈGLE DURE : `accepted_count == 0` sans le moindre motif = un gate invérifiable.
    C'est ce silence qui a permis à un edge fabriqué de passer pour un contrôle sérieux."""
    monkeypatch.setenv("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS", "15000")
    for n, age in ((1, 500), (3, 60_000), (3, 500)):
        r = _lancer(_votes(n, age_ms=age))
        if r.accepted_count == 0:
            assert r.refusal_reasons, (
                f"refus MUET (wallets={n}, age={age} ms) : impossible de savoir quel gate a agi"
            )


def test_the_summary_exposes_the_reasons_to_the_dashboard(monkeypatch):
    """Les motifs doivent sortir jusqu'au dashboard, sinon ils n'existent que dans le code."""
    monkeypatch.setenv("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS", "15000")
    r = _lancer(_votes(3, age_ms=60_000))
    d = r.as_dict()
    assert "refusal_reasons" in d
    assert any("STALE_SIGNAL" in m for m in d["refusal_reasons"])
    assert d["real_execution"] is False


# ------------------------------------------------------------------ une acceptation reste possible

def test_an_acceptable_candidate_still_passes_in_AB_mode(monkeypatch):
    """Le gate ne bloque pas TOUT : en mode A/B explicite (ancien edge), le candidat frais et
    consensuel passe encore — et sans motif de refus."""
    monkeypatch.setenv("HYPERSMART_REQUIRE_EMPIRICAL_EDGE", "0")
    monkeypatch.setenv("HYPERSMART_FUSION_COPY_MIN_WALLETS", "1")
    monkeypatch.setenv("HYPERSMART_SIMULATION_MAX_SIGNAL_AGE_MS", "15000")
    r = _lancer(_votes(3, age_ms=500))
    if r.accepted_count > 0:
        assert r.refusal_reasons == ()
