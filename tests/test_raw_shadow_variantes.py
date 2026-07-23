"""Shadow multi-seuils × âge réel (rectif Flo 24/07) : on prouve que la grille classe les OPEN par seuil
relatif (frac × TVL clampé) ET par bucket d'âge, mesure un net forward, et exclut correctement sous le
seuil. PUR (journal + tape + TVL). Ne touche pas la cohorte live."""
from __future__ import annotations

import json

from hl_observer.experimental import raw_shadow_variantes as RS


def test_grille_seuils_relatifs_et_buckets_age(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    T = 1_000_000_000_000
    full = "0xvaultaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"        # TVL 500k -> 0.001 = 500$, 0.002 = 1000$
    (tmp_path / "runtime" / "data" / "vaults_scores.json").write_text(json.dumps({
        "classement": [{"vault": full, "retenu": False, "facteurs": {"tvl_usd": 500_000.0}}]}))
    # 6 OPEN Long FRAIS (latence 500ms) + 2 OPEN Long VIEUX (latence 3000ms), notional 800$ (sz800×px1)
    lignes = [{"coin": "DOT", "vault": full[:12], "dir": "Open Long", "sz": 800, "px": 1.0,
               "fill_ts_ms": T + i * 60000, "latence_fill_decision_ms": 500} for i in range(6)]
    lignes += [{"coin": "DOT", "vault": full[:12], "dir": "Open Long", "sz": 800, "px": 1.0,
                "fill_ts_ms": T + (10 + i) * 60000, "latence_fill_decision_ms": 3000} for i in range(2)]
    (tmp_path / RS.JOURNAL_RELPATH).write_text("\n".join(json.dumps(x) for x in lignes))
    tape = {"DOT": [(T + i * 60000, 100.0 + i * 0.1) for i in range(300)]}   # monte -> net forward > 0
    p = RS.mesurer(tmp_path, tape=tape)

    assert p["n_open_journal"] == 8 and p["variante"] == "v1"
    def cell(frac, bkt):
        return [g for g in p["grille"] if g["frac_tvl"] == frac and g["bucket_age"] == bkt][0]
    assert cell(0.001, "<1s")["n"] == 6 and cell(0.001, "<1s")["positif"] is True   # seuil 500 < 800 -> inclus, tape monte
    assert cell(0.001, "2-5s")["n"] == 2                                             # les 2 vieux -> bucket d'âge séparé
    assert cell(0.002, "<1s")["n"] == 0                                             # seuil 1000 > 800 -> EXCLU


def test_ecrire_versionne(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (tmp_path / RS.JOURNAL_RELPATH).write_text("")
    p = RS.ecrire(tmp_path, tape={})
    assert p.exists()
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["variante"] == "v1" and "grille" in d and d["plafond_usd"] == 2000.0
