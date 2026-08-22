"""LA WHITELIST COPY EXIGE LE NET, PAS LE BRUT (22/07).

Le rapport du 22/07 listait 10 leaders « prouvés » (markout brut > 0) et disait « copy peut
suivre CES leaders ». Or suivre = arriver APRÈS = taker aller-retour = ~9 bps. Sur ces 10, un
SEUL survivait au coût (0x5306, +17,9 brut → +8,9 net) ; les 9 autres perdaient de l'argent.
Un markout brut n'est pas un edge net — le même piège que le forfait d'arbitrage.
"""
from __future__ import annotations

import json

import pytest

from hl_observer.copy_wallet import leader_markout as LM


def test_le_cout_de_suivi_est_un_aller_retour_taker():
    """Copier = arriver après le leader = taker aux DEUX jambes. HL taker 4,5 × 2 = 9 bps."""
    assert LM.COPY_FOLLOW_COST_BPS == pytest.approx(9.0)


def test_le_net_soustrait_le_cout_de_suivi():
    assert LM.markout_net_de_copie_bps(17.9) == pytest.approx(8.9)
    assert LM.markout_net_de_copie_bps(8.19) == pytest.approx(-0.81)   # « prédit » mais PERD
    assert LM.markout_net_de_copie_bps(0.0) == pytest.approx(-9.0)


def test_un_markout_absent_ne_fabrique_pas_d_edge():
    assert LM.markout_net_de_copie_bps(None) is None


# ─────────────── la whitelist filtre sur le NET ───────────────

def _fills(adresse, markout_bps, n=40, mid=100.0):
    """Fabrique n fills d'un leader dont le markout moyen vaut ~markout_bps (side LONG)."""
    fwd = mid * (1 + markout_bps / 1e4)
    return [{"adresse": adresse, "coin": "BTC", "side": "B", "mid_at_fill": mid,
             "mid_forward": fwd, "ts_ms": 1_700_000_000_000 + i * 1_800_001}
            for i in range(n)]


def test_un_leader_qui_PREDIT_mais_PERD_apres_cout_est_verrouille(tmp_path):
    """LE test du rapport : brut +6 bps (predit) mais net -3 bps (perd) -> hors whitelist."""
    from tools.ecrire_copy_whitelist import construire_whitelist
    fills = _fills("0xPERD", 6.0) + _fills("0xGAGNE", 18.0)
    r = construire_whitelist(tmp_path, fills=fills)
    observations = {g["adresse"] for g in r["gardes_observation"]}
    assert "0xGAGNE" in observations, "brut +18 -> net +9 : observation rentable simple"
    assert "0xPERD" not in observations, "brut +6 -> net -3 : predit mais PERD, verrouille"
    assert r["gardes"] == [], "sans jours/regimes independants, aucune promotion live"
    assert r["predisent_brut"] == 2
    assert r["survivent_net_simple"] == 1 and r["survivent_net"] == 0


def test_les_predisent_mais_perdent_restent_VISIBLES_dans_details(tmp_path):
    """On ne cache pas un leader écarté : `details` porte son brut, son net, et pourquoi."""
    from tools.ecrire_copy_whitelist import construire_whitelist
    r = construire_whitelist(tmp_path, fills=_fills("0xPERD", 6.0))
    d = next(x for x in r["details"] if x["adresse"] == "0xPERD")
    assert d["predit"] is True and d["survit_au_cout"] is False
    assert d["markout_net_bps"] == pytest.approx(-3.0, abs=0.5)


def test_la_regle_dit_que_le_bar_est_le_NET(tmp_path):
    from tools.ecrire_copy_whitelist import construire_whitelist
    r = construire_whitelist(tmp_path, fills=[])
    assert "NET" in r["regle"] and "cout de suivi" in r["regle"]
    assert r["cout_de_suivi_bps"] == pytest.approx(9.0)


def test_une_whitelist_vide_reste_un_verrou_honnete(tmp_path):
    from tools.ecrire_copy_whitelist import construire_whitelist
    r = construire_whitelist(tmp_path, fills=_fills("0xFAIBLE", 2.0))   # net -7 -> personne
    assert r["gardes"] == [] and r["survivent_net"] == 0
    assert r["predisent_brut"] == 1, "il predit (brut>0) mais ne survit pas -> compte a part"


def test_aucune_execution_reelle(tmp_path):
    from tools.ecrire_copy_whitelist import construire_whitelist
    assert construire_whitelist(tmp_path, fills=[])["real_execution"] is False
