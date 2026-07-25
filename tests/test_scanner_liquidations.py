"""SCANNER LIQUIDATIONS CONFIRMÉES — prouvé sans réseau (poster factice).

Prouve : extraction confirmée depuis une réponse userFillsByTime brute (réutilise le parseur WS →
cohérence live/backfill), plafond DUR de requêtes, journal + résumé écrits, et le cas
AUCUNE_DONNEE_CONFIRMEE (flux normal → 0). Aucun réseau, aucun ordre.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("scanner_liquidations_confirmees",
                                               _ROOT / "tools" / "scanner_liquidations_confirmees.py")
M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(M)


class _LimiteurNoop:
    def attente(self):
        return None


def _fill(coin, liq=None):
    f = {"coin": coin, "px": "100.0", "sz": "2", "side": "A", "time": 1700000000000, "dir": "Close Long", "hash": "0xh"}
    if liq:
        f["liquidation"] = liq
    return f


def _root(tmp_path, users):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vaults_suivis.json").write_text(json.dumps(users), encoding="utf-8")
    return tmp_path


def test_confirmees_depuis_reponse_liste_brute():
    liq = {"liquidatedUser": "0xabc", "markPx": "99.0", "method": "market"}
    rep = [_fill("SOL", liq), _fill("ETH")]           # 1 liquidation + 1 normal
    conf = M.confirmees_depuis_reponse(rep, "0xVAULT")
    assert len(conf) == 1 and conf[0]["coin"] == "SOL" and conf[0]["provenance"] == "REAL_LIQUIDATION"


def test_scanner_trouve_et_journalise_les_confirmees(tmp_path):
    root = _root(tmp_path, ["0xUSER1", "0xUSER2"])
    liq = {"liquidatedUser": "0xabc", "markPx": "99.0", "method": "market"}
    appels = {"n": 0}

    def poster(user, a, b):
        appels["n"] += 1
        return [_fill("SOL", liq)] if user == "0xUSER1" else [_fill("ETH")]

    r = M.scanner(root, lookback_j=2, poster=poster, limiteur=_LimiteurNoop(), max_req=50)
    assert r["n_confirmees"] >= 1, "au moins une liquidation confirmee doit ressortir de USER1"
    assert r["par_user"]["0xUSER1"] >= 1 and r["par_user"]["0xUSER2"] == 0
    # journal + resume ecrits
    assert (root / M.LIQ_CONFIRMEES).exists()
    lignes = (root / M.LIQ_CONFIRMEES).read_text(encoding="utf-8").strip().splitlines()
    assert lignes and json.loads(lignes[0])["provenance"] == "REAL_LIQUIDATION"
    res = json.loads((root / M.RESUME).read_text(encoding="utf-8"))
    assert res["n_confirmees"] == r["n_confirmees"] and "confirmees" not in res    # resume sans le gros payload


def test_plafond_dur_de_requetes_respecte(tmp_path):
    root = _root(tmp_path, ["0x" + "%02d" % i + "user" for i in range(9)])   # 9 users suivis
    appels = {"n": 0}

    def poster(user, a, b):
        appels["n"] += 1
        return [_fill("ETH")]

    r = M.scanner(root, lookback_j=60, poster=poster, limiteur=_LimiteurNoop(), max_req=7)
    assert appels["n"] <= 7 and r["n_requetes"] <= 7, "le plafond de requetes doit etre STRICT (budget borne)"


def test_aucune_donnee_confirmee_sur_flux_normal(tmp_path):
    root = _root(tmp_path, ["0xUSER1"])
    r = M.scanner(root, lookback_j=2, poster=lambda u, a, b: [_fill("BTC"), _fill("ETH")],
                  limiteur=_LimiteurNoop(), max_req=50)
    assert r["n_confirmees"] == 0                    # motif AUCUNE_DONNEE_CONFIRMEE
    assert r["n_fills_scannes"] >= 1                 # on a bien SCANNÉ (pas un échec silencieux)
