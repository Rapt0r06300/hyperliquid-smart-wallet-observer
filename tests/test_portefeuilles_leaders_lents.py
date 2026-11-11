"""Boucle labo → collecteurs : les portefeuilles complets des leaders lents sont relevés automatiquement."""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.backtesting import copy_vault_copiability as cop  # noqa: E402
from hl_observer.datasets import coffre_certifie as CERT  # noqa: E402

NOW = 1_794_410_000.0


def _outil():
    spec = importlib.util.spec_from_file_location("collecter_vaults_leaders", RACINE / "tools" / "collecter_vaults.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _adr(n: int) -> str:
    return f"0x{n:040x}"


def _plan(tmp_path: Path) -> None:
    leaders = [
        {"unit": _adr(1), "addresses": [_adr(1)], "archetype": "DIRECTIONAL_SLOW"},
        {"unit": _adr(2), "addresses": [_adr(2), _adr(3)], "archetype": "SWING"},
        {"unit": _adr(4), "addresses": [_adr(4)], "archetype": "HFT"},                 # robot : jamais relevé
        {"unit": _adr(5), "addresses": [_adr(5)], "archetype": "INSUFFICIENT"},
        {"unit": "x", "addresses": ["pas-une-adresse"], "archetype": "SWING"},
    ]
    chemin = tmp_path / "runtime" / "data" / "copy_vault_besoins_collecte.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps({"leaders": leaders}), encoding="utf-8")


def test_seuls_les_leaders_lents_designes_par_le_labo_sont_releves(tmp_path):
    m = _outil()
    assert m.leaders_lents(tmp_path) == []                                           # pas de plan : aucun univers inventé
    _plan(tmp_path)
    assert m.leaders_lents(tmp_path) == [_adr(1), _adr(2), _adr(3)]


def test_un_instantane_par_leader_et_par_dex_certifiable_et_lisible_par_le_labo(tmp_path, monkeypatch):
    m = _outil()
    _plan(tmp_path)
    appels: list[dict] = []

    def faux_post(charge, **_):
        appels.append(charge)
        if charge["user"] == _adr(3) and "dex" not in charge:
            raise OSError("réseau coupé")
        coin = "xyz:GOLD" if charge.get("dex") else "BTC"
        return {"assetPositions": [{"type": "oneWay", "position": {
                    "coin": coin, "szi": "1.5", "entryPx": "100", "positionValue": "150", "unrealizedPnl": "2",
                    "leverage": {"type": "cross", "value": 3}}}],
                "marginSummary": {"accountValue": "1000.0"}, "time": int(NOW * 1000) - 50}

    monkeypatch.setattr(m, "_post_info", faux_post)
    bilan = m.passe_portefeuilles_leaders(tmp_path, now=NOW)

    assert bilan == {"leaders": 3, "portefeuilles": 5, "echecs": 1}                  # une panne n'arrête pas les autres
    assert {"type": "clearinghouseState", "user": _adr(1), "dex": "xyz"} in appels
    lignes = [json.loads(l) for l in (tmp_path / m.SORTIE_PORTEFEUILLES).read_text(encoding="utf-8").splitlines()]
    assert {(l["vault"], l["portfolio_scope"]) for l in lignes} == {
        (_adr(1), "DEX_PRINCIPAL"), (_adr(1), "DEX:xyz"), (_adr(2), "DEX_PRINCIPAL"), (_adr(2), "DEX:xyz"),
        (_adr(3), "DEX:xyz")}
    assert all(l["source"] == "CLEARINGHOUSE_REST" and l["nav_usd"] == 1000.0 for l in lignes)
    # chaque ligne est certifiable dans la famille des instantanés...
    kw = {"famille": CERT.FAMILLE_SNAPSHOT, "source": "CLEARINGHOUSE_REST", "now_ms": int(NOW * 1000) + 1}
    assert all(CERT.certifier_record(l, **kw)[1] == CERT.PASS for l in lignes)
    assert CERT.detecter_famille(m.SORTIE_PORTEFEUILLES.name)[0] == CERT.FAMILLE_SNAPSHOT
    # ... et le labo ne lit que le dex principal comme portefeuille complet
    evenements, vus, rejets = cop.position_events_from_snapshots(lignes)
    assert sorted(vus) == [_adr(1), _adr(2)] and rejets == {"portefeuille_autre_dex_non_fusionne": 3}
    assert set(evenements["coin"]) == {"BTC"}


def test_le_lanceur_releve_ces_portefeuilles_sans_option_particuliere():
    source = (RACINE / "tools" / "collecter_vaults.py").read_text(encoding="utf-8")
    assert "passe_portefeuilles_leaders(root)" in source and "--sans-leaders" in source
    from hl_observer.ops import collecteur_registry as REG

    entree = next(c for c in REG.REGISTRE if c["nom"] == "vault-collector")
    assert entree["script"] == "tools/collecter_vaults.py" and "--sans-leaders" not in entree["args"]
