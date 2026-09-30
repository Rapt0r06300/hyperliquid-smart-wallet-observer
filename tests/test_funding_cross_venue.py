"""#365 / H-137 -- funding cross-venue, et **LE PIEGE D'UNITE**.

🔴 LE TEST LE PLUS IMPORTANT DE CE FICHIER : `test_l_exemple_de_la_doc_donne_ZERO_ecart`.

Ma 1re version de ce module annoncait **38 % APR** sur l'exemple de la doc Hyperliquid, parce
qu'elle comparait un taux **8 heures** (Binance) avec un taux **1 heure** (HL). Les trois venues
de cet exemple sont en realite **EXACTEMENT d'accord** (0.0001 / 8 = 0.0000125).

C'est le **bid-ask bounce de T1b en costume neuf** : comparer deux nombres qui ne sont pas dans
la meme unite, et recolter un edge fantome. Ce test existe pour que ca ne revienne JAMAIS.
"""
from __future__ import annotations

import pytest

from hl_observer.funding.funding_cross_venue import (
    CAPITAL_SUR_DEUX_VENUES,
    COUT_4_EXECUTIONS_BPS,
    INTERVALLE_FUNDING_HEURES,
    MOTIF_ECART_MESURE,
    MOTIF_ECART_TROP_FAIBLE,
    MOTIF_INTERVALLE_INCONNU,
    MOTIF_RAPPORT_SUSPECT,
    MOTIF_UNE_SEULE_VENUE,
    TauxVenue,
    evaluer_coin,
    parser_predicted_fundings,
    rapport_suspect,
    resume,
)
from hl_observer.hyperliquid.rest_info_client import (
    READ_ONLY_INFO_TYPES,
    HyperliquidInfoError,
    _ensure_read_only_payload,
    build_funding_history_payload,
    build_predicted_fundings_payload,
)

# L'exemple EXACT de la doc officielle (for-developers/api/info-endpoint/perpetuals).
PAYLOAD_DOC = [
    ["AVAX", [
        ["BinPerp", {"fundingRate": "0.0001", "nextFundingTime": 1733961600000}],
        ["HlPerp", {"fundingRate": "0.0000125", "nextFundingTime": 1733958000000}],
        ["BybitPerp", {"fundingRate": "0.0001", "nextFundingTime": 1733961600000}],
    ]],
]


# ════════════════════════════════════════════════════════════════════════════════════════════
# 1. 🔴 LE PIEGE D'UNITE — le test qui garde ma propre erreur
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_les_intervalles_sont_sources_pas_devines() -> None:
    """Doc HL : « paid every hour », « one eighth of the computed [8h] rate »."""
    assert INTERVALLE_FUNDING_HEURES["HlPerp"] == 1.0
    assert INTERVALLE_FUNDING_HEURES["BinPerp"] == 8.0
    assert INTERVALLE_FUNDING_HEURES["BybitPerp"] == 8.0


def test_la_normalisation_ramene_tout_en_bps_par_HEURE() -> None:
    """0.0001 sur 8 h == 0.0000125 sur 1 h == 0,125 bps/h. Le MEME taux."""
    bin8 = TauxVenue("BinPerp", 0.0001, 8.0)
    hl1 = TauxVenue("HlPerp", 0.0000125, 1.0)
    assert bin8.bps_h == pytest.approx(0.125)
    assert hl1.bps_h == pytest.approx(0.125)
    assert bin8.bps_h == pytest.approx(hl1.bps_h)


def test_l_exemple_de_la_doc_donne_ZERO_ecart() -> None:
    """🔴🔴🔴 LE TEST QUI GARDE LE BUG.

    Ma 1re version annoncait ici **+0,875 bps/h -> 38 % APR**. C'etait l'INTERVALLE DE FUNDING,
    pas un edge. Les 3 venues de l'exemple officiel sont EXACTEMENT d'accord.
    """
    d = parser_predicted_fundings(PAYLOAD_DOC)
    e = evaluer_coin("AVAX", d["AVAX"])

    assert e.ecart_bps_h == pytest.approx(0.0, abs=1e-9), (
        "Les 3 venues de la doc paient le MEME funding (0.0001/8h == 0.0000125/1h). "
        "Un ecart non nul ici = le bug d'unite est revenu."
    )
    assert e.exploitable is False
    assert e.ecart_sur_capital_bps_h == pytest.approx(0.0, abs=1e-9)
    assert e.heures_pour_amortir is None      # pas d'infini fabrique


