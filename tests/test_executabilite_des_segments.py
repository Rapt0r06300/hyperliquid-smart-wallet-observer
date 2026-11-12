"""L2 — la même sonde sur CHAQUE segment : « non mesuré » n'est pas « validé ».

La sonde d'origine (posée le 12/11) ne regardait que TRAIN : elle empêchait de CHERCHER à vide, mais
pas de VALIDER à vide. Or un segment où aucun trade n'est exécutable produit zéro trade, donc zéro
perte, donc un résultat qui FRANCHIT les portes sans avoir rien mesuré — un faux PROVEN. C'est
exactement le mensonge que ce projet combat, et c'était un trou dans ce qui venait d'être construit.

Ces tests verrouillent les deux moitiés :

1. la sonde dit, segment par segment, s'il contient au moins un trade exécutable ;
2. la **porte de promotion** REFUSE quand un segment n'est pas mesurable, même si tout le reste est
   parfait (PnL positif, profit factor élevé, parité prouvée...).
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import copy_vault_executable as cv  # noqa: E402
from hl_observer.backtesting import copy_vault_train_executability as S  # noqa: E402
from hl_observer.backtesting import promotion_gate as P  # noqa: E402

T0 = 1_800_000_600_000                 # dix minutes après l'heure pile : aucun funding traversé
HORIZON = (30_000,)                    # un seul horizon court : des carnets légers suffisent

# Trois fenêtres disjointes, comme la découpe réelle (train / validation / oos avec purge).
BORNES = {
    "train_start_ms": T0, "train_end_ms": T0 + 100_000,
    "validation_start_ms": T0 + 200_000, "validation_end_ms": T0 + 300_000,
    "oos_start_ms": T0 + 400_000, "oos_end_ms": T0 + 500_000,
}


def _carnet(ts: int, *, ligne: int, connexion: str = "cx", epoque: int = 0) -> dict:
    bid = 100.0
    ask = bid + 2.0
    return {"coin": "ETH", "ts_ms": ts, "bid": bid, "ask": ask, "capacity_usd": 50_000.0,
            "bids5": [[bid, 500.0]], "asks5": [[ask, 500.0]], "source_line": ligne,
            "causal_observation": True, "connection_id": connexion, "l2_gap_epoch": epoque}


def _carnets(depart: int, fin: int, *, pas: int = 1_000) -> list[dict]:
    return [_carnet(ts, ligne=i + 1) for i, ts in enumerate(range(depart, fin + 1, pas))]


def _signal(ts: int, identifiant: str) -> dict:
    entree = {"event_id": identifiant, "ts_ms": ts, "coin": "ETH", "direction": 1, "action": "ADD",
              "dir": "Open Long", "vault": "0xA", "taille_usd": 100.0, "move_frac": 0.01,
              "source": "LIVE_WS", "is_snapshot": False,
              "observed_at_ms": ts + 25, "received_at_ms": ts + 25}
    metaordres, _audit = cv.cluster_metaorders([entree])      # (metaordres, audit) : surtout pas [0] seul
    return metaordres[0]


def _signaux_dans_les_trois_segments() -> list[dict]:
    """Un signal dans chaque fenetre : chaque segment a donc quelque chose a executer."""
    return [_signal(T0 + 10_000, "train"),
            _signal(T0 + 210_000, "validation"),
            _signal(T0 + 410_000, "oos")]


# ------------------------------------------------------------------ la sonde par segment

def test_les_trois_segments_sont_sondes_separement():
    metas = _signaux_dans_les_trois_segments()
    carnets = {"ETH": _carnets(T0 - 60_000, T0 + 600_000)}
    r = S.sonder_les_segments(metas, carnets, BORNES, horizons_ms=HORIZON)
    assert set(r["par_segment"]) == {"train", "validation", "oos"}
    for nom in ("train", "validation", "oos"):
        assert r["par_segment"][nom]["segment"] == nom
        assert r["par_segment"][nom]["debut_ms"] == BORNES[f"{nom}_start_ms"]


def test_un_segment_SANS_trade_executable_rend_tout_non_mesurable():
    """LE cas qui comptait : les carnets ne couvrent que TRAIN, donc validation et oos ne peuvent
    rien executer — et on ne doit surtout pas les considerer comme « valides »."""
    metas = _signaux_dans_les_trois_segments()
    carnets = {"ETH": _carnets(T0 - 60_000, T0 + 120_000)}        # rien apres TRAIN
    r = S.sonder_les_segments(metas, carnets, BORNES, horizons_ms=HORIZON)
    assert r["tous_mesurables"] is False
    assert r["raison"] == S.RAISON_SEGMENT
    assert "validation" in r["segments_non_mesurables"]
    assert "oos" in r["segments_non_mesurables"]
    assert r["par_segment"]["validation"]["mesurable"] is False
    assert r["par_segment"]["validation"]["refus_par_motif"]      # on sait POURQUOI
    assert "NON mesurable" in r["lecture"]


def test_la_lecture_nomme_les_segments_fautifs():
    metas = _signaux_dans_les_trois_segments()
    r = S.sonder_les_segments(metas, {"ETH": _carnets(T0 - 60_000, T0 + 120_000)},
                              BORNES, horizons_ms=HORIZON)
    assert "oos" in r["lecture"] and "aucune validation possible" in r["lecture"]


def test_un_segment_absent_des_bornes_est_signale_et_non_compte():
    partielles = {k: v for k, v in BORNES.items() if not k.startswith("oos")}
    r = S.sonder_les_segments(_signaux_dans_les_trois_segments(),
                              {"ETH": _carnets(T0 - 60_000, T0 + 600_000)},
                              partielles, horizons_ms=HORIZON)
    assert r["segments_absents_des_bornes"] == ["oos"]
    assert "oos" not in r["par_segment"]


def test_sans_aucune_borne_on_ne_declare_PAS_mesurable():
    """Deny-by-default : ne rien avoir sonde n'est pas « tout va bien »."""
    r = S.sonder_les_segments([], {}, {}, horizons_ms=HORIZON)
    assert r["tous_mesurables"] is False
    assert r["par_segment"] == {}
    assert "rien n'a pu etre sonde" in r["lecture"]


