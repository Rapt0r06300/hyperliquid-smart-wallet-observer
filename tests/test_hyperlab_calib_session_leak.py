"""[Bloc 43/52/55] Calibration mesuree, session COMPLETE+hash, anti-fuite + gel finalistes."""
from hl_observer.hyperlab import calibration as cal
from hl_observer.hyperlab import leakage as lk
from hl_observer.hyperlab import session as se


def test_calibration_depuis_mesures():
    quotes = [{"bid": 99.9, "ask": 100.1}, {"bid": 100.0, "ask": 100.2}]
    fills = [{"prix_exec": 100.2, "mid_ref": 100.0, "frais": 0.05, "notionnel": 100.0,
              "mid_apres": 100.1, "side": "buy"}]
    p = cal.parametres_calibres(quotes, fills, [10, 20, 30, 40, 100])
    assert p["spread_bps"] > 0 and p["slippage_bps"] > 0 and p["frais_bps"] == 5.0
    assert p["latence"]["p50"] == 30.0 and p["latence"]["p99"] >= p["latence"]["p95"]


def test_calibration_sans_donnee_est_none():
    p = cal.parametres_calibres([], [], [])
    assert p["spread_bps"] is None and p["slippage_bps"] is None and p["latence"] is None


def test_session_complete_et_verif():
    s = se.Session("sess1", ts=1000.0)
    assert s.statut == "INCOMPLETE"
    s.add_artifact("rapport", "PNL=+1.23")
    man = s.fermer(ts=1005.0)
    assert man["statut"] == "COMPLETE"
    assert se.verifier(man, {"rapport": "PNL=+1.23"})["ok"] is True
    assert se.verifier(man, {"rapport": "ALTERE"})["ok"] is False


def test_anti_fuite_et_gel():
    assert lk.verifier_pas_de_fuite([0, 1], [2, 3], [4, 5])["fuite"] is False
    assert lk.verifier_pas_de_fuite([0, 3], [2, 3], [4, 5])["fuite"] is True  # intersection
    assert lk.verifier_pas_de_fuite([4, 5], [2, 3], [0, 1])["fuite"] is True  # ordre inverse
    gel = lk.geler_finalistes(["cfg_a", "cfg_b"])
    assert lk.gel_intact(gel, ["cfg_b", "cfg_a"]) is True
    assert lk.gel_intact(gel, ["cfg_a", "cfg_c"]) is False  # modif apres gel detectee
