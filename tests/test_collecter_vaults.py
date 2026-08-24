"""COLLECTEUR DE VAULTS HL (chantier COPY, 23/07). La dernière porte copy : répliquer une trajectoire
de vault (horizon jours) où nos 62 s sont négligeables. Ces tests prouvent qu'on capture TOUT (NAV,
positions, expo, levier, PnL latent+réalisé, drawdown, delta d'expo), qu'on exclut les vaults de MM,
et qu'on n'invente rien. Aucun réseau réel : tout bouchonné.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod():
    spec = importlib.util.spec_from_file_location("cv", RACINE / "tools" / "collecter_vaults.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


_CH = {"marginSummary": {"accountValue": "10000.0"},
       "assetPositions": [
           {"position": {"coin": "ETH", "szi": "5.0", "entryPx": "3000", "positionValue": "15000",
                         "unrealizedPnl": "200", "leverage": {"value": 3}}},
           {"position": {"coin": "BTC", "szi": "-0.2", "entryPx": "60000", "positionValue": "12000",
                         "unrealizedPnl": "-100", "leverage": {"value": 2}}}]}
_VD = {"leader": "0xabc", "apr": 0.5, "portfolio": [
    ["day", {}], ["allTime", {"accountValueHistory": [[1, "100"], [2, "120"], [3, "90"]],
                              "pnlHistory": [[1, "0"], [3, "-10"]]}]]}


def test_clearinghouse_capture_nav_expo_levier_pnl_latent():
    m = _mod()
    r = m.parser_clearinghouse(_CH)
    assert r["nav_usd"] == 10000.0 and r["n_positions"] == 2
    assert r["expo_brute_usd"] == 27000.0 and r["expo_nette_usd"] == 3000.0   # 15000-12000
    assert r["levier"] == 2.7 and r["pnl_latent_usd"] == 100.0                # 200-100
    assert m.parser_clearinghouse("nawak") is None                           # illisible -> None


def test_vault_details_capture_hist_et_pnl_realise():
    m = _mod()
    r = m.parser_vault_details(_VD)
    assert r["nav_hist"] == [100.0, 120.0, 90.0] and r["pnl_realise_usd"] == -10.0
    assert m.parser_vault_details("nawak")["nav_hist"] == []                  # tolérant


def test_drawdown_pic_a_creux():
    m = _mod()
    assert m.drawdown_pct([100, 120, 90]) == -25.0                            # (90-120)/120
    assert m.drawdown_pct([]) == 0.0


def test_snapshot_calcule_le_DELTA_d_exposition():
    m = _mod()
    cs = m.parser_clearinghouse(_CH)
    vd = m.parser_vault_details(_VD)
    snap = m.construire_snapshot("0xv", cs, vd, now=1000.0, etat_prec={"expo_nette_usd": 2000.0})
    assert snap["delta_expo_nette_usd"] == 1000.0                             # 3000 - 2000
    assert snap["drawdown_pct"] == -25.0 and snap["real_execution"] is False


def test_les_vaults_de_MARKET_MAKING_sont_exclus(tmp_path):
    m = _mod()
    d = tmp_path / "runtime" / "data"
    d.mkdir(parents=True)
    hlp = next(iter(m.VAULTS_EXCLUS))
    (d / "vaults_suivis.json").write_text(json.dumps({"vaults": ["0xDIRECTIONNEL", hlp, "0xdirectionnel"]}),
                                          encoding="utf-8")
    assert m.charger_vaults_suivis(tmp_path) == ["0xdirectionnel"]            # HLP exclu, dédupliqué


def test_une_passe_ecrit_un_snapshot_complet(tmp_path, monkeypatch):
    m = _mod()

    def faux_post(charge, **_k):
        return _CH if charge.get("type") == "clearinghouseState" else _VD

    monkeypatch.setattr(m, "_post_info", faux_post)
    n = m.une_passe(tmp_path, ["0xv"], now=1000.0)
    assert n == 1
    snap = json.loads((tmp_path / m.SORTIE).read_text(encoding="utf-8").splitlines()[0])
    assert snap["vault"] == "0xv" and snap["nav_usd"] == 10000.0 and snap["levier"] == 2.7
    assert snap["pnl_realise_usd"] == -10.0 and snap["n_positions"] == 2


def test_reseau_coupe_ne_tue_pas_la_passe(tmp_path, monkeypatch):
    m = _mod()

    def boom(*_a, **_k):
        raise OSError("reseau")

    monkeypatch.setattr(m, "_post_info", boom)
    assert m.une_passe(tmp_path, ["0xv"], now=1000.0) == 0


def test_resume_honnete_quand_vide(tmp_path):
    m = _mod()
    assert m.resume(tmp_path)["verdict"] == "AUCUN_VAULT_SUIVI_OU_COLLECTE"


def _snaps(net, *, jours=4.0, dd=-10.0, n=15):
    pas = jours * 86_400_000.0 / n
    return [{"nav_usd": 10000.0, "expo_brute_usd": 20000.0, "expo_nette_usd": net,
             "levier": 2.0, "drawdown_pct": dd, "ts_ms": int(i * pas)} for i in range(n)]


def test_classer_retient_un_DIRECTIONNEL_sain():
    m = _mod()
    r = m.classer_vault(_snaps(15000.0))                       # net/gross = 0.75 -> directionnel
    assert r["verdict"] == "RETENU_DIRECTIONNEL" and r["directionnalite"] == 0.75


def test_classer_ECARTE_un_market_maker_net_proche_de_zero():
    m = _mod()
    assert m.classer_vault(_snaps(300.0))["verdict"] == "ECARTE_MARKET_MAKING"   # net/gross 0.015


def test_classer_ECARTE_un_vault_trop_jeune():
    m = _mod()
    assert m.classer_vault(_snaps(15000.0, jours=1.0))["verdict"] == "ECARTE_TROP_JEUNE"


def test_classer_ne_se_fie_ni_au_nom_ni_a_l_apr_et_exige_de_la_donnee():
    m = _mod()
    assert m.classer_vault(_snaps(15000.0, n=5))["verdict"] == "INSUFFISANT"      # < 10 snapshots


def test_import_assiste_fusionne_et_exclut_les_MM(tmp_path):
    m = _mod()
    hlp = next(iter(m.VAULTS_EXCLUS))
    assert m.importer_vaults(tmp_path, ["0xAAA", hlp, "0xaaa", "0xBBB"]) == 2   # dédup + HLP exclu
    assert set(m.charger_vaults_suivis(tmp_path)) == {"0xaaa", "0xbbb"}


def _vault_public(address, *, tvl=250_000, age_days=100, now_ms=2_000_000_000_000,
                  closed=False, relationship="normal", apr=0.25):
    return {
        "apr": apr,
        "summary": {
            "vaultAddress": address,
            "name": f"Vault {address[-4:]}",
            "tvl": tvl,
            "isClosed": closed,
            "relationship": {"type": relationship},
            "createTimeMillis": now_ms - age_days * 86_400_000,
        },
    }


def test_parser_univers_public_filtre_et_trie_sans_promouvoir():
    m = _mod()
    now_ms = 2_000_000_000_000
    first = "0x1111111111111111111111111111111111111111"
    second = "0x2222222222222222222222222222222222222222"
    payload = [
        _vault_public(first, tvl=300_000, now_ms=now_ms),
        _vault_public(second, tvl=900_000, now_ms=now_ms),
        _vault_public("0x3333333333333333333333333333333333333333", tvl=99_999, now_ms=now_ms),
        _vault_public("0x4444444444444444444444444444444444444444", age_days=44, now_ms=now_ms),
        _vault_public("0x5555555555555555555555555555555555555555", closed=True, now_ms=now_ms),
        _vault_public("0x6666666666666666666666666666666666666666", relationship="child", now_ms=now_ms),
        _vault_public("0xtronquee...", now_ms=now_ms),
        _vault_public(second.upper().replace("0X", "0x"), tvl=800_000, now_ms=now_ms),
    ]

    result = m.parser_univers_public(payload, now_ms=now_ms)

    assert [row["address"] for row in result] == [second, first]
    assert all(row["observation_only"] is True for row in result)
    assert result[0]["tvl_usd"] == 900_000


def test_rafraichissement_public_preserve_manuel_et_provenance(tmp_path):
    m = _mod()
    now_ms = 2_000_000_000_000
    managed = "0x1111111111111111111111111111111111111111"
    manual = "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    fresh = "0x2222222222222222222222222222222222222222"
    destination = tmp_path / m.CONFIG
    destination.parent.mkdir(parents=True)
    destination.write_text(json.dumps({
        "_provenance": {"vaults": [{"address": managed}]},
        "vaults": [managed, manual],
    }), encoding="utf-8")

    result = m.rafraichir_univers_public(
        tmp_path,
        fetcher=lambda: [_vault_public(fresh, now_ms=now_ms)],
        now_ms=now_ms,
    )

    assert result["vaults"] == [fresh, manual]
    assert result["_provenance"]["source"] == m.URL_VAULTS
    assert result["_provenance"]["manual_preserved"] == [manual]
    assert json.loads(destination.read_text(encoding="utf-8")) == result


def test_rafraichissement_vide_preserve_strictement_ancien_fichier(tmp_path):
    m = _mod()
    destination = tmp_path / m.CONFIG
    destination.parent.mkdir(parents=True)
    original = '{"vaults":["0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"]}'
    destination.write_text(original, encoding="utf-8")

    try:
        m.rafraichir_univers_public(tmp_path, fetcher=lambda: [])
    except ValueError as exc:
        assert "préservé" in str(exc)
    else:
        raise AssertionError("un univers vide doit échouer fail-closed")

    assert destination.read_text(encoding="utf-8") == original