def test_sonder_un_segment_rend_None_si_ses_bornes_manquent():
    assert S.sonder_un_segment([], {}, {}, "validation", horizons_ms=HORIZON) is None


def test_la_sonde_TRAIN_d_origine_est_intacte():
    """Non-regression : la sonde TRAIN garde sa signature et ses cles (le labo l'appelle)."""
    metas = _signaux_dans_les_trois_segments()
    r = S.sonder_train(metas, {"ETH": _carnets(T0 - 60_000, T0 + 600_000)}, BORNES,
                       horizons_ms=HORIZON)
    for cle in ("executable", "raison", "signaux_train", "par_coin", "coins_a_collecter"):
        assert cle in r


# ------------------------------------------------------------------ la porte REFUSE

def _dossier_parfait() -> dict:
    """Un dossier qui passe TOUS les autres criteres : seul le segment doit pouvoir le bloquer."""
    return {
        "pnl_paper": 42.0, "profit_factor": 2.0, "n_trades": 100,
        "survit": True, "parite_ok": True,
        "candidate_id": "cand-1", "evidence_candidate_id": "cand-1",
        "validation_stage": "FORWARD_PAPER_POST_FREEZE",
        "frozen_at_ms": 1_000, "observed_at_ms": 2_000,
        "replay_pipeline_hash": "h", "forward_pipeline_hash": "h",
    }


def test_un_dossier_parfait_mais_un_segment_non_mesurable_RESTE_PAPER():
    """Le faux PROVEN qu'on empeche : zero trade executable = zero perte = un resultat qui passait."""
    v = P.decision_promotion(**_dossier_parfait(),
                             executabilite_des_segments={"tous_mesurables": False,
                                                         "segments_non_mesurables": ["oos"]})
    assert v.decision == P.RESTE_PAPER
    assert "SEGMENT_NON_MESURABLE_AUCUN_TRADE_EXECUTABLE" in v.motifs
    assert v.real_execution is False


def test_le_meme_dossier_avec_tous_les_segments_mesurables_passe():
    v = P.decision_promotion(**_dossier_parfait(),
                             executabilite_des_segments={"tous_mesurables": True,
                                                         "segments_non_mesurables": []})
    assert v.decision == P.PROMOUVOIR_TESTNET
    assert v.motifs == ()


def test_une_preuve_ambigue_est_traitee_comme_un_refus():
    """`tous_mesurables` absent ou autre que True : on ne promeut jamais dans le doute."""
    for preuve in ({}, {"tous_mesurables": None}, {"tous_mesurables": "oui"}):
        v = P.decision_promotion(**_dossier_parfait(), executabilite_des_segments=preuve)
        assert v.decision == P.RESTE_PAPER
        assert "SEGMENT_NON_MESURABLE_AUCUN_TRADE_EXECUTABLE" in v.motifs


def test_sans_preuve_le_comportement_d_origine_est_conserve():
    """Compatibilite : les appelants existants (et leurs tests) ne changent pas de verdict."""
    v = P.decision_promotion(**_dossier_parfait())
    assert v.decision == P.PROMOUVOIR_TESTNET


def test_on_peut_EXIGER_la_preuve_et_alors_son_absence_refuse():
    criteres = P.CriteresPromotion(exige_segments_mesurables=True)
    v = P.decision_promotion(**_dossier_parfait(), criteres=criteres)
    assert v.decision == P.RESTE_PAPER
    assert "PREUVE_D_EXECUTABILITE_DES_SEGMENTS_MANQUANTE" in v.motifs
