"""§11.2 — source unique des frais taker (aucun hardcode concurrent)."""

import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.config import frais_venues as F  # noqa: E402


def test_frais_par_defaut_et_alias():
    assert F.frais_taker_bps("HYPERLIQUID") == 4.5
    assert F.frais_taker_bps("HL") == 4.5
    assert F.frais_taker_bps("BINANCE") == 5.0
    assert F.frais_taker_bps("BIN") == 5.0


def test_env_surcharge():
    os.environ["HYPERSMART_FEE_HYPERLIQUID_BPS"] = "2.0"
    try:
        assert F.frais_taker_bps("HL") == 2.0
    finally:
        del os.environ["HYPERSMART_FEE_HYPERLIQUID_BPS"]


def test_env_invalide_retombe_sur_defaut():
    os.environ["HYPERSMART_FEE_BINANCE_BPS"] = "pas_un_nombre"
    try:
        assert F.frais_taker_bps("BINANCE") == 5.0
    finally:
        del os.environ["HYPERSMART_FEE_BINANCE_BPS"]


def test_venue_inconnue_retourne_defaut_conservateur():
    assert F.frais_taker_bps("N_IMPORTE_QUOI") == max(F.DEFAUTS_TAKER_BPS.values())
    assert F.frais_taker_bps("X", defaut=7.0) == 7.0


def test_cross_venue_modules_tirent_de_la_source_unique():
    # Sans remise BNB prouvée, le round-trip utilise HL=4.5 et Binance=5.0.
    from hl_observer.arbitrage import cross_venue_roundtrip as R
    from hl_observer.arbitrage.cross_venue_capacity import BUY_HL_SELL_BINANCE
    books = {"hl_bids": [(100.0, 100.0)], "hl_asks": [(100.0, 100.0)],
             "bin_bids": [(100.0, 100.0)], "bin_asks": [(100.0, 100.0)]}
    r = R.cout_round_trip(BUY_HL_SELL_BINANCE, entree=books, sortie=books, notional_usd=100.0)
    assert r["frais_4_jambes_bps"] == 2 * 4.5 + 2 * 5.0


def test_binance_default_is_bound_to_official_regular_user_rate():
    assumption = F.hypothese_frais_taker("BINANCE")

    assert assumption.value == 5.0
    assert assumption.source_ref.startswith("https://www.binance.com/")
    assert assumption.observed_at == "2026-09-09T00:00:00Z"
