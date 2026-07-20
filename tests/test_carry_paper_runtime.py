"""Carry HYPE paper v1 : refus motive sans inputs, verdict complet avec inputs MESURES,
peremption, et journal jsonl estampille session. Aucune conversion d'unite dans le module."""
from __future__ import annotations

import json

from hl_observer.funding.carry_paper_runtime import (
    ENV_ENABLED, JOURNAL_RELPATH, INPUTS_RELPATH, enabled, evaluer_et_journaliser,
)


def _lire_journal(root):
    path = root / JOURNAL_RELPATH
    return [json.loads(l) for l in path.read_text(encoding="utf-8").splitlines() if l.strip()]


def test_flag_defaut_off(monkeypatch):
    monkeypatch.delenv(ENV_ENABLED, raising=False)
    assert enabled() is False
    monkeypatch.setenv(ENV_ENABLED, "1")
    assert enabled() is True


def test_sans_inputs_refus_motive_et_journalise(tmp_path, monkeypatch):
    monkeypatch.delenv("HYPERSMART_SESSION_ID", raising=False)
    ligne = evaluer_et_journaliser(tmp_path, now_ms=10_000_000)
    assert ligne["decision"]["viable"] is False
    assert ligne["decision"]["motif"] == "INPUTS_SPOT_ABSENTS_NO_TRADE"
    assert ligne["real_execution"] is False and ligne["paper_only"] is True
    assert _lire_journal(tmp_path)[0]["decision"]["motif"] == "INPUTS_SPOT_ABSENTS_NO_TRADE"


def test_inputs_perimes_refuses(tmp_path):
    p = tmp_path / INPUTS_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"ts_ms": 1_000, "coin": "HYPE", "funding_bps_h": 1.0,
                             "base_bps": 0.0, "liquidite_spot_usd": 50_000.0}), encoding="utf-8")
    ligne = evaluer_et_journaliser(tmp_path, now_ms=1_000 + 901_000)   # 901 s > 900 s
    assert ligne["decision"]["motif"] == "INPUTS_SPOT_PERIMES_NO_TRADE"


def test_inputs_mesures_verdict_complet_avec_verrou(tmp_path, monkeypatch):
    """Avec des entrees completes (dont le verrou T2b), le module rend le verdict du moteur
    delta_neutral_carry — on verifie qu'il TRANSMET sans convertir ni adoucir."""
    monkeypatch.setenv("HYPERSMART_SESSION_ID", "S-CARRY")
    p = tmp_path / INPUTS_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    inputs = {"ts_ms": 100_000_000, "coin": "HYPE", "funding_bps_h": 1.2, "base_bps": 2.0,
              "liquidite_spot_usd": 80_000.0, "maker": True,
              "levier_max": 10.0, "marge_ratio": 1.06, "pire_hausse_observee": 0.956}
    p.write_text(json.dumps(inputs), encoding="utf-8")
    ligne = evaluer_et_journaliser(tmp_path, now_ms=100_060_000)   # 60 s: frais
    d = ligne["decision"]
    assert ligne["session_id"] == "S-CARRY"
    assert ligne["inputs_age_s"] == 60.0
    assert d["coin"] == "HYPE" and d["real_execution"] is False
    assert d["funding_bps_h"] == 1.2                       # transmis TEL QUEL (piege d'unite)
    assert isinstance(d["viable"], bool) and d["motif"]    # verdict rendu, jamais silencieux


# ---------- ETAPE 2 (cablage opt-in) : ouvrir REELLEMENT la position paper ----------

_INPUTS_VIABLES = {"ts_ms": 100_000_000, "coin": "HYPE", "funding_bps_h": 0.125, "base_bps": -0.68,
                   "liquidite_spot_usd": 200_000.0, "maker": True, "levier_max": 10.0,
                   "marge_ratio": 0.5, "pire_hausse_observee": 0.29, "levier_utilise": 2.0}


