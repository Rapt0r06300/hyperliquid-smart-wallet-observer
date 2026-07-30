"""ALPHA-5 — lead-lag cross-venue conditionné aux événements causaux.

Prouve les invariants de vérité : condition non mesurable ⇒ `None` jamais retenu, seuils et horloges
pré-enregistrés, embargo réel, TOUS les essais comptés (y compris les KILL), et **aucune promotion possible**.

Paper/SHADOW uniquement : 0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.experimental import cross_venue_conditions as CVC  # noqa: E402
from hl_observer.experimental import registre_essais  # noqa: E402
from hl_observer.experimental.metaorder_l2_tape import resume_book  # noqa: E402


def _book(bid: float, ask: float, taille_bid: float = 10.0, taille_ask: float = 10.0) -> dict:
    """l2Book BRUT au format Hyperliquid (levels[0]=bids, levels[1]=asks)."""
    return {
        "time": 1_700_000_000_000,
        "levels": [
            [{"px": str(bid - i * 0.01), "sz": str(taille_bid), "n": 1} for i in range(5)],
            [{"px": str(ask + i * 0.01), "sz": str(taille_ask), "n": 1} for i in range(5)],
        ],
    }


def _mesures(n: int, net_bps: float = 1.0, pas_ms: int = 10_000, t0: int = 1_000_000, horizon: int = 500):
    return [{"statut": "OK", "famille": "PRICE_SHOCK", "dir": 1, "t_choc": t0 + i * pas_ms,
             "par_horizon": {str(horizon): {"statut": "OK", "net_bps": net_bps}}} for i in range(n)]


# ═══════════════ horloges pré-enregistrées ═══════════════
def test_horloges_preenregistrees_sans_balayage():
    debut_minute = 1_700_000_040_000  # multiple exact de 60 000
    c = CVC.conditions_horloge(debut_minute)
    assert c["CLOCK_SECOND_START"] is True and c["CLOCK_MINUTE_START"] is True
    milieu = CVC.conditions_horloge(debut_minute + 30_500)
    assert milieu["CLOCK_MINUTE_START"] is False
    # les fenêtres sont des constantes du module, pas un réglage issu des données
    assert CVC.FENETRES_HORLOGE["CLOCK_SECOND_START"] == (1_000, 100)


def test_horloge_sans_timestamp_reste_non_mesurable():
    assert all(v is None for v in CVC.conditions_horloge(None).values())


# ═══════════════ deny-by-default ═══════════════
def test_sans_carnet_les_conditions_microstructure_sont_none():
    c = CVC.conditions_microstructure(1)
    for nom in ("OFI_ALIGNE", "OFI_OPPOSE", "SPREAD_TIGHT", "DEPTH_THIN", "VOLATILITY_BURST"):
        assert c[nom] is None, "%s devrait être non mesurable, pas False" % nom


def test_une_condition_none_nest_jamais_retenue():
    mesures = [{"t_choc": 1, "conditions": {"SPREAD_TIGHT": None}},
               {"t_choc": 2, "conditions": {"SPREAD_TIGHT": False}},
               {"t_choc": 3, "conditions": {"SPREAD_TIGHT": True}}]
    gardes = CVC.filtrer_par_condition(mesures, "SPREAD_TIGHT")
    assert [m["t_choc"] for m in gardes] == [3]


def test_nets_horizon_exclut_non_mesurable_sans_le_compter_zero():
    mesures = [{"statut": "OK", "par_horizon": {"500": {"statut": "OK", "net_bps": 2.0}}},
               {"statut": "OK", "par_horizon": {"500": {"statut": "NON_MESURABLE"}}}]
    assert CVC.nets_horizon(mesures, 500) == [2.0]


# ═══════════════ microstructure réelle ═══════════════
def test_ofi_aligne_et_oppose_dependent_du_sens_du_choc():
    avant = resume_book(_book(100.0, 100.02, taille_bid=10.0))
    apres = resume_book(_book(100.0, 100.02, taille_bid=20.0))   # pression acheteuse : OFI > 0
    hausse = CVC.conditions_microstructure(1, resume_avant=avant, resume_apres=apres)
    baisse = CVC.conditions_microstructure(-1, resume_avant=avant, resume_apres=apres)
    assert hausse["OFI_ALIGNE"] is True and hausse["OFI_OPPOSE"] is False
    assert baisse["OFI_ALIGNE"] is False and baisse["OFI_OPPOSE"] is True


def test_regime_de_spread_et_profondeur_mesures():
    serre = CVC.conditions_microstructure(1, resume_apres=resume_book(_book(100.0, 100.02)))
    large = CVC.conditions_microstructure(1, resume_apres=resume_book(_book(100.0, 100.5)))
    assert serre["SPREAD_TIGHT"] is True and serre["SPREAD_WIDE"] is False
    assert large["SPREAD_WIDE"] is True and large["SPREAD_TIGHT"] is False
    assert serre["DEPTH_THIN"] is True and serre["DEPTH_THICK"] is False
    epais = CVC.conditions_microstructure(
        1, resume_apres=resume_book(_book(100.0, 100.02, taille_bid=30_000.0, taille_ask=30_000.0)))
    assert epais["DEPTH_THICK"] is True and epais["DEPTH_THIN"] is False


def test_volatility_burst_mesure_sur_le_mid():
    calme = CVC.conditions_microstructure(1, mid_avant=100.0, mid_apres=100.01)   # 1 bps
    burst = CVC.conditions_microstructure(1, mid_avant=100.0, mid_apres=100.30)   # 30 bps
    assert calme["VOLATILITY_BURST"] is False and burst["VOLATILITY_BURST"] is True


def test_conditionner_nattaque_pas_lentree_et_couvre_toutes_les_conditions():
    mesures = _mesures(2)
    original = dict(mesures[0])
    enrichies = CVC.conditionner(mesures, {mesures[0]["t_choc"]: {"mid_avant": 100.0, "mid_apres": 100.4}})
    assert mesures[0] == original, "l'entrée ne doit pas être mutée"
    assert set(enrichies[0]["conditions"]) == set(CVC.CONDITIONS)
    assert enrichies[0]["conditions"]["VOLATILITY_BURST"] is True


# ═══════════════ embargo ═══════════════
def test_embargo_retire_reellement_les_chocs_trop_proches():
    serres = _mesures(6, pas_ms=1_000)          # 1 s d'écart, embargo 5 s
    assert len(CVC.appliquer_embargo(serres, 5_000)) == 2
    espaces = _mesures(6, pas_ms=10_000)
    assert len(CVC.appliquer_embargo(espaces, 5_000)) == 6


# ═══════════════ registre des essais ═══════════════
def test_plan_essais_preenregistre_et_hashe(tmp_path):
    plan = CVC.plan_essais(familles=("PRICE_SHOCK", "TAKER_BURST"), horizons=(500, 1000))
    assert len(plan) == 2 * len(CVC.CONDITIONS) * 2
    hashes = {e["parameter_hash"] for e in plan}
    assert len(hashes) == len(plan), "chaque essai doit avoir un hash distinct"
    # le hash est déterministe : re-planifier donne exactement les mêmes essais
    assert {e["parameter_hash"] for e in CVC.plan_essais(
        familles=("PRICE_SHOCK", "TAKER_BURST"), horizons=(500, 1000))} == hashes


def test_tous_les_essais_sont_comptes_y_compris_les_kill(tmp_path):
    plan = CVC.plan_essais(familles=("PRICE_SHOCK",), conditions=("SPREAD_TIGHT", "SPREAD_WIDE"), horizons=(500,))
    assert CVC.enregistrer_plan(tmp_path, plan) == 2
    resultats = [{**plan[0], "result": "DISCOVERY_PROBE", "pass_kill": "PASS", "sharpe": 0.8},
                 {**plan[1], "result": "SHADOW_KILL", "pass_kill": "KILL", "sharpe": -0.4}]
    assert CVC.enregistrer_resultats(tmp_path, resultats) == 2
    lignes = registre_essais.charger(tmp_path)
    assert len([x for x in lignes if x["phase"] == "preregistration"]) == 2
    assert len([x for x in lignes if x["phase"] == "resultat"]) == 2
    # le perdant DOIT rester dans la population qui dégonfle le DSR
    sharpes = registre_essais.sharpes_tous_essais(lignes, family=CVC.FAMILLE_REGISTRE)
    assert -0.4 in sharpes and 0.8 in sharpes


# ═══════════════ verdict : jamais une promotion ═══════════════
def test_verdict_refuse_sur_donnees_insuffisantes():
    v = CVC.verdict_conditionne(_mesures(4), 500, min_chocs=20)
    assert v["statut"] == "SHADOW_DONNEES_INSUFFISANTES"
    assert v["pnl_net_bps"] is None and v["promotion_possible"] is False


def test_verdict_ne_promeut_jamais_meme_avec_de_bons_chiffres():
    v = CVC.verdict_conditionne(_mesures(24, net_bps=1.0), 500, min_chocs=5)
    assert v["statut"] in {"DISCOVERY_PROBE", "SHADOW_KILL"}
    assert v["statut"] == "DISCOVERY_PROBE"          # données volontairement favorables
    assert v["promotion_possible"] is False and v["shadow"] is True
    assert v["real_execution"] is False
    assert v["n_apres_embargo"] == 24 and v["n_mesurables"] == 24


def test_verdict_kill_quand_le_net_est_negatif():
    v = CVC.verdict_conditionne(_mesures(24, net_bps=-1.0), 500, min_chocs=5)
    assert v["statut"] == "SHADOW_KILL" and v["pnl_net_bps"] < 0


def test_verdict_applique_lembargo_avant_de_juger():
    v = CVC.verdict_conditionne(_mesures(40, pas_ms=1_000), 500, min_chocs=5, embargo_ms=5_000)
    assert v["n_avant_embargo"] == 40 and v["n_apres_embargo"] == 8


# ═══════════════ sécurité ═══════════════
def test_securite_aucun_appel_reel():
    src = (RACINE / "src" / "hl_observer" / "experimental" / "cross_venue_conditions.py").read_text(encoding="utf-8")
    for interdit in ('"/exchange"', "'/exchange'", "requests.get", "requests.post", "import websocket",
                     "websockets.connect", "eth_account", "Account.from_key", "private_key"):
        assert interdit not in src, "appel interdit dans cross_venue_conditions: %s" % interdit
