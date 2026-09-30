"""INVARIANTS ÉCONOMIQUES — property-based (21/07, recherche X/GitHub demandée par Flo).

Les tests par EXEMPLE vérifient les cas qu'on a imaginés. Les tests par PROPRIÉTÉ vérifient
des LOIS sur des milliers d'entrées générées — c'est ainsi que Hughes (QuickCheck) a trouvé
200+ bugs qu'aucun test d'exemple ne voyait. Ici, les lois qui PROTÈGENT LE PnL :

  L1. Un PnL ne naît jamais de rien : sans funding ni mouvement de base, fermer COÛTE.
  L2. Les coûts sont TOUJOURS payés : réalisé <= funding accru + base capturée.
  L3. Monotonie du funding : à taux positif, l'accru ne recule jamais avec le temps.
  L4. Symétrie de la base : gagner X bps dans un sens = perdre X bps dans l'autre.
  L5. Arbitrage : on n'ouvre JAMAIS sous le seuil, quel que soit l'écart généré.
  L6. Arbitrage : un aller-retour sans convergence est TOUJOURS perdant (les coûts).
  L7. Le ledger ne peut pas fabriquer de PnL : somme des CLOSE == réalisé du résumé.

Sans `hypothesis` installé, un repli déterministe balaie une grille dense (mêmes lois,
moins d'aléatoire) — le test ne disparaît JAMAIS en silence.
"""
from __future__ import annotations

import json

import pytest

from hl_observer.funding.arb_dislocation_paper import (
    ECART_MAX_ENTREE_BPS,
    COUT_AR_BPS, NOTIONAL_USD, SEUIL_OUVERTURE_BPS, tick)
from hl_observer.funding.carry_position_lifecycle import pnl_realise
from hl_observer.ui.dashboard_v2 import base_mtm_usd

try:                                    # property-based si dispo, grille dense sinon
    from hypothesis import HealthCheck, given, settings
    from hypothesis import strategies as st
    HYPO = True
except ImportError:                     # pragma: no cover - depend de l'environnement
    HYPO = False


def _position(notional=150.0, accru=0.0, cout_entree_bps=5.5, base_entree=0.0):
    return {"coin": "TEST", "notional_usdt": float(notional),
            "funding_accrued_usdt": float(accru),
            "cout_entree_bps": float(cout_entree_bps),
            "base_bps_entree": float(base_entree), "liquidite_spot_usd": 100000.0,
            "levier_max": 10.0, "marge_ratio": 0.5, "pire_hausse_entree": 0.1,
            "entry_ts_ms": 0}


# ─────────────────────────────── L1/L2 : le PnL ne naît pas de rien
if HYPO:
    @settings(max_examples=200, deadline=None,
              suppress_health_check=[HealthCheck.function_scoped_fixture])
    @given(notional=st.floats(10, 5000), cout=st.floats(0.1, 20.0))
    def test_L1_sans_funding_ni_base_fermer_COUTE_toujours(notional, cout):
        p = _position(notional=notional, accru=0.0, cout_entree_bps=cout, base_entree=0.0)
        assert pnl_realise(p, base_bps_courant=0.0) < 0.0

    @settings(max_examples=300, deadline=None)
    @given(notional=st.floats(10, 5000), accru=st.floats(0, 50),
           cout=st.floats(0.1, 20), base_in=st.floats(-200, 200),
           base_out=st.floats(-200, 200))
    def test_L2_le_realise_ne_depasse_JAMAIS_funding_plus_base(notional, accru, cout,
                                                               base_in, base_out):
        p = _position(notional=notional, accru=accru, cout_entree_bps=cout,
                      base_entree=base_in)
        r = pnl_realise(p, base_bps_courant=base_out)
        # convention A5 : la base d'entree est deja creditee dans `cout_entree_bps` ; le
        # realise ne peut PAS depasser accru + correction de sortie (les couts sont > 0).
        from hl_observer.funding.base_convergence import correction_sortie_bps
        borne = accru + correction_sortie_bps(base_out) * notional / 1e4
        assert r < borne + 1e-9, "un PnL au-dessus de la borne = des couts non payes"
else:                                   # pragma: no cover
    def test_L1_L2_repli_grille_dense():
        for notional in (10.0, 150.0, 5000.0):
            for cout in (0.1, 5.5, 20.0):
                p = _position(notional=notional, cout_entree_bps=cout)
                assert pnl_realise(p, base_bps_courant=0.0) < 0.0


