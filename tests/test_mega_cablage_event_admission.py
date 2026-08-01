"""[CABLAGE étage A] event_admission : porte d'intégrité à l'ingestion (data_contract + feed_integrity)."""

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.mega_cablage.event_admission import admettre   # noqa: E402

TS = 1_700_000_000_000   # epoch ms réaliste


def test_evenement_valide_admis():
    ev = {"coin": "BTC", "px": 60000.0, "sz": 0.1, "signe": 1, "ts_ms": TS,
          "book": {"bids": [(59990.0, 2.0)], "asks": [(60010.0, 2.0)]}}
    r = admettre(ev)
    assert r["admis"] is True and r["side"] == "BUY" and r["canonique"]["price"] == 60000.0


def test_carnet_croise_refuse():
    ev = {"coin": "BTC", "px": 60000.0, "sz": 0.1, "signe": -1, "ts_ms": TS,
          "book": {"bids": [(60050.0, 2.0)], "asks": [(60000.0, 2.0)]}}   # croisé
    r = admettre(ev)
    assert r["admis"] is False and r["raison"].startswith("CARNET_")


def test_non_conforme_et_unite_ts():
    assert admettre({"coin": "BTC", "px": -1.0, "sz": 0.1, "signe": 1, "ts_ms": TS})["raison"] == "NON_CONFORME"
    # ts en secondes alors que ms attendu -> refus d'unité
    r = admettre({"coin": "BTC", "px": 60000.0, "sz": 0.1, "signe": 1, "ts_ms": 1_700_000_000})
    assert r["admis"] is False and r["raison"] == "TIMESTAMP_UNITE"