def test_le_bug_original_reproduit_sans_normalisation_prouve_le_piege() -> None:
    """Si on pretend (a tort) que tout le monde est en 1 h, le faux edge REVIENT.

    C'est la preuve que le bug etait bien dans l'UNITE, pas ailleurs.
    """
    faux = {"BinPerp": 1.0, "HlPerp": 1.0, "BybitPerp": 1.0}   # <- l'erreur d'origine
    d = parser_predicted_fundings(PAYLOAD_DOC, intervalles=faux)
    e = evaluer_coin("AVAX", d["AVAX"])
    # Le garde anti-rapport-suspect l'attrape AVANT qu'on annonce un edge.
    assert e.exploitable is False
    assert e.motif == MOTIF_RAPPORT_SUSPECT
    assert "8" in e.note


# ════════════════════════════════════════════════════════════════════════════════════════════
# 2. Le garde anti-erreur-d'unite
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_le_garde_NE_TIRE_PAS_sur_le_rapport_deja_declare() -> None:
    """HL 1h vs Binance 8h -> rapport brut 8 ATTENDU. La normalisation le regle : pas de refus."""
    assert rapport_suspect(TauxVenue("BinPerp", 0.0001, 8.0),
                           TauxVenue("HlPerp", 0.0000125, 1.0)) is None


def test_le_garde_TIRE_si_la_vraie_periode_n_est_pas_celle_de_notre_table() -> None:
    """Une paire Binance passee en funding 4 h : rapport brut 4, alors qu'on a declare 8.

    Sans ce garde, on normaliserait par 8 et on verrait un ecart FANTOME.
    """
    cible = rapport_suspect(TauxVenue("BinPerp", 0.00005, 8.0),     # 4h en realite
                            TauxVenue("HlPerp", 0.0000125, 1.0))
    assert cible == 4.0


def test_un_ecart_economique_ordinaire_n_est_PAS_refuse() -> None:
    """1,37x entre deux venues 8h : ce n'est aucun rapport de periode. On le laisse passer."""
    assert rapport_suspect(TauxVenue("BinPerp", 0.000137, 8.0),
                           TauxVenue("BybitPerp", 0.0001, 8.0)) is None


def test_un_taux_nul_ne_fait_pas_exploser_le_garde() -> None:
    assert rapport_suspect(TauxVenue("A", 0.0, 8.0), TauxVenue("B", 0.0001, 8.0)) is None


# ════════════════════════════════════════════════════════════════════════════════════════════
# 3. Deny-by-default : sur la donnee ET sur l'unite
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_une_venue_inconnue_est_ECARTEE_jamais_normalisee_au_hasard() -> None:
    """*Une unite inconnue est PIRE qu'une donnee absente : elle produit un chiffre credible.*"""
    d = parser_predicted_fundings([["AVAX", [
        ["HlPerp", {"fundingRate": "0.0000125"}],
        ["OkxPerp", {"fundingRate": "0.0004"}],       # intervalle inconnu de notre table
    ]]])
    okx = [t for t in d["AVAX"] if t.venue == "OkxPerp"][0]
    assert okx.intervalle_h is None and not okx.normalisable
    with pytest.raises(ValueError):
        _ = okx.bps_h                                  # on REFUSE de le convertir

    e = evaluer_coin("AVAX", d["AVAX"])
    assert e.motif == MOTIF_INTERVALLE_INCONNU
    assert e.venues_ecartees == ("OkxPerp",)
    assert not e.exploitable


def test_un_taux_manquant_est_ECARTE_jamais_remplace_par_zero() -> None:
    d = parser_predicted_fundings([["AVAX", [
        ["BinPerp", {"fundingRate": "0.0001"}],
        ["HlPerp", {"nextFundingTime": 1}],            # PAS de fundingRate
        ["BybitPerp", {"fundingRate": "pas-un-nombre"}],
    ]]])
    assert [t.venue for t in d["AVAX"]] == ["BinPerp"]
    assert evaluer_coin("AVAX", d["AVAX"]).motif == MOTIF_UNE_SEULE_VENUE


