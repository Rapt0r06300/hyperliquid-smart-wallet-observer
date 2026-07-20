"""Tests de l'outil de mesure carry (tools/ecrire_carry_spot_inputs.py) : carnet REEL + VWAP + plancher.
Rien n'echappe aux tests, meme un tool. Le reseau (_post) est monkeypatche -> 100% offline."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location("ecrire_carry_tool", ROOT / "tools" / "ecrire_carry_spot_inputs.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def test_vwap_achat_est_au_dessus_du_mid_slippage_reel():
    m = _load()
    # bid 39.9 ; asks 40.0 x5 (=200$) puis 40.5 (large). Acheter 500$ traverse les 2 niveaux.
    m._post = lambda payload, **k: {"levels": [
        [{"px": "39.9", "sz": "10"}],
        [{"px": "40.0", "sz": "5"}, {"px": "40.5", "sz": "100"}]]}
    mid, prof, vwap = m._carnet_spot("@T", notional_cible=500.0)
    assert mid == 39.95
    assert vwap > mid                                        # acheter POUSSE le prix au-dessus du mid
    assert abs(vwap - 500.0 / (200 / 40.0 + 300 / 40.5)) < 1e-6   # VWAP exact
    assert prof > 500.0                                      # profondeur reelle mesuree


def test_carnet_vide_retourne_none():
    m = _load()
    m._post = lambda payload, **k: {"levels": [[], []]}
    assert m._carnet_spot("@T", notional_cible=500.0) is None


def test_profondeur_bornee_par_l_impact_max():
    m = _load()
    # 2e niveau au-dela de +2% d'impact -> ignore dans la profondeur ET le VWAP
    m._post = lambda payload, **k: {"levels": [
        [{"px": "100.0", "sz": "1"}],
        [{"px": "100.0", "sz": "3"}, {"px": "110.0", "sz": "100"}]]}
    mid, prof, vwap = m._carnet_spot("@T", impact_max=0.02, notional_cible=500.0)
    assert prof == 300.0                                     # seul le niveau a 100.0 compte (110 > +2%)


def test_plancher_liquidite_est_principiel():
    m = _load()
    assert m.NOTIONNEL_MAX_USD == 500.0
    assert m.SECURITE_PROFONDEUR == 5.0
    assert m.LIQUIDITE_MIN_USD == m.NOTIONNEL_MAX_USD * m.SECURITE_PROFONDEUR == 2500.0


# ---------- A2 : classement transversal net (top-K) ----------

def test_classer_viables_par_carry_net_et_top_k():
    m = _load()
    viables = [
        ("A", {"coin": "A"}, 10.0, 2.0),   # net 2
        ("B", {"coin": "B"}, 5.0, 9.0),    # net 9 (meilleur)
        ("C", {"coin": "C"}, 1.0, 5.0),    # net 5
        ("D", {"coin": "D"}, 50.0, 1.0),   # net 1
    ]
    r = m.classer_viables(viables, top_k=2)
    assert [x[0] for x in r] == ["B", "C"]           # top-2 par carry NET


def test_classer_viables_tie_break_break_even_court():
    m = _load()
    viables = [("A", {}, 20.0, 3.0), ("B", {}, 8.0, 3.0)]   # meme net -> break-even court d'abord
    assert [x[0] for x in m.classer_viables(viables, top_k=2)] == ["B", "A"]


def test_classer_viables_gain_none_est_relegue():
    m = _load()
    viables = [("A", {}, 10.0, None), ("B", {}, 10.0, 0.1)]
    assert m.classer_viables(viables, top_k=2)[0][0] == "B"   # net inconnu -> en dernier


def test_plafond_shortlist_est_defini():
    m = _load()
    assert isinstance(m.PLAFOND_SHORTLIST, int) and m.PLAFOND_SHORTLIST >= 1


# ---------- A3 : levier en risk-parity (tampon liq uniforme) ----------

def test_a3_plus_de_securite_baisse_ou_egale_le_levier():
    m = _load()
    b1 = m._meilleur_levier("X", 1.0, 0.0, 200_000.0, 10.0, 0.15, securite=1.0)
    b15 = m._meilleur_levier("X", 1.0, 0.0, 200_000.0, 10.0, 0.15, securite=1.5)
    assert b1 is not None and b15 is not None
    assert b15[0] <= b1[0]                    # plus de securite -> levier <= (plus conservateur)


def test_a3_coin_volatil_recoit_moins_de_levier_risk_parity():
    m = _load()
    calme = m._meilleur_levier("CALM", 1.0, 0.0, 200_000.0, 10.0, 0.06)    # pire 6%
    volatil = m._meilleur_levier("VOL", 1.0, 0.0, 200_000.0, 10.0, 0.35)   # pire 35%
    assert calme is not None
    lev_vol = volatil[0] if volatil else 0.0
    assert lev_vol <= calme[0]                # risk-parity : le volatil a MOINS de levier (ou refuse)


def test_securite_liquidation_est_definie_et_conservative():
    m = _load()
    assert m.SECURITE_LIQUIDATION >= 1.0


# ---------- A4 : z-score comme departage (le net prime) ----------

def test_a4_a_net_egal_le_spike_passe_devant():
    m = _load()
    # (coin, inp, heures, gain_net, zscore) — meme net, B spike
    viables = [("A", {}, 10.0, 5.0, 0.2), ("B", {}, 10.0, 5.0, 3.0)]
    assert [x[0] for x in m.classer_viables(viables, top_k=2)] == ["B", "A"]


def test_a4_le_net_prime_sur_le_zscore():
    m = _load()
    viables = [("A", {}, 10.0, 9.0, 0.0), ("B", {}, 10.0, 2.0, 5.0)]   # A meilleur net, B spike
    assert m.classer_viables(viables, top_k=2)[0][0] == "A"            # le NET prime, z = departage


# ------------------------------------------ NUIT 19-20/07 : cache pire-hausse (anti-hoquet reseau)

def test_un_rate_de_fetch_REUTILISE_le_cache_recent(tmp_path, capsys):
    """UN echec de candleSnapshot -> pire=None -> coin ejecte de la shortlist -> 45 min plus
    tard le store fermait une position non amortie (-0,49 $ cette nuit). La pire-hausse est une
    statistique sur 200 JOURS : un hoquet reseau n'a pas le droit de l'amputer."""
    m = _load()
    # 1) une mesure fraiche remplit le cache
    assert m._pire_avec_cache(tmp_path, "PURR", 0.26) == 0.26
    # 2) le fetch rate (None) -> la valeur du cache revient, et c'est TRACE au log
    assert m._pire_avec_cache(tmp_path, "PURR", None) == 0.26
    assert "CACHE" in capsys.readouterr().out


def test_un_cache_PERIME_ne_fabrique_pas_de_mesure(tmp_path, monkeypatch):
    """> 24 h -> exclusion honnete, comme avant. Un cache eternel serait une donnee inventee."""
    m = _load()
    m._pire_avec_cache(tmp_path, "PURR", 0.26)
    vraie = m.time.time
    monkeypatch.setattr(m.time, "time", lambda: vraie() + m.PIRE_HAUSSE_CACHE_MAX_AGE_S + 60)
    assert m._pire_avec_cache(tmp_path, "PURR", None) is None


def test_le_cache_sans_entree_reste_None(tmp_path):
    m = _load()
    assert m._pire_avec_cache(tmp_path, "JAMAIS_VU", None) is None


def test_une_mesure_fraiche_RAFRAICHIT_le_cache(tmp_path):
    m = _load()
    m._pire_avec_cache(tmp_path, "PURR", 0.26)
    m._pire_avec_cache(tmp_path, "PURR", 0.31)          # nouvelle mesure
    assert m._pire_avec_cache(tmp_path, "PURR", None) == 0.31


def test_la_boucle_collecteur_PRESERVE_le_log_precedent():
    """La relance du superviseur tronquait le log et DETRUISAIT la preuve de la mort
    (venues-collector, nuit du 19-20/07). Une generation .prev.log doit etre gardee."""
    texte = (ROOT / "tools" / "boucle_collecteur.cmd").read_text(encoding="utf-8", errors="ignore")
    assert '.prev"' in texte and "copy /y" in texte.lower(), (
        "boucle_collecteur.cmd doit copier le log en .prev avant de le tronquer (autopsie R5)")
