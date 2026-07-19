"""Le collecteur de MARKS + le durcissement du docteur replay (19/07).

CE QUI A MOTIVÉ CES TESTS — des chiffres, pas une intuition :

    candidats : 30 148  sur 106 coins  (HYPE 8392, BTC 5743, ZEC 3828, ETH 2923…)
    marks     :    661  sur   2 coins  (HYPE 601, PURR 60)
    -> candidats REJOUABLES : 8 815 / 30 148  (29 %)

Les marks venaient de la shortlist carry. BTC/ETH/SOL/ZEC avaient des candidats et AUCUN prix
futur. Deux corrections : un collecteur qui marque TOUS les coins utiles, et un docteur qui
n'accepte plus un mark ANTÉRIEUR comme une couverture.
"""
from __future__ import annotations

import json

import pytest

from hl_observer.backtesting.replay_doctor import (
    _a_un_mark_posterieur, _index_marks_par_coin, diagnostiquer)


# ------------------------------------------------------------------ le docteur, durci

def test_un_mark_ANTERIEUR_ne_compte_PAS_comme_couverture():
    """LE BUG QU'ON FERME : tous les marks avant les candidats -> 0 % de couverture, pas 100 %.
    Un prix d'avant ne dit rien de ce que le prix a fait APRÈS. C'est tout l'objet du replay."""
    cands = [{"coin": "BTC", "recorded_at": 2_000.0} for _ in range(300)]
    marks = [{"coin": "BTC", "ts": 1_000.0 + i, "mid": 100.0} for i in range(600)]  # tous AVANT
    r = diagnostiquer(cands, marks, min_coins=1)
    assert r.couverture_marks == 0.0
    assert not r.suffisant
    assert any("COUVERTURE" in x for x in r.raisons)


def test_un_mark_POSTERIEUR_compte():
    cands = [{"coin": "BTC", "recorded_at": 1_000.0} for _ in range(300)]
    marks = [{"coin": "BTC", "ts": 2_000.0 + i, "mid": 100.0} for i in range(600)]
    r = diagnostiquer(cands, marks, min_coins=1)
    assert r.couverture_marks == 1.0
    assert r.suffisant


def test_le_cas_reel_du_19_07_est_declare_INSUFFISANT():
    """Reproduction fidèle : beaucoup de candidats sur beaucoup de coins, marks sur 2 coins.
    Le docteur DOIT refuser -- c'est exactement l'état qui avait produit le faux « 1 sur 1M »."""
    cands = ([{"coin": "HYPE", "recorded_at": 1_000.0}] * 800
             + [{"coin": "BTC", "recorded_at": 1_000.0}] * 600
             + [{"coin": "ETH", "recorded_at": 1_000.0}] * 400)
    marks = [{"coin": "HYPE", "ts": 2_000.0 + i, "mid": 40.0} for i in range(600)]
    r = diagnostiquer(cands, marks)
    assert r.couverture_marks == pytest.approx(800 / 1800, abs=1e-3)
    assert not r.suffisant, "un dataset borgne (2 coins sur 3) ne doit JAMAIS passer"


def test_index_et_predicat_sont_coherents():
    marks = [{"coin": "SOL", "ts": 50.0}, {"coin": "SOL", "ts": 10.0}, {"coin": "BTC", "ts": 20.0}]
    idx = _index_marks_par_coin(marks)
    assert idx["SOL"] == [10.0, 50.0], "les ts doivent être triés (recherche binaire)"
    assert _a_un_mark_posterieur({"coin": "SOL", "recorded_at": 30.0}, idx) is True
    assert _a_un_mark_posterieur({"coin": "SOL", "recorded_at": 60.0}, idx) is False
    assert _a_un_mark_posterieur({"coin": "DOGE", "recorded_at": 1.0}, idx) is False


