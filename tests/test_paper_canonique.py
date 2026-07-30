"""§5/§6/§7 — moteur paper canonique, exécution réaliste, runtime-truth.

Deux verrous de scope prouvés ici : le carry NE PEUT PAS émettre d'intent (ScopeViolation), et runtime-truth
le liste toujours `DISABLED_BY_SCOPE`. Plus les invariants d'exécution : liquidité non re-consommable,
partial fill à résidu explicite, maker non mesurable, carnet non fiable = pas d'entrée.

Paper/read-only : 0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import paper_canonique as PC  # noqa: E402


# ═══════════════ §5 + scope : le carry ne peut pas émettre d'intent ═══════════════
def test_une_strategie_active_peut_emettre_un_intent():
    i = PC.PaperIntent(strategy="cross_venue_dislocation", coin="btc", side=1,
                       notional_usd=50.0, signal_observable_at_ms=1)
    assert i.as_dict()["coin"] == "BTC" and i.as_dict()["real_execution"] is False


@pytest.mark.parametrize("legacy", ["carry", "funding", "triangular", "market_making"])
def test_le_carry_et_le_legacy_ne_peuvent_pas_emettre_dintent(legacy):
    with pytest.raises(PC.ScopeViolation):
        PC.PaperIntent(strategy=legacy, coin="BTC", side=1, notional_usd=50.0, signal_observable_at_ms=1)


def test_les_cinq_strategies_actives_sont_le_scope_declare():
    assert set(PC.STRATEGIES_ACTIVES) == {"cross_venue_dislocation", "lead_lag", "copy_wallet",
                                          "copy_vault", "twap_metaorder"}
    assert "carry" not in PC.STRATEGIES_ACTIVES and "carry" in PC.STRATEGIES_LEGACY_OFF


def test_un_side_invalide_est_refuse():
    with pytest.raises(ValueError):
        PC.PaperIntent(strategy="lead_lag", coin="BTC", side=0, notional_usd=50.0, signal_observable_at_ms=1)


# ═══════════════ §6.2 — consommation de liquidité ═══════════════
def test_une_profondeur_consommee_nest_pas_reutilisable_sur_le_meme_snapshot():
    l = PC.LiquidityConsumptionLedger()
    a = l.consommer(venue="HL", coin="BTC", side=1, price_level=100.0, snapshot_version="v1",
                    quantite=6.0, profondeur_affichee=10.0)
    b = l.consommer(venue="HL", coin="BTC", side=1, price_level=100.0, snapshot_version="v1",
                    quantite=6.0, profondeur_affichee=10.0)
    assert a["consomme"] == 6.0 and b["consomme"] == 4.0 and b["refuse"] == 2.0


def test_un_nouveau_snapshot_reapprovisionne_la_liquidite():
    l = PC.LiquidityConsumptionLedger()
    l.consommer(venue="HL", coin="BTC", side=1, price_level=100.0, snapshot_version="v1",
                quantite=10.0, profondeur_affichee=10.0)
    c = l.consommer(venue="HL", coin="BTC", side=1, price_level=100.0, snapshot_version="v2",
                    quantite=4.0, profondeur_affichee=10.0)
    assert c["consomme"] == 4.0


def test_les_cotes_opposes_sont_des_files_distinctes():
    l = PC.LiquidityConsumptionLedger()
    l.consommer(venue="HL", coin="BTC", side=1, price_level=100.0, snapshot_version="v1",
                quantite=10.0, profondeur_affichee=10.0)
    c = l.consommer(venue="HL", coin="BTC", side=-1, price_level=100.0, snapshot_version="v1",
                    quantite=5.0, profondeur_affichee=10.0)
    assert c["consomme"] == 5.0


# ═══════════════ §6.3 — fills partiels ═══════════════
def test_une_taille_superieure_a_la_profondeur_laisse_un_residu_explicite():
    r = PC.remplir_partiellement(15.0, [(100.0, 5.0), (100.1, 5.0)])
    assert r["statut"] == "PARTIEL" and r["rempli"] == 10.0 and r["residu"] == 5.0
    assert r["fill_ratio"] == round(10 / 15, 6)


def test_le_vwap_est_pondere_par_les_niveaux_consommes():
    r = PC.remplir_partiellement(10.0, [(100.0, 5.0), (110.0, 5.0)])
    assert r["statut"] == "COMPLET" and r["vwap"] == 105.0 and r["residu"] == 0.0


def test_un_carnet_vide_ne_remplit_rien():
    r = PC.remplir_partiellement(10.0, [])
    assert r["rempli"] == 0.0 and r["residu"] == 10.0 and r["vwap"] is None


# ═══════════════ §6.4 — maker ═══════════════
def test_sans_file_mesuree_le_maker_est_unmeasurable():
    r = PC.fill_maker(file_devant_nous=None, volume_traversant=100.0, taille=5.0)
    assert r["statut"] == "MAKER_FILL_UNMEASURABLE" and r["rempli"] is None


def test_le_maker_nest_rempli_que_par_le_volume_au_dela_de_la_file():
    plein = PC.fill_maker(file_devant_nous=10.0, volume_traversant=18.0, taille=5.0)
    rien = PC.fill_maker(file_devant_nous=10.0, volume_traversant=8.0, taille=5.0)
    assert plein["rempli"] == 5.0                       # 18 - 10 = 8 >= 5
    assert rien["rempli"] == 0.0                        # 8 - 10 < 0 : la file n'est meme pas franchie


# ═══════════════ §6.5 — carnet fiable ═══════════════
def test_un_gap_de_sequence_interdit_lentree():
    r = PC.carnet_fiable(sequence=105, derniere_sequence=100, age_ms=10.0, age_max_ms=1_000.0)
    assert r["entree_autorisee"] is False and "GAP_DE_SEQUENCE" in r["raisons"]


def test_un_carnet_stale_interdit_lentree():
    r = PC.carnet_fiable(sequence=101, derniere_sequence=100, age_ms=5_000.0, age_max_ms=1_000.0)
    assert r["entree_autorisee"] is False and "STALE" in r["raisons"]


def test_out_of_order_et_skew_sont_detectes():
    ooo = PC.carnet_fiable(sequence=99, derniere_sequence=100, age_ms=10.0, age_max_ms=1_000.0)
    skew = PC.carnet_fiable(sequence=101, derniere_sequence=100, age_ms=10.0, age_max_ms=1_000.0,
                            skew_ms=5_000.0, skew_max_ms=1_000.0)
    assert "OUT_OF_ORDER" in ooo["raisons"] and "SKEW_HORLOGE" in skew["raisons"]


def test_un_carnet_sain_autorise_lentree():
    r = PC.carnet_fiable(sequence=101, derniere_sequence=100, age_ms=50.0, age_max_ms=1_000.0, skew_ms=10.0)
    assert r["fiable"] is True and r["raisons"] == []


# ═══════════════ §7 — runtime-truth ═══════════════
def test_un_flag_on_sans_producteur_est_off_de_fait():
    obs = {"lead_lag": {"flag_on": True, "producer_alive": False}}
    rt = PC.runtime_truth(obs, now_ms=1_000_000)
    assert rt["strategies_actives"]["lead_lag"]["etat"] == "ON_SANS_PRODUCTEUR"


def test_une_strategie_avec_chaine_complete_est_vivante():
    obs = {"copy_vault": {"flag_on": True, "producer_alive": True, "last_event_ms": 999_000,
                          "signal_path_alive": True, "execution_engine_alive": True, "ledger_writable": True}}
    rt = PC.runtime_truth(obs, now_ms=1_000_000, age_max_ms=120_000)
    assert rt["strategies_actives"]["copy_vault"]["etat"] == "VIVANT"


def test_un_producteur_trop_vieux_nest_pas_vivant():
    obs = {"copy_vault": {"flag_on": True, "producer_alive": True, "last_event_ms": 1_000,
                          "signal_path_alive": True, "execution_engine_alive": True, "ledger_writable": True}}
    rt = PC.runtime_truth(obs, now_ms=1_000_000, age_max_ms=120_000)
    assert rt["strategies_actives"]["copy_vault"]["etat"] == "ON_SANS_PRODUCTEUR"


def test_le_carry_est_toujours_disabled_by_scope_dans_runtime_truth():
    rt = PC.runtime_truth({}, now_ms=1_000_000)
    assert rt["legacy_off"]["carry"] == "DISABLED_BY_SCOPE"
    assert "carry" not in rt["strategies_actives"]


def test_securite_aucun_appel_reel():
    src = (RACINE / "src" / "hl_observer" / "ops" / "paper_canonique.py").read_text(encoding="utf-8")
    for interdit in ('"/exchange"', "'/exchange'", "requests.get", "requests.post", "import websocket",
                     "websockets.connect", "eth_account", "Account.from_key", "private_key"):
        assert interdit not in src, "appel interdit dans paper_canonique: %s" % interdit
