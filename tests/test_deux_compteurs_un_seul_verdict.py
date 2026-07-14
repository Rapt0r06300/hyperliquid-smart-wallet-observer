"""DEUX MODULES, UN MEME LOG, UN SEUL VERDICT (2026-07-12).

L'INCOHERENCE REPAREE
---------------------
`log_metrics._row_is_accepted` comptait `status="ACCEPTED"` comme une acceptation.
`decision_replay_analyzer._is_accepted_event`, non. La MEME ligne de log etait donc
"acceptee" pour un module et invisible pour l'autre.

Consequence concrete : le rapport de readiness pouvait annoncer OBSERVING_NO_VIRTUAL_ENTRY
("le moteur n'ouvre rien") alors qu'une position virtuelle venait d'etre ouverte et loggee.
Deux compteurs qui se contredisent, c'est deja un mensonge -- meme si aucun des deux n'est
malveillant. La regle du projet l'interdit : "Dashboard, audit, logs, exports convergent sur
le meme ledger."

CE QUE CES TESTS DEFENDENT
--------------------------
1. Les deux modules donnent le MEME verdict sur les MEMES lignes.
2. Les lignes d'ombre (profils GitHub, evaluations) restent EXCLUES -- on ne repare pas une
   incoherence en rouvrant le trou par lequel des dizaines de faux "acceptes" entraient.

Aucun reseau, aucun ordre : des dicts en memoire.
"""
from __future__ import annotations

import pytest

from hl_observer.simulation.decision_replay_analyzer import _is_accepted_event, _row_to_event
from hl_observer.simulation.log_metrics import _is_accepted_row, row_from_payload

# (ligne de log, doit-elle compter comme acceptee ?)
CAS = [
    ({"status": "ACCEPTED", "bot_decision": "VIRTUAL_POSITION_OPENED"}, True),
    ({"status": "ACCEPT_PAPER", "bot_decision": "PAPER_ENTRY"}, True),
    ({"status": "LOCAL_REPLAY", "bot_decision": "PAPER_CLOSE_SLTP"}, True),
    ({"status": "REFUSED", "bot_decision": "NO_TRADE"}, False),
    ({"status": "OK", "bot_decision": "REJECT_NO_TRADE"}, False),
    # LES LIGNES D'OMBRE : elles avaient fait afficher des dizaines de faux "acceptes"
    # pendant que le PnL restait plat. Elles doivent rester dehors.
    ({"status": "ACCEPTED", "bot_decision": "EXTERNAL_GITHUB_PROFILE_EVALUATED"}, False),
    ({"status": "ACCEPTED", "bot_decision": "ENGINE_EVALUATION"}, False),
]


@pytest.mark.parametrize("row,attendu", CAS)
def test_les_deux_compteurs_donnent_le_MEME_verdict(row: dict, attendu: bool) -> None:
    """L'INVARIANT. Si ce test tombe, un module a evolue sans l'autre -- et le dashboard
    recommencera a contredire l'audit."""
    verdict_analyzer = _is_accepted_event(_row_to_event(row))
    verdict_metrics = _is_accepted_row(row_from_payload(row))

    assert verdict_analyzer == verdict_metrics, (
        f"DESACCORD sur {row} : decision_replay_analyzer dit {verdict_analyzer}, "
        f"log_metrics dit {verdict_metrics}. Deux compteurs, un seul log : ils doivent "
        "converger, sinon l'un des deux ment au dashboard."
    )
    assert verdict_analyzer is attendu, f"verdict attendu {attendu} pour {row}"


def test_une_ligne_d_ombre_ne_redevient_PAS_un_trade_avec_un_statut_flatteur() -> None:
    """Le piege de la correction : en acceptant `status="ACCEPTED"`, on aurait pu rouvrir la
    porte aux profils GitHub qui portent ce statut. Les exclusions passent AVANT."""
    ombre = {"status": "ACCEPTED", "bot_decision": "EXTERNAL_GITHUB_PROFILE_EVALUATED"}
    assert _is_accepted_event(_row_to_event(ombre)) is False, (
        "une ligne d'ombre a ete comptee comme un trade parce qu'elle porte un statut "
        "flatteur. C'est exactement ce qui faisait afficher des dizaines de faux 'acceptes' "
        "pendant que le PnL restait plat."
    )
