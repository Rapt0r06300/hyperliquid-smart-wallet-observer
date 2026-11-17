"""COLLECTEUR D'ÉVÉNEMENTS DE LIQUIDATION (overshoot mark/oracle) — l'infra n°1 (23/07).

Le fade de liquidations était bloqué faute d'events. Ces tests prouvent qu'on CAPTURE l'overshoot
(mid vs oracle) + sa réversion, qu'on n'invente RIEN, qu'on exclut BTC (mort), et qu'une coupure
réseau ne tue pas la boucle. Aucun appel réseau réel : tout est bouchonné.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod():
    chemin = RACINE / "tools" / "collecter_overshoots.py"
    spec = importlib.util.spec_from_file_location("collecter_overshoots", chemin)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# ------------------------------------------------------------------ cœur PUR

def test_overshoot_bps_signe_et_garde():
    m = _mod()
    assert round(m.overshoot_bps(99.6, 100.0), 1) == -40.0     # mid SOUS l'oracle -> négatif (forced sell)
    assert round(m.overshoot_bps(100.4, 100.0), 1) == 40.0
    assert m.overshoot_bps(100.0, 0.0) is None                 # oracle absurde -> rien d'inventé


def test_parser_ctxs_apparie_universe_et_contextes_tolerant():
    m = _mod()
    payload = [{"universe": [{"name": "ETH"}, {"name": "SOL"}]},
               [{"oraclePx": "100.0", "markPx": "99.9"}, {"oraclePx": "5.0"}]]
    out = m.parser_ctxs(payload)
    assert out["ETH"] == {"oracle": 100.0, "mark": 99.9}
    assert out["SOL"]["oracle"] == 5.0 and out["SOL"]["mark"] == 5.0   # markPx absent -> = oracle
    assert m.parser_ctxs("nawak") == {}                        # illisible -> vide, pas d'exception


def test_detecter_flague_au_dessus_du_seuil_exclut_BTC():
    m = _mod()
    mids = {"ETH": 99.6, "SOL": 20.0, "BTC": 59000.0}
    ctxs = {"ETH": {"oracle": 100.0, "mark": 99.8},           # -40 bps -> retenu
            "SOL": {"oracle": 20.01, "mark": 20.0},           # -5 bps -> sous le seuil
            "BTC": {"oracle": 59300.0, "mark": 59100.0}}      # -50 bps MAIS BTC exclu (mort)
    ev = m.detecter(mids, ctxs)
    assert [e["coin"] for e in ev] == ["ETH"]
    assert ev[0]["sens"] == "SELL_OVERSHOOT"


def test_avancer_remplit_les_forward_et_calcule_la_reversion():
    m = _mod()
    ouverts = {"ETH": {"coin": "ETH", "ts0": 1000.0, "mid_at_event": 100.0, "oracle_px": 100.4,
                       "mark_px": 100.2, "overshoot_bps": -40.0, "sens": "SELL_OVERSHOOT"}}
    finis = m.avancer(ouverts, {"ETH": 100.2}, 1000.0 + max(m.HORIZONS_S))  # mid remonté vers l'oracle
    assert len(finis) == 1 and not ouverts                    # arrivé à terme -> retiré
    # fade d'un SELL_OVERSHOOT : le mid remonte (100.0 -> 100.2) = réversion POSITIVE
    assert finis[0]["reversion_bps"] > 0
    assert "mid_fwd_60s" in finis[0]


# ------------------------------------------------------------------ une passe (bouchonnée)

def test_une_passe_ouvre_puis_ecrit_a_terme(tmp_path, monkeypatch):
    m = _mod()
    monkeypatch.setattr(m, "lire_ctxs", lambda **k: {"ETH": {"oracle": 100.0, "mark": 99.8}})
    monkeypatch.setattr(m, "lire_all_mids", lambda **k: {"ETH": 99.6})   # -40 bps -> événement
    ouverts: dict = {}
    assert m.une_passe(tmp_path, ouverts, now=1000.0) == 0     # ouvre, rien à terme encore
    assert "ETH" in ouverts
    # plus tard, le mid est revenu : l'événement arrive à terme et s'écrit
    monkeypatch.setattr(m, "lire_all_mids", lambda **k: {"ETH": 99.95})
    n = m.une_passe(tmp_path, ouverts, now=1000.0 + max(m.HORIZONS_S))
    assert n == 1 and not ouverts
    lignes = (tmp_path / m.SORTIE).read_text(encoding="utf-8").splitlines()
    ev = json.loads(lignes[0])
    assert ev["coin"] == "ETH" and ev["reversion_bps"] > 0 and ev["real_execution"] is False


def test_une_coupure_reseau_ne_tue_pas_la_passe(tmp_path, monkeypatch):
    m = _mod()

    def boom(**_k):
        raise OSError("reseau coupe")

    monkeypatch.setattr(m, "lire_ctxs", boom)
    assert m.une_passe(tmp_path, {}, now=1000.0) == 0          # 0 écrit, aucune exception


def test_resume_est_honnete_quand_vide(tmp_path):
    m = _mod()
    assert m.resume(tmp_path)["verdict"] == "AUCUN_OVERSHOOT_ENCORE_COLLECTE"


# ─────── 17/11/2026 : UN PERP DÉLISTÉ N'EST PAS UN ÉVÉNEMENT, ET UN PRIX ABSENT N'EST PAS ZÉRO ───────
#
# MESURÉ SUR LE COFFRE. La famille `overshoot` compte 175 238 lignes ; **67,3 % ont leurs quatre
# prix futurs identiques au prix de l'événement**, et 69,1 % une « réversion » de 0,0. Les coins
# touchés à 100 % — RNDR, FTM, FXS, HPOS, UNIBOT, OX, FRIEND, SHIA, exactement 3 693 lignes
# chacun — sont des perps DÉLISTÉS : mark et oracle y sont figés avec un écart permanent
# (RNDR : −191,75 bps), donc le seuil de 30 bps était franchi à chaque cycle et le collecteur
# écrivait un « dépassement » toutes les deux minutes, pour toujours. Sur ETH, SOL et HYPE : 0 %.
#
# Deux défauts distincts :
#   1. le collecteur ignorait `isDelisted`, que `collection/univers_perps.py` applique déjà ;
#   2. `mf = ev.get(...) or m0` recopiait le prix de l'événement quand le prix futur manquait :
#      une observation ABSENTE devenait une réversion de 0,0.
def _payload(*actifs):
    """[meta, contextes] : chaque actif est (nom, oracle, mark, deliste)."""
    return [{"universe": [{"name": n, **({"isDelisted": True} if d else {})} for n, _, _, d in actifs]},
            [{"oraclePx": str(o), "markPx": str(m)} for _, o, m, _ in actifs]]


def test_un_perp_DELISTE_n_entre_pas_dans_les_contextes():
    m = _mod()
    payload = _payload(("ETH", 100.0, 99.9, False), ("RNDR", 7.03, 6.8952, True))
    ctxs = m.parser_ctxs(payload)
    assert set(ctxs) == {"ETH"}, "un marche deliste ne doit jamais devenir un evenement"
    assert m.coins_delistes(payload) == ["RNDR"], "ce qu'on ecarte doit pouvoir etre nomme"


def test_un_ecart_PERMANENT_sur_un_deliste_ne_declenche_plus_rien():
    """Le cas exact du coffre : RNDR, −191,75 bps, à chaque cycle."""
    m = _mod()
    ctxs = m.parser_ctxs(_payload(("RNDR", 7.03, 6.8952, True)))
    assert m.detecter({"RNDR": 6.8952}, ctxs) == []


def test_un_deliste_ne_decale_pas_l_appariement_des_AUTRES_actifs():
    """`universe[i]` correspond à `contextes[i]` : sauter un délisté ne doit rien désaligner."""
    m = _mod()
    ctxs = m.parser_ctxs(_payload(("AAA", 1.0, 1.0, False), ("MORT", 9.0, 5.0, True),
                                  ("ZZZ", 3.0, 2.9, False)))
    assert ctxs == {"AAA": {"oracle": 1.0, "mark": 1.0}, "ZZZ": {"oracle": 3.0, "mark": 2.9}}


def test_un_prix_futur_ABSENT_rend_une_reversion_INCONNUE_et_non_nulle():
    """L'ancien `or m0` transformait une observation manquante en mesure de 0,0."""
    m = _mod()
    ouverts = {"ETH": {"coin": "ETH", "ts0": 1000.0, "mid_at_event": 100.0, "oracle_px": 100.4,
                       "mark_px": 100.2, "overshoot_bps": -40.0, "sens": "SELL_OVERSHOOT"}}
    finis = m.avancer(ouverts, {}, 1000.0 + max(m.HORIZONS_S))      # le coin a disparu des mids
    assert len(finis) == 1
    assert finis[0]["reversion_bps"] is None, "une absence n'est jamais un zero"
    assert finis[0]["reversion_inconnue"] is True
    assert finis[0]["prix_fige"] is False, "sans prix futur, on ne peut pas dire qu'il est fige"


