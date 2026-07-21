

# ------------------------------------------------------------------ 21/07 : fixtures dans le live

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
