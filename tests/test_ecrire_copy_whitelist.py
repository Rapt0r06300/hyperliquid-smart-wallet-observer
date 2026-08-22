

# ------------------------------------------------------------------ 21/07 : fixtures dans le live


def test_une_rafale_de_fills_identiques_ne_devient_pas_une_preuve_statistique(tmp_path):
    """43 lignes a 1 ms d'ecart ne sont pas 43 decisions independantes du leader."""
    import importlib.util as _u
    from pathlib import Path as _P

    racine = _P(__file__).resolve().parents[1]
    spec = _u.spec_from_file_location("wl_dedupe", racine / "tools" / "ecrire_copy_whitelist.py")
    m = _u.module_from_spec(spec)
    spec.loader.exec_module(m)
    rows = [
        {
            "adresse": "0xabc",
            "coin": "BTC",
            "side": "LONG",
            "mid_at_fill": 100.0,
            "mid_forward": 101.0,
            "ts_ms": 1_700_000_000_000 + i,
        }
        for i in range(43)
    ]
    result = m.construire_whitelist(tmp_path, fills=rows)
    detail = result["details"][0]
    assert result["fills_bruts"] == 43
    assert result["episodes_independants"] == 1
    assert detail["n_events"] == 1
    assert detail["n_fills_bruts"] == 43
    assert result["gardes"] == []


def test_les_episodes_separes_restent_des_observations_independantes(tmp_path):
    import importlib.util as _u
    from pathlib import Path as _P

    racine = _P(__file__).resolve().parents[1]
    spec = _u.spec_from_file_location("wl_episodes", racine / "tools" / "ecrire_copy_whitelist.py")
    m = _u.module_from_spec(spec)
    spec.loader.exec_module(m)
    rows = [
        {
            "adresse": "0xabc",
            "coin": "BTC",
            "side": "LONG",
            "mid_at_fill": 100.0,
            "mid_forward": 101.0,
            "ts_ms": 1_700_000_000_000 + i * 1_800_001,
        }
        for i in range(20)
    ]
    result = m.construire_whitelist(tmp_path, fills=rows)
    assert result["episodes_independants"] == 20
    assert result["details"][0]["n_events"] == 20
    assert result["gardes"][0]["adresse"] == "0xabc"


def test_des_markouts_30_minutes_qui_se_chevauchent_ne_sont_pas_independants(tmp_path):
    import importlib.util as _u
    from pathlib import Path as _P

    racine = _P(__file__).resolve().parents[1]
    spec = _u.spec_from_file_location("wl_horizon", racine / "tools" / "ecrire_copy_whitelist.py")
    m = _u.module_from_spec(spec)
    spec.loader.exec_module(m)
    rows = [
        {
            "adresse": "0xabc",
            "coin": "SPX",
            "side": "LONG",
            "mid_at_fill": 100.0,
            "mid_forward": 101.0,
            "ts_ms": 1_700_000_000_000 + i * 61_000,
        }
        for i in range(20)
    ]
    result = m.construire_whitelist(tmp_path, fills=rows)
    assert result["fills_bruts"] == 20
    assert result["episodes_independants"] == 1
    assert result["gardes"] == []

def test_un_fill_synthetique_n_entre_JAMAIS_dans_la_chaine_copy(tmp_path):
    """🔴 L'audit de fraîcheur a mesuré 495 734 h d'étendue (56 ans) sur les fills de leaders :
    3 lignes portaient `ts_ms=0` et des adresses `0x1111...`. Un leader FABRIQUÉ qui
    accumulerait assez de fills pourrait entrer dans la whitelist — c'est-à-dire déverrouiller
    le copy sur de la donnée inventée. C'est la règle n°1 du projet qui tombait."""
    import importlib.util as _u
    import json as _j
    from pathlib import Path as _P

    racine = _P(__file__).resolve().parents[1]
    spec = _u.spec_from_file_location("wl", racine / "tools" / "ecrire_copy_whitelist.py")
    m = _u.module_from_spec(spec)
    spec.loader.exec_module(m)

    d = tmp_path / "runtime" / "data"
    d.mkdir(parents=True, exist_ok=True)
    (d / "leader_fills_bruts.jsonl").write_text("\n".join([
        _j.dumps({"adresse": "0x1111111111111111111111111111111111111111", "coin": "HYPE",
                  "side": "B", "ts_ms": 0}),
        _j.dumps({"adresse": "0x0000000000000000000000000000000000000000", "coin": "HYPE",
                  "side": "B", "ts_ms": 1_784_000_000_000}),
        _j.dumps({"adresse": "0xabc1234567890abcdef1234567890abcdef1234", "coin": "HYPE",
                  "side": "B", "ts_ms": 1_784_000_000_000}),
    ]), encoding="utf-8")

    src = (racine / "tools" / "ecrire_copy_whitelist.py").read_text(encoding="utf-8")
    assert "1_577_836_800.0 <= ts" in src, "aucun garde sur l'horodatage des fills"
    assert "adresse synthetique" in src or "synthetique" in src, "aucun garde sur les adresses"