def test_un_prix_reste_EXACTEMENT_egal_est_MARQUE_fige_et_jamais_ecarte():
    m = _mod()
    ouverts = {"ILL": {"coin": "ILL", "ts0": 1000.0, "mid_at_event": 6.8952, "oracle_px": 7.03,
                       "mark_px": 6.8952, "overshoot_bps": -191.75, "sens": "SELL_OVERSHOOT"}}
    for dt in m.HORIZONS_S:                                           # chaque horizon voit le meme prix
        finis = m.avancer(ouverts, {"ILL": 6.8952}, 1000.0 + dt)
    assert len(finis) == 1, "la ligne est gardee : l'etude decide, mais elle le sait"
    assert finis[0]["prix_fige"] is True
    assert finis[0]["reversion_bps"] == 0.0, "ici le zero est OBSERVE, pas suppose"


def test_un_prix_qui_BOUGE_n_est_pas_marque_fige():
    m = _mod()
    ouverts = {"ETH": {"coin": "ETH", "ts0": 1000.0, "mid_at_event": 100.0, "oracle_px": 100.4,
                       "mark_px": 100.2, "overshoot_bps": -40.0, "sens": "SELL_OVERSHOOT"}}
    finis = m.avancer(ouverts, {"ETH": 100.2}, 1000.0 + max(m.HORIZONS_S))
    assert finis[0]["prix_fige"] is False and finis[0]["reversion_bps"] > 0