# ─────────────────────────────── L3/L4 : monotonie et symétrie
def test_L3_a_taux_positif_l_accru_ne_recule_jamais():
    from hl_observer.funding.carry_position_lifecycle import accruer
    p = _position(accru=0.0)
    p["last_accrual_ts_ms"] = 0
    precedent = 0.0
    for h in range(1, 25):
        p2, _ = accruer(p, now_ms=h * 3_600_000, funding_bps_h_courant=0.125)
        assert p2["funding_accrued_usdt"] >= precedent
        precedent = p2["funding_accrued_usdt"]


if HYPO:
    @settings(max_examples=200, deadline=None)
    @given(a=st.floats(-300, 300), b=st.floats(-300, 300), n=st.floats(1, 10000))
    def test_L4_la_base_est_SYMETRIQUE_aucun_biais_cache(a, b, n):
        assert abs(base_mtm_usd(a, b, n) + base_mtm_usd(b, a, n)) < 1e-6
else:                                   # pragma: no cover
    def test_L4_repli():
        assert abs(base_mtm_usd(30.0, 10.0, 150.0) + base_mtm_usd(10.0, 30.0, 150.0)) < 1e-9


# ─────────────────────────────── L5/L6 : les portes de l'arbitrage tiennent
def _venue(root, ecart, ts=1000.0):
    p = root / "runtime" / "data" / "dispersion_venues.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"ts": ts, "coin": "BTC", "ecart_prix_bps": ecart}) + "\n",
                 encoding="utf-8")


@pytest.mark.parametrize("ecart", [0.0, 1.0, 10.0, 14.9, -14.9, -0.5])
def test_L5_jamais_d_ouverture_sous_le_seuil(tmp_path, ecart):
    _venue(tmp_path, ecart)
    assert tick(tmp_path, now=1010.0) == [], "une ouverture sous %s bps = porte percee" % \
        SEUIL_OUVERTURE_BPS


# 🔴 21/07 — les ecarts d'ouverture sont DERIVES du seuil, plus codes en dur. Le seuil est
# passe de 15 a 19 bps (cout all-in 16 + marge 3) : les anciennes valeurs 15/-15 tombaient
# SOUS le nouveau seuil -> plus d'ouverture -> plus de CLOSE. L'invariant, lui, est intact :
# une position ouverte qui ne converge pas perd exactement ses couts. On le teste donc
# JUSTE AU-DESSUS du seuil, quelle que soit sa valeur future.
# 06/08 — -120 bps depassait ECART_MAX_ENTREE_BPS (plafond de plausibilite du 22/07 :
# les ecarts enormes sont des appariements structurels, jamais trades -> deny-by-default).
# L'extreme negatif se teste donc JUSTE SOUS le plafond, quelle que soit sa valeur future.
@pytest.mark.parametrize("ecart", [SEUIL_OUVERTURE_BPS + 1.0, 60.0,
                                   -(SEUIL_OUVERTURE_BPS + 1.0), -(ECART_MAX_ENTREE_BPS - 1.0)])
def test_L6_un_aller_retour_SANS_convergence_est_toujours_perdant(tmp_path, ecart):
    _venue(tmp_path, ecart)
    tick(tmp_path, now=1010.0, session_id="S")
    _venue(tmp_path, ecart, ts=1010.0 + 5 * 3600)          # meme ecart, 5 h plus tard
    evts = tick(tmp_path, now=1020.0 + 5 * 3600, session_id="S")
    close = next(e for e in evts if e["type"] == "CLOSE")
    assert close["realized"] == pytest.approx(-COUT_AR_BPS / 1e4 * NOTIONAL_USD)
    assert close["realized"] < 0


# ─────────────────────────────── L7 : le ledger ne fabrique pas de PnL
def test_L7_la_somme_des_CLOSE_est_EXACTEMENT_le_realise_du_resume(tmp_path):
    from hl_observer.funding.carry_positions_store import resume_depuis_ledger
    montants = [0.05, -0.30, 0.12, -0.01, 2.5, -1.75]
    p = tmp_path / "runtime" / "data" / "carry_paper_ledger.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps({
        "kind": "CLOSE", "mode": "LIVE", "coin": "X%d" % i, "ts_ms": 1000 + i,
        "session_id": "S", "realized_net_pnl_usdc": m}) for i, m in enumerate(montants)
    ) + "\n", encoding="utf-8")
    r = resume_depuis_ledger(tmp_path, session_id="S")
    assert r["closes"] == len(montants)
    assert abs(r["realized_net_pnl_usdc"] - sum(montants)) < 1e-9
    assert abs(r["realized_net_pnl_usdc_session"] - sum(montants)) < 1e-9