def _ecrire_inputs(root, inputs):
    p = root / INPUTS_RELPATH
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(inputs), encoding="utf-8")


def test_etape2_off_par_defaut_aucune_ouverture(tmp_path, monkeypatch):
    monkeypatch.delenv("HYPERSMART_CARRY_ETAPE2", raising=False)
    _ecrire_inputs(tmp_path, _INPUTS_VIABLES)
    ligne = evaluer_et_journaliser(tmp_path, now_ms=100_060_000)
    assert ligne["etape2"] is None                                  # flag OFF -> on n'ouvre rien
    assert not (tmp_path / "runtime" / "data" / "carry_paper_positions.json").exists()


def test_etape2_on_ouvre_la_position_et_ecrit_le_ledger(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERSMART_CARRY_ETAPE2", "1")
    _ecrire_inputs(tmp_path, _INPUTS_VIABLES)                        # pas de shortlist -> repli sur le best
    ligne = evaluer_et_journaliser(tmp_path, now_ms=100_060_000)
    assert ligne["decision"]["viable"] is True                      # HYPE viable a 2x
    assert ligne["etape2"]["positions_ouvertes"] == 1               # etape 2 a OUVERT 1 position
    assert ligne["etape2"]["coins_ouverts"] == ["HYPE"]
    assert ligne["real_execution"] is False                         # ... mais JAMAIS d'ordre reel
    assert (tmp_path / "runtime" / "data" / "carry_paper_positions.json").exists()
    assert (tmp_path / "runtime" / "data" / "carry_paper_ledger.jsonl").exists()


def test_etape2_multi_coins_via_shortlist(tmp_path, monkeypatch):
    monkeypatch.setenv("HYPERSMART_CARRY_ETAPE2", "1")
    _ecrire_inputs(tmp_path, _INPUTS_VIABLES)
    # une shortlist de 2 coins viables -> 2 positions en parallele
    sl = tmp_path / "runtime" / "data" / "carry_spot_shortlist.json"
    a = dict(_INPUTS_VIABLES)
    b = dict(_INPUTS_VIABLES); b["coin"] = "PURR"
    sl.write_text(json.dumps([a, b]), encoding="utf-8")
    ligne = evaluer_et_journaliser(tmp_path, now_ms=100_060_000)
    assert ligne["etape2"]["positions_ouvertes"] == 2
    assert set(ligne["etape2"]["coins_ouverts"]) == {"HYPE", "PURR"}


def test_etape2_erreur_ne_casse_pas_la_decision(tmp_path, monkeypatch):
    # inputs viables mais on force une erreur interne -> la decision reste journalisee, etape2 = erreur
    monkeypatch.setenv("HYPERSMART_CARRY_ETAPE2", "1")
    _ecrire_inputs(tmp_path, _INPUTS_VIABLES)
    import hl_observer.funding.carry_positions_store as store
    monkeypatch.setattr(store, "tick_multi_sur_disque",
                        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    ligne = evaluer_et_journaliser(tmp_path, now_ms=100_060_000)
    assert ligne["decision"]["viable"] is True                      # la decision survit
    assert ligne["etape2"]["erreur"] == "etape2_indisponible"       # l'erreur est capturee, pas propagee


def test_etape2_shortlist_sortie_selective_APRES_amortissement(tmp_path, monkeypatch):
    """🔴 RÉÉCRIT LE 19/07 — l'ancienne version de ce test PRESCRIVAIT le churn.

    Elle exigeait : « PURR sort de la shortlist a +2 h => PURR se ferme ». C'est exactement le
    comportement qui a coute -5,07 $ (29 fermetures COIN_PLUS_DANS_SHORTLIST a ~17,5 cts le
    tour, sans jamais laisser le funding rembourser l'entree). L'anti-churn (A3) exige
    desormais d'avoir AMORTI l'entree avant toute sortie non urgente.

    Fixture : 0,125 bps/h de funding, ~11,7 bps d'entree -> amortissement ~93 h.
    Trois actes :
      1. deux coins viables -> deux positions ;
      2. PURR quitte la shortlist a +2 h  -> il RESTE (fermer acterait la perte pour rien) ;
      3. PURR toujours exclu a +100 h (amorti) -> il se ferme, et SEULEMENT lui.
    """
    monkeypatch.setenv("HYPERSMART_CARRY_ETAPE2", "1")
    H = 3_600_000

    def _inp(coin, ts):
        d = dict(_INPUTS_VIABLES); d["coin"] = coin; d["ts_ms"] = ts
        return d

    def _ecrire(ts, coins):
        _ecrire_inputs(tmp_path, _inp(coins[0], ts))
        (tmp_path / "runtime" / "data" / "carry_spot_shortlist.json").write_text(
            json.dumps([_inp(c, ts) for c in coins]), encoding="utf-8")

    t0 = 100_000_000
    _ecrire(t0, ["HYPE", "PURR"])
    e1 = evaluer_et_journaliser(tmp_path, now_ms=t0 + 30_000)["etape2"]
    assert set(e1["coins_ouverts"]) == {"HYPE", "PURR"}

    # ACTE 2 -- PURR sort a +2 h : NON amorti -> l'anti-churn annule la sortie, PURR reste.
    t1 = t0 + 2 * H
    _ecrire(t1, ["HYPE"])
    e2 = evaluer_et_journaliser(tmp_path, now_ms=t1 + 30_000)["etape2"]
    assert set(e2["coins_ouverts"]) == {"HYPE", "PURR"}, (
        "fermer un carry non amorti parce que la shortlist a cligne = le churn a -5$ du 18-19/07")
    assert [x for x in e2["evts"] if x.get("ferme")] == []

    # ACTE 3 -- PURR toujours exclu : l'absence doit etre PROLONGEE (A1 : >3 passes ET >45 min)
    # avant de fermer. On fait 4 passes etalees sur ~1 h -> la 4e ferme PURR, et SEULEMENT lui.
    # (Motif = SORTIE_ABSENCE_PROLONGEE : "hors shortlist" est une absence de donnee, pas un
    # ordre de fuite. COIN_PLUS_DANS_SHORTLIST ne subsiste que dans les vieilles lignes de ledger.)
    t2 = t0 + 100 * H
    e3, fermes = None, []
    for minutes in (0, 20, 40, 55):
        tk = t2 + minutes * 60_000
        _ecrire(tk - 30_000, ["HYPE"])                       # donnees fraiches, PURR absent
        e3 = evaluer_et_journaliser(tmp_path, now_ms=tk)["etape2"]
        fermes += [(x["coin"], x["ferme"]) for x in e3["evts"] if x.get("ferme")]
    assert e3["coins_ouverts"] == ["HYPE"], "HYPE (dans la shortlist) ne doit JAMAIS se fermer ici"
    assert fermes == [("PURR", "DONNEE_ABSENTE_PROLONGEE")], (
        "PURR doit fermer UNE fois, pour absence PROLONGEE -- pas a chaque clignotement: %r" % fermes)


def test_R1_un_SPIKE_de_funding_ouvre_PLUS_GROS_bout_en_bout(tmp_path, monkeypatch):
    """LE CHASSEUR DE SPIKES, prouve de bout en bout (R1, 19/07 soir).

    Toute la chaine existait deja (z-score A4 -> regime SPIKE -> facteur_zscore -> marge scalee)
    mais seulement en tests UNITAIRES. Ici : des inputs de spike ecrits sur disque -> le runtime
    complet -> une position ~1,5x plus grosse qu'en regime normal. Si quelqu'un debranche un
    maillon (feeder qui n'ecrit plus le facteur, lifecycle qui ne le lit plus), ce test rougit.
    """
    monkeypatch.setenv("HYPERSMART_CARRY_ETAPE2", "1")

    def _inp(coin, facteur):
        d = dict(_INPUTS_VIABLES)
        d["coin"] = coin
        d["facteur_taille"] = facteur          # ce que le feeder ecrit via facteur_zscore(z)
        d["funding_regime"] = "SPIKE" if facteur > 1.0 else "NORMAL"
        return d

    def _marge_ouverte(root, coin):
        d = json.loads((root / "runtime" / "data" / "carry_paper_positions.json"
                        ).read_text(encoding="utf-8"))
        return d["ouvertes"][coin]["marge_usdt"]

    # regime NORMAL (facteur 1.0) -> marge de base
    _ecrire_inputs(tmp_path, _inp("HYPE", 1.0))
    assert evaluer_et_journaliser(tmp_path, now_ms=100_060_000)["etape2"]["positions_ouvertes"] == 1
    marge_normale = _marge_ouverte(tmp_path, "HYPE")

    # regime SPIKE (facteur 1.5, ce que donne z >= 2) -> ~1,5x plus gros, borne respectee
    _ecrire_inputs(tmp_path / "spike", _inp("PURR", 1.5))
    assert evaluer_et_journaliser(tmp_path / "spike",
                                  now_ms=100_060_000)["etape2"]["positions_ouvertes"] == 1
    marge_spike = _marge_ouverte(tmp_path / "spike", "PURR")

    assert marge_spike == round(marge_normale * 1.5, 6), (
        "le SPIKE doit ouvrir 1,5x plus gros (marge %s vs %s) -- un maillon de la chaine "
        "z-score->facteur->marge est debranche" % (marge_spike, marge_normale))


def test_NUIT_1920_coin_hors_shortlist_NON_amorti_ne_ferme_PAS_meme_apres_45_min(tmp_path, monkeypatch):
    """🔴 LA NUIT DU 19-20/07 : PURR ferme 3x (-0,49 $) par la porte 'DONNEE_ABSENTE_PROLONGEE'
    alors que le marche etait MESURE — c'est le feeder qui ratait ses bougies, PURR sortait de
    la shortlist, et 45 min plus tard on fermait une position NON AMORTIE. Desormais : tant que
    d'AUTRES coins sont mesures (donnee vivante), un coin absent est un 'hors shortlist' non
    urgent -> gate par l'amortissement (A3). Le vrai blackout (0 mesure) garde l'ancienne regle."""
    monkeypatch.setenv("HYPERSMART_CARRY_ETAPE2", "1")

    def _inp(coin, ts):
        d = dict(_INPUTS_VIABLES); d["coin"] = coin; d["ts_ms"] = ts
        return d

    def _ecrire(ts, coins):
        _ecrire_inputs(tmp_path, _inp(coins[0], ts))
        (tmp_path / "runtime" / "data" / "carry_spot_shortlist.json").write_text(
            json.dumps([_inp(c, ts) for c in coins]), encoding="utf-8")

    t0 = 100_000_000
    _ecrire(t0, ["HYPE", "PURR"])
    e = evaluer_et_journaliser(tmp_path, now_ms=t0 + 30_000)["etape2"]
    assert set(e["coins_ouverts"]) == {"HYPE", "PURR"}

    # PURR disparait de la shortlist (rate de bougies) pendant ~1 h, 5 passes — HYPE reste mesure.
    # Position agee de 2 h : NON amortie (amortissement ~93 h) -> PURR doit RESTER OUVERT.
    H = 3_600_000
    for minutes in (0, 15, 30, 46, 60):
        tk = t0 + 2 * H + minutes * 60_000
        _ecrire(tk - 30_000, ["HYPE"])                     # donnee VIVANTE, PURR absent
        e = evaluer_et_journaliser(tmp_path, now_ms=tk)["etape2"]
    assert set(e["coins_ouverts"]) == {"HYPE", "PURR"}, (
        "fermer un carry NON amorti pour un rate de fetch = les -0,49 $ de la nuit du 19-20/07")