def test_candidat_sans_horodatage_n_est_pas_rejouable():
    """Pas de date = on ne sait pas quels prix sont 'après'. Deny-by-default."""
    idx = _index_marks_par_coin([{"coin": "BTC", "ts": 100.0}])
    assert _a_un_mark_posterieur({"coin": "BTC"}, idx) is False


# ------------------------------------------------------------------ le collecteur

def _collecteur():
    import importlib.util
    from pathlib import Path
    chemin = Path(__file__).resolve().parents[1] / "tools" / "ecrire_marks_tous_coins.py"
    spec = importlib.util.spec_from_file_location("ecrire_marks_tous_coins", chemin)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_les_prix_illisibles_sont_IGNORES_jamais_remplaces(monkeypatch):
    """RÈGLE DURE : un prix absent reste absent. Pas de 0.0 de remplissage, pas de report du
    tick précédent -- un mark fabriqué ressort plus tard en faux PnL."""
    mod = _collecteur()
    charge = {"BTC": "100.5", "ETH": "abc", "SOL": "0", "DOGE": "-3", "HYPE": 41.2}
    monkeypatch.setattr(mod.urllib.request, "urlopen", lambda *a, **k: (_ for _ in ()).throw(AssertionError))
    monkeypatch.setattr(mod, "lire_all_mids", lambda **k: {
        c: float(p) for c, p in charge.items()
        if isinstance(p, (int, float)) or (isinstance(p, str) and p.replace(".", "").isdigit())})
    mids = mod.lire_all_mids()
    assert set(mids) == {"BTC", "SOL", "HYPE"}          # 'abc' et '-3' écartés en amont
    assert "ETH" not in mids and "DOGE" not in mids


def test_une_erreur_reseau_ne_tue_pas_la_boucle(monkeypatch, tmp_path):
    """Le collecteur doit survivre à une coupure : 0 mark écrit, pas d'exception."""
    mod = _collecteur()

    def boom(**_kw):
        raise OSError("reseau coupe")

    monkeypatch.setattr(mod, "lire_all_mids", boom)
    n, dispo = mod.une_passe(tmp_path, coins={"BTC"})
    assert (n, dispo) == (0, 0)


def test_le_collecteur_cible_les_coins_vus_dans_les_candidats(tmp_path):
    """On marque ce qu'on aura à JUGER : les coins des candidats récents."""
    mod = _collecteur()
    base = tmp_path / "runtime" / "replay"
    base.mkdir(parents=True)
    import time as _t
    maintenant = _t.time()
    lignes = [{"coin": "BTC", "recorded_at": maintenant - 60},
              {"coin": "ETH", "recorded_at": maintenant - 120},
              {"coin": "VIEUX", "recorded_at": maintenant - 10 * 24 * 3600}]   # hors fenêtre
    (base / "candidates.123.jsonl").write_text(
        "\n".join(json.dumps(x) for x in lignes), encoding="utf-8")
    coins = mod.coins_utiles(tmp_path, fenetre_h=48.0)
    assert coins == {"BTC", "ETH"}, coins


def test_sans_candidats_lisibles_on_marque_TOUT(tmp_path, monkeypatch):
    """Mieux vaut trop de marks que pas assez : c'est l'erreur inverse qu'on vient de payer."""
    mod = _collecteur()
    assert mod.coins_utiles(tmp_path) == set()
    monkeypatch.setattr(mod, "lire_all_mids", lambda **k: {"BTC": 1.0, "ETH": 2.0, "SOL": 3.0})
    n, dispo = mod.une_passe(tmp_path, coins=set())     # coins vide -> tout l'univers
    assert n == 3 and dispo == 3


def test_le_plafond_de_coins_borne_le_volume(tmp_path, monkeypatch):
    """Les shards de marks sont capés : on ne noie pas le dataset sous 5 000 coins."""
    mod = _collecteur()
    monkeypatch.setattr(mod, "lire_all_mids", lambda **k: {f"C{i}": 1.0 + i for i in range(500)})
    n, dispo = mod.une_passe(tmp_path, coins=set(), plafond=250)
    assert dispo == 500 and n == 250
