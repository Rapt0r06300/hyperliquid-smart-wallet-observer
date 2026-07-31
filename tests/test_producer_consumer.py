"""FIX-45 — producer/consumer PAR stratégie : runtime_truth pilote le routage. Une stratégie sans producteur
vivant ne consomme RIEN (pas de fill fantôme) ; une stratégie VIVANTE ingère ses événements via son pipeline
canonique dédié (FIX-44). Preuve que runtime_truth est réellement APPELÉ pour décider (plus 'jamais appelé').
"""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import paper_canonique as PC              # noqa: E402
from hl_observer.ops.producer_consumer import ProducerConsumer  # noqa: E402

NOW = 1_000_000


def _obs(*, vivante, morte_flag_on=False):
    # `vivante` : producteur frais + chaîne complète -> VIVANT. `morte` : producer_alive=False -> OFF /
    # ON_SANS_PRODUCTEUR (si flag_on). Les deux premières stratégies actives servent de vivante/morte.
    actives = list(PC.STRATEGIES_ACTIVES)
    obs = {}
    obs[actives[0]] = {"producer_alive": True, "last_event_ms": NOW, "signal_path_alive": True,
                       "execution_engine_alive": True, "ledger_writable": True}
    obs[actives[1]] = {"producer_alive": False, "last_event_ms": NOW - 10_000_000,
                       "signal_path_alive": True, "execution_engine_alive": True,
                       "ledger_writable": True, "flag_on": morte_flag_on}
    return actives[0], actives[1], obs


def _flux(vivante, morte):
    evs, seq = [], 0
    for k in range(10):
        seq += 1
        evs.append({"seq": seq, "ts_ms": k, "coin": "BTC", "mid": 100.0})               # marché (état)
        seq += 1
        evs.append({"seq": seq, "ts_ms": k, "coin": "BTC", "mid": 100.0,
                    "strategy": vivante, "side": 1, "edge_bps": 30.0})                   # signal vivante
        seq += 1
        evs.append({"seq": seq, "ts_ms": k, "coin": "BTC", "mid": 100.0,
                    "strategy": morte, "side": 1, "edge_bps": 30.0})                     # signal morte
    return evs


def test_fix45_strategie_morte_ne_consomme_rien():
    vivante, morte, obs = _obs(vivante=True)
    pc = ProducerConsumer()
    rt = pc.traiter(_flux(vivante, morte), observations=obs, now_ms=NOW)
    # runtime_truth a bien été appelé pour décider (module plus jamais 'jamais appelé')
    assert rt["strategies_actives"][vivante]["etat"] == "VIVANT"
    assert rt["strategies_actives"][morte]["etat"] == "OFF"
    sb = pc.scoreboards()
    assert sb[vivante]["n_fills"] == 10 and sb[vivante]["net_bps_total"] > 0        # la vivante trade
    assert sb[morte]["n_fills"] == 0 and sb[morte]["n_events"] == 0                 # la morte : AUCUN fill fantôme
    assert pc.drops.get("PRODUCTEUR_ABSENT:OFF") == 10                             # ses 10 signaux droppés, nommés


def test_fix45_flag_on_sans_producteur_reste_off_de_fait():
    vivante, morte, obs = _obs(vivante=True, morte_flag_on=True)
    pc = ProducerConsumer()
    pc.traiter(_flux(vivante, morte), observations=obs, now_ms=NOW)
    assert pc.rt_dernier["strategies_actives"][morte]["etat"] == "ON_SANS_PRODUCTEUR"
    assert pc.scoreboards()[morte]["n_fills"] == 0                                  # ON affiché mais OFF de fait
    assert pc.drops.get("PRODUCTEUR_ABSENT:ON_SANS_PRODUCTEUR") == 10
    assert pc.rt_dernier["real_execution"] is False                                # 0 ordre réel


def test_fix45_evenement_hors_scope_est_droppe():
    vivante, morte, obs = _obs(vivante=True)
    pc = ProducerConsumer()
    evs = [{"seq": 1, "ts_ms": 0, "coin": "BTC", "mid": 100.0,
            "strategy": "carry", "side": 1, "edge_bps": 50.0}]                       # famille legacy hors scope
    pc.traiter(evs, observations=obs, now_ms=NOW)
    assert pc.drops.get("HORS_SCOPE") == 1
    assert all(s["n_fills"] == 0 for s in pc.scoreboards().values())
