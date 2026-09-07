"""Coverage ciblée de l'agrégation de feedback de la boucle autonome.

Pur test : aucun réseau, aucune exécution réelle, aucun changement de seuil/gate.
"""

from hl_observer.loops.models import ExecutionFeedback, LearningSummary


def test_learning_summary_counts_testnet_guard_rejection() -> None:
    feedback = ExecutionFeedback(
        candidate_id="candidate-guard",
        decision_action="NO_TRADE",
        execution_status="REJECT_TESTNET_GUARD",
        reasons=["TESTNET_GUARD"],
    )

    summary = LearningSummary.from_feedback([feedback])

    assert summary.total_decisions == 1
    assert summary.rejected == 1
    assert summary.no_trade == 1
    assert summary.accepted_testnet == 0
    assert summary.recurring_reasons == {"TESTNET_GUARD": 1}
