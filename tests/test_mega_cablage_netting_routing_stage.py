"""[CABLAGE étage D] netting_routing_stage : net + self-trade + priorité + routing + candidat canonique."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.mega_cablage.netting_routing_stage import netter_et_router   # noqa: E402

PRIX = {"BTC": 60000.0}


def test_deux_copies_meme_sens_nettees_en_un_candidat():
    intents = [
        {"module": "COPY_A", "venue": "HYPERLIQUID", "coin": "BTC", "montant_signe": 600.0},
        {"module": "COPY_B", "venue": "HYPERLIQUID", "coin": "BTC", "montant_signe": 400.0},
    ]
    r = netter_et_router(intents, prix_par_coin=PRIX)
    c = r["candidats"][0]
    assert c["net"] == 1000.0 and c["candidat"]["valide"] is True and c["cote"] == "BUY"
    assert abs(c["candidat"]["notional"] - 1000.0) < 1e-6


def test_self_trade_detecte_et_net_reduit():
    intents = [
        {"module": "COPY", "venue": "HYPERLIQUID", "coin": "BTC", "montant_signe": 600.0},
        {"module": "HEDGE", "venue": "HYPERLIQUID", "coin": "BTC", "montant_signe": -200.0},
    ]
    r = netter_et_router(intents, prix_par_coin=PRIX)
    assert r["self_trade"]["self_trade"] is True and r["candidats"][0]["net"] == 400.0


def test_net_nul_aucun_candidat_et_routing_choisit_maker():
    intents = [
        {"module": "A", "venue": "HYPERLIQUID", "coin": "BTC", "montant_signe": 600.0},
        {"module": "B", "venue": "HYPERLIQUID", "coin": "BTC", "montant_signe": -600.0},
    ]
    assert netter_et_router(intents, prix_par_coin=PRIX)["candidats"][0]["raison"] == "NET_NUL"
    # routing : la route MAKER la moins chère est choisie -> type_exec du candidat = MAKER
    routes = {"HYPERLIQUID/BTC": [
        {"venue": "HYPERLIQUID", "instrument": "BTC", "side": "BUY", "exec_type": "TAKER",
         "frais_bps": 4.5, "spread_bps": 1.0, "slippage_bps": 2.0, "premium_fiabilite_bps": 0.0},
        {"venue": "HYPERLIQUID", "instrument": "BTC", "side": "BUY", "exec_type": "MAKER",
         "frais_bps": 1.5, "spread_bps": 0.0, "slippage_bps": 0.5, "premium_fiabilite_bps": 0.0},
    ]}
    r = netter_et_router([{"module": "A", "venue": "HYPERLIQUID", "coin": "BTC", "montant_signe": 600.0}],
                         prix_par_coin=PRIX, routes_par_cle=routes)
    assert r["candidats"][0]["candidat"]["type_exec"] == "MAKER"
