"""LIQUIDATIONS CONFIRMÉES (25/07) — le champ WsFill.liquidation ne doit PLUS être perdu au parsing.

Avant : `parser_message_userfills` reconstruisait un sous-ensemble et JETAIT `liquidation`. On avait donc
REAL_LIQUIDATION=0 par PERTE, pas par absence. Ces tests prouvent : (1) le champ est préservé quand présent,
(2) omis quand absent (pas de clé vide), (3) le helper `liquidations_confirmees` aplatit + marque REAL_LIQUIDATION,
(4) la logique de trading (appliquer_fill) ignore la clé en plus — aucune décision ne change.
"""
from __future__ import annotations

from hl_observer.collection import userfills_live as UL


def _msg(fills):
    return {"channel": "userFills", "data": {"user": "0xVAULT", "isSnapshot": False, "fills": fills}}


def test_le_champ_liquidation_est_PRESERVE_quand_present():
    liq = {"liquidatedUser": "0xabc", "markPx": "101.5", "method": "market"}
    fills = UL.parser_message_userfills(_msg([
        {"coin": "SOL", "px": "100.0", "sz": "3", "side": "A", "time": 1700000000000, "dir": "Close Long",
         "hash": "0xh", "liquidation": liq},
    ]), vault="0xVAULT")
    assert len(fills) == 1
    assert fills[0]["liquidation"] == liq, "le champ liquidation doit etre CONSERVE tel quel"


def test_pas_de_cle_liquidation_quand_absente():
    fills = UL.parser_message_userfills(_msg([
        {"coin": "ETH", "px": "2000", "sz": "1", "side": "B", "time": 1700000000000, "dir": "Open Long", "hash": "0xz"},
    ]), vault="0xVAULT")
    assert "liquidation" not in fills[0], "jamais de cle liquidation=None sur un fill normal"


def test_liquidations_confirmees_aplatit_et_marque_REAL_LIQUIDATION():
    liq = {"liquidatedUser": "0xabc", "markPx": "101.5", "method": "market"}
    fills = UL.parser_message_userfills(_msg([
        {"coin": "SOL", "px": "100.0", "sz": "3", "side": "A", "time": 1700000000000, "dir": "Close Long", "hash": "0xh", "liquidation": liq},
        {"coin": "ETH", "px": "2000", "sz": "1", "side": "B", "time": 1700000000001, "dir": "Open Long", "hash": "0xz"},  # normal
    ]), vault="0xVAULT")
    conf = UL.liquidations_confirmees(fills)
    assert len(conf) == 1, "seul le fill AVEC liquidation compte"
    c = conf[0]
    assert c["coin"] == "SOL" and c["provenance"] == "REAL_LIQUIDATION"
    assert c["source"] == "userFills.liquidation"
    assert c["liquidatedUser"] == "0xabc" and c["markPx"] == "101.5" and c["method"] == "market"
    assert c["px"] == 100.0 and c["sz"] == 3.0 and c["ts_ms"] == 1700000000000


def test_zero_confirmee_sur_flux_normal():
    fills = UL.parser_message_userfills(_msg([
        {"coin": "BTC", "px": "50000", "sz": "0.1", "side": "B", "time": 1700000000000, "dir": "Open Long", "hash": "0x1"},
    ]), vault="0xVAULT")
    assert UL.liquidations_confirmees(fills) == []


def test_la_logique_de_trading_IGNORE_la_cle_liquidation():
    """appliquer_fill lit coin/sz/signe/px : la clé liquidation en plus ne change AUCUNE position."""
    liq = {"liquidatedUser": "0xabc", "markPx": "101.5", "method": "market"}
    f_avec = {"coin": "SOL", "sz": 3.0, "signe": -1, "px": 100.0, "liquidation": liq}
    f_sans = {"coin": "SOL", "sz": 3.0, "signe": -1, "px": 100.0}
    p1 = UL.appliquer_fill({"SOL": {"szi": 5.0, "entryPx": 90.0}}, f_avec)
    p2 = UL.appliquer_fill({"SOL": {"szi": 5.0, "entryPx": 90.0}}, f_sans)
    assert p1 == p2, "la presence de liquidation ne doit RIEN changer a l'etat de position"
