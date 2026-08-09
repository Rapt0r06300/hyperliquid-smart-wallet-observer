"""[LANCEUR item 6] Preflight BLOQUANT — prouvé 0 réseau (sonde injectée).

GO seulement si TOUS les contrôles durs passent ; sinon NO-GO avec raison précise et CLI exit 2. On
prouve : le chemin sain (GO), chaque catégorie dure qui casse (deps, endpoint, horloge, orphelin,
paper), et que les avertissements (dYdX non branché, dep recommandée) NE bloquent PAS.
"""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.ops import preflight_lanceur as PF

RACINE_REPO = Path(__file__).resolve().parents[1]
T = 1_700_000_000_000.0
_DISQUE_OK = lambda p: (100 * 2**30, 10 * 2**30, 90 * 2**30)  # noqa: E731 (total, used, free)


def _prober_ok(url: str) -> PF.Sonde:
    if "binance" in url:
        return PF.Sonde(True, code=200, serveur_ts_ms=T)      # heure serveur pour le check horloge
    return PF.Sonde(True, code=200)


def _preflight(tmp_path, **kw):
    base = dict(prober=_prober_ok, local_ts_ms=T, env={}, procs=[], deps_present=lambda n: True,
                disque_usage=_DISQUE_OK, schemas=())
    base.update(kw)
    return PF.executer_preflight(tmp_path, **base)


def test_preflight_go_quand_tout_est_sain(tmp_path):
    res = _preflight(tmp_path)
    assert res.go() is True and not res.blocages()
    assert (tmp_path / "runtime" / "data").is_dir()           # dossiers réellement créés+inscriptibles


def test_preflight_no_go_si_dep_dure_manquante(tmp_path):
    res = _preflight(tmp_path, deps_present=lambda n: n != "httpx")
    assert res.go() is False
    assert "deps-obligatoires" in {v.nom for v in res.blocages()}


def test_preflight_paper_strict_bloque_execution_reelle(tmp_path):
    res = _preflight(tmp_path, env={"HL_ENABLE_MAINNET_EXECUTION": "1"})
    assert res.go() is False
    assert any(v.categorie == "paper" for v in res.blocages())


def test_preflight_endpoint_dur_et_orphelin_bloquent(tmp_path):
    def prober_hl_down(url):
        if "hyperliquid" in url:
            return PF.Sonde(False, detail="timeout")
        return _prober_ok(url)

    procs = [{"pid": 42, "name": "cmd.exe",
              "cmd": "cmd /c tools\\boucle_collecteur.cmd bbo-collector tools\\collecter_bbo.py 5"}]
    res = _preflight(tmp_path, prober=prober_hl_down, procs=procs)
    noms = {v.nom for v in res.blocages()}
    assert "endpoint:hyperliquid" in noms and "orphelins" in noms and res.go() is False


def test_preflight_avertissements_ne_bloquent_pas(tmp_path):
    def prober_dydx_down(url):
        if "dydx" in url:
            return PF.Sonde(False, detail="503")
        return _prober_ok(url)

    # dYdX non-branché (non-dur) + dep recommandée absente -> warn, mais GO
    res = _preflight(tmp_path, prober=prober_dydx_down, deps_present=lambda n: n != "lz4")
    assert res.go() is True
    avert = {v.nom for v in res.avertissements()}
    assert "endpoint:dydx" in avert and "deps-recommandees" in avert


def test_preflight_horloge_skew_bloque(tmp_path):
    res = _preflight(tmp_path, local_ts_ms=T + 60_000.0)       # 60 s de dérive > 5 s
    assert res.go() is False
    assert any(v.nom == "horloge" for v in res.blocages())


def test_preflight_sans_sonde_les_endpoints_durs_echouent(tmp_path):
    res = _preflight(tmp_path, prober=None)                    # 0 réseau -> endpoints durs injoignables
    assert res.go() is False
    assert "endpoint:hyperliquid" in {v.nom for v in res.blocages()}


def test_preflight_schemas_reels_presents_dans_le_repo():
    v = PF.verifier_schemas(RACINE_REPO)                       # garde de régression sur docs/schemas
    assert v.ok, v.detail


def test_cli_sort_2_si_no_go(monkeypatch, tmp_path):
    monkeypatch.setattr(PF, "_sonde_http_reelle", lambda url, **k: PF.Sonde(False, detail="offline"))
    assert PF.main([str(tmp_path)]) == 2                       # HL/Binance injoignables -> NO-GO -> exit 2


def test_sonde_hyperliquid_info_utilise_post_meta_read_only(monkeypatch):
    capture = {}

    class Reponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self, _limit):
            return b'{"universe":[]}'

    def fake_urlopen(request, timeout):
        capture["method"] = request.get_method()
        capture["body"] = json.loads(request.data.decode("utf-8"))
        capture["content_type"] = request.headers.get("Content-type")
        capture["timeout"] = timeout
        return Reponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    sonde = PF._sonde_http_reelle("https://api.hyperliquid.xyz/info", timeout=1.5)
    assert sonde.joignable and sonde.code == 200
    assert capture == {
        "method": "POST", "body": {"type": "meta"},
        "content_type": "application/json", "timeout": 1.5,
    }