@pytest.mark.parametrize("payload", [None, {}, "x", [], [["AVAX"]], [["", []]], [[None, None]]])
def test_payload_malforme_ne_leve_pas_et_ne_fabrique_rien(payload: object) -> None:
    assert parser_predicted_fundings(payload) == {}


# ════════════════════════════════════════════════════════════════════════════════════════════
# 4. Les couts, et le capital sur DEUX venues (lecon T2b)
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_le_rendement_est_divise_par_DEUX_venues() -> None:
    """T2 annoncait 4 % ; T2b a montre 2 %. Ici le capital est sur deux VENUES."""
    taux = [TauxVenue("HlPerp", 0.0, 1.0), TauxVenue("BinPerp", 0.0080, 8.0)]  # 10 bps/h
    e = evaluer_coin("X", taux)
    assert e.ecart_bps_h == pytest.approx(10.0)
    assert e.ecart_sur_capital_bps_h == pytest.approx(10.0 / CAPITAL_SUR_DEUX_VENUES)
    assert e.ecart_sur_capital_bps_h < e.ecart_bps_h


def test_on_short_la_venue_qui_paie_le_plus_APRES_normalisation() -> None:
    """Le classement doit se faire en bps/h, PAS sur les taux bruts.

    Ici Binance a le taux BRUT le plus haut (0.0004 > 0.0001) mais, ramene a l'heure,
    c'est **HL** qui paie le plus (1,0 bps/h contre 0,5). Sur les bruts, on se tromperait de sens.
    """
    e = evaluer_coin("X", [TauxVenue("BinPerp", 0.0004, 8.0),    # 0,5 bps/h
                           TauxVenue("HlPerp", 0.0001, 1.0)])    # 1,0 bps/h
    assert e.venue_qui_encaisse == "HlPerp"
    assert e.venue_qui_paie == "BinPerp"
    assert e.ecart_bps_h == pytest.approx(0.5)


def test_ecart_trop_faible_pour_amortir_4_executions_est_REFUSE() -> None:
    e = evaluer_coin("X", [TauxVenue("HlPerp", 0.00001, 1.0),    # 0,1 bps/h
                           TauxVenue("BinPerp", 0.0, 8.0)])
    assert not e.exploitable and e.motif == MOTIF_ECART_TROP_FAIBLE
    assert e.heures_pour_amortir == pytest.approx(COUT_4_EXECUTIONS_BPS / 0.1)


def test_un_ecart_reellement_gros_est_exploitable_et_le_dit_honnetement() -> None:
    e = evaluer_coin("X", [TauxVenue("HlPerp", 0.0, 1.0), TauxVenue("BinPerp", 0.0080, 8.0)])
    assert e.exploitable and e.motif == MOTIF_ECART_MESURE
    d = e.as_dict()
    assert d["real_execution"] is False
    assert "BINANCE" in d["avertissement"].upper()
    assert "HEURE" in d["unite"].upper()


def test_resume_dit_le_piege_et_qu_on_ne_peut_pas_capturer() -> None:
    r = resume([evaluer_coin("AVAX", parser_predicted_fundings(PAYLOAD_DOC)["AVAX"])])
    assert r["n_exploitables"] == 0
    assert r["real_execution"] is False
    assert "38 %" in r["piege_documente"]
    assert "ne capture rien" in r["avertissement"]


# ════════════════════════════════════════════════════════════════════════════════════════════
# 5. 🔒 SECURITE : les deux endpoints sont /info et ne peuvent RIEN executer
# ════════════════════════════════════════════════════════════════════════════════════════════
def test_les_deux_endpoints_sont_lecture_seule() -> None:
    for p in (build_predicted_fundings_payload(), build_funding_history_payload("BTC", 0)):
        _ensure_read_only_payload(p)
        assert p["type"] in READ_ONLY_INFO_TYPES
        assert "signature" not in p and "action" not in p and "user" not in p


def test_elargir_l_allowlist_ne_l_a_pas_OUVERTE() -> None:
    for interdit in ("order", "cancel", "withdraw3", "usdSend", "exchange", None):
        with pytest.raises(HyperliquidInfoError):
            _ensure_read_only_payload({"type": interdit})


def test_funding_history_refuse_un_intervalle_inverse() -> None:
    with pytest.raises(ValueError):
        build_funding_history_payload("BTC", start_time=10, end_time=5)
