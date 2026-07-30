"""§12/§13 — robustesse OOS du scoring + sémantique copy par action.

Le test qui porte le sens : `test_les_fills_dun_meme_metaordre_comptent_pour_un_seul_vote`. 3 686 fills
corrélés ne sont pas 3 686 preuves.

Paper/read-only : 0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.following import scoring_robuste as SR  # noqa: E402

JOUR = 86_400_000


# ═══════════════ §12.1 — pseudo-réplication ═══════════════
def test_les_fills_dun_meme_metaordre_comptent_pour_un_seul_vote():
    eps = [{"metaorder_id": "m1", "net_bps": 10.0} for _ in range(3_686)]
    agg = SR.agreger_en_grappes(eps)
    assert agg["n_fills"] == 3_686 and agg["n_votes_independants"] == 1
    assert agg["facteur_replication"] == 3686.0


def test_deux_metaordres_donnent_deux_votes():
    eps = [{"metaorder_id": "m1", "net_bps": 10.0}] * 5 + [{"metaorder_id": "m2", "net_bps": -4.0}] * 5
    agg = SR.agreger_en_grappes(eps)
    assert agg["n_votes_independants"] == 2 and sorted(agg["votes_bps"]) == [-4.0, 10.0]


def test_sans_metaorder_la_grappe_retombe_sur_wallet_coin_jour():
    e = {"wallet": "0xa", "coin": "BTC", "ts_ms": 2 * JOUR + 100, "net_bps": 1.0}
    assert SR.cle_grappe(e).startswith("wcj:0xa:BTC:2")


# ═══════════════ §12.2 — critères CORE au-delà de N ═══════════════
def _eps_independants(n, net=5.0, coins=("BTC",), regimes=("calme", "actif"), jours=5):
    out = []
    for i in range(n):
        out.append({"metaorder_id": "m%d" % i, "net_bps": net,
                    "coin": coins[i % len(coins)], "regime": regimes[i % len(regimes)],
                    "ts_ms": (i % jours) * JOUR + 1})
    return out


def test_un_wallet_avec_peu_de_votes_independants_nest_pas_core():
    eps = [{"metaorder_id": "m1", "net_bps": 50.0, "coin": "BTC", "regime": "calme", "ts_ms": JOUR}] * 100
    c = SR.critere_core(eps)
    assert c["eligible_core"] is False and "VOTES_INDEPENDANTS_INSUFFISANTS" in c["raisons"]


def test_un_wallet_sur_un_seul_jour_nest_pas_core():
    eps = [{"metaorder_id": "m%d" % i, "net_bps": 5.0, "coin": "BTC", "regime": "calme", "ts_ms": JOUR}
           for i in range(30)]
    c = SR.critere_core(eps)
    assert c["eligible_core"] is False and "PAS_ASSEZ_DE_JOURS" in c["raisons"]


def test_une_borne_basse_non_positive_bloque_le_core():
    # net moyen ~0 avec bruit : la borne basse de l'IC est <= 0
    eps = []
    for i in range(40):
        eps.append({"metaorder_id": "m%d" % i, "net_bps": (5.0 if i % 2 else -5.0),
                    "coin": "BTC", "regime": ("calme" if i % 2 else "actif"), "ts_ms": (i % 5) * JOUR})
    c = SR.critere_core(eps)
    assert c["eligible_core"] is False and "BORNE_BASSE_NON_POSITIVE" in c["raisons"]


def test_un_wallet_solide_est_eligible_core():
    c = SR.critere_core(_eps_independants(40, net=8.0))
    assert c["eligible_core"] is True and c["borne_basse_bps"] > 0


# ═══════════════ §12.3 — biais de sélection ═══════════════
def test_decouverte_et_validation_sont_disjointes_dans_le_temps():
    eps = [{"ts_ms": i * JOUR, "net_bps": 1.0} for i in range(10)]
    s = SR.separer_decouverte_validation(eps, fraction_decouverte=0.6)
    assert len(s["decouverte"]) == 6 and len(s["validation"]) == 4 and s["disjointes"] is True
    t_dec = max(e["ts_ms"] for e in s["decouverte"])
    t_val = min(e["ts_ms"] for e in s["validation"])
    assert t_val >= t_dec                                 # aucune fuite temporelle


# ═══════════════ §12.5 — expiration ═══════════════
def test_un_edge_recent_negatif_retrograde_le_wallet():
    now = 100 * JOUR
    eps = [{"ts_ms": now - i * 3600_000, "net_bps": -8.0} for i in range(10)]
    s = SR.statut_expiration(eps, now_ms=now)
    assert s["statut"] == "RETROGRADE" and s["peut_rester_core"] is False


def test_un_edge_recent_positif_maintient_le_core():
    now = 100 * JOUR
    eps = [{"ts_ms": now - i * 3600_000, "net_bps": 6.0} for i in range(10)]
    s = SR.statut_expiration(eps, now_ms=now)
    assert s["statut"] == "CORE_MAINTENU" and s["peut_rester_core"] is True


def test_sans_activite_recente_le_core_nest_pas_prolonge():
    now = 100 * JOUR
    eps = [{"ts_ms": 1 * JOUR, "net_bps": 20.0} for _ in range(10)]   # tout est vieux
    s = SR.statut_expiration(eps, now_ms=now)
    assert s["statut"] == "GEL_INSUFFISANCE_RECENTE" and s["peut_rester_core"] is False


# ═══════════════ §13 — sémantique copy par action ═══════════════
def test_open_est_le_candidat_principal():
    d = SR.decision_copy("OPEN")
    assert d["action_copy"] == "OUVRIR" and d["ouvre_inverse"] is False


def test_reduce_ne_ouvre_jamais_le_sens_inverse():
    d = SR.decision_copy("REDUCE", avons_position=True)
    assert d["action_copy"] == "REDUIRE" and d["ouvre_inverse"] is False
    # sans position, on n'invente pas une entree inverse
    d2 = SR.decision_copy("REDUCE", avons_position=False)
    assert d2["action_copy"] == "IGNORER" and d2["ouvre_inverse"] is False


def test_add_nest_copie_quavec_position_capacite_et_edge():
    ok = SR.decision_copy("ADD", avons_position=True, capacite_restante=True, edge_residuel_positif=True)
    non = SR.decision_copy("ADD", avons_position=True, capacite_restante=False, edge_residuel_positif=True)
    assert ok["action_copy"] == "AJOUTER" and non["action_copy"] == "IGNORER"


def test_le_flip_ferme_puis_decide_separement():
    d = SR.decision_copy("FLIP", avons_position=True)
    assert d["action_copy"] == "FERMER_PUIS_DECIDER" and d["ouvre_inverse"] is False


def test_les_variantes_de_copie_sont_declarees():
    v = SR.variantes_de_copie()
    assert "OPEN_SEUL" in v and "SUIVRE_LEADER_EXIT" in v and "TIME_STOP" in v


def test_securite_aucun_appel_reel():
    src = (RACINE / "src" / "hl_observer" / "following" / "scoring_robuste.py").read_text(encoding="utf-8")
    for interdit in ('"/exchange"', "'/exchange'", "requests.get", "requests.post", "import websocket",
                     "websockets.connect", "eth_account", "Account.from_key", "private_key"):
        assert interdit not in src, "appel interdit dans scoring_robuste: %s" % interdit
