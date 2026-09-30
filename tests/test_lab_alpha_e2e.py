"""[LAB α] E2E : « double-clic » jusqu'au rapport. Découverte auto → feed_adapter → chemin unique (Copy-Vault +
cross-venue 2 jambes + Lead-Lag + netting + risk) → IS/OOS/FORWARD → rapport ; reprise après interruption ;
ledger réconcilié ; paper strict (0 ordre réel). Données de fixture SYNTHETIQUE (exclues du verdict économique)."""

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops.lab_alpha import lancer_lab, main   # noqa: E402

T = 1_700_000_000_000


def _ecrire_donnees(root):
    d = root / "runtime" / "data"
    d.mkdir(parents=True)
    rows = []
    for i in range(40):
        px = 60000.0 + i * 10.0
        rows.append({"coin": "BTC", "px": px, "mid": px, "sz": 0.3, "signe": 1 if i % 2 == 0 else -1,
                     "ts_ms": T + i * 1000, "vault": "A",
                     "book": {"asks": [[px + 10.0, 5.0]], "bids": [[px - 10.0, 5.0]]}})
    rows.append({"coin": "ETH", "px": 3000.0, "mid": 3000.0, "sz": 0.5, "signe": 1, "ts_ms": T + 10500, "vault": "C",
                 "book": {"asks": [[3000.0, 10.0]], "bids": [[2999.0, 10.0]]},
                 "cross_venue": {"edge_bps": 26.0, "venue_hedge": "BINANCE",
                                 "carnet_hedge": {"bids": [[3008.0, 10.0]], "asks": [[3010.0, 10.0]]},
                                 "latences_ms": [10, 20, 30, 40, 50]}})
    rows.append({"coin": "SOL", "px": 150.0, "mid": 150.0, "sz": 1.0, "signe": 1, "ts_ms": T + 11500, "vault": "D",
                 "book": {"asks": [[150.1, 0.0001]], "bids": [[149.9, 0.0001]]}})          # carnet mince -> missed
    rows.append({"coin": "BTC", "px": 60000.0, "mid": 60000.0, "sz": 5.0, "signe": 1, "ts_ms": T + 12500, "vault": "F",
                 "book": {"asks": [[60010.0, 5.0]], "bids": [[59990.0, 5.0]]}})             # trop gros -> risk
    (d / "ticks.jsonl").write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def test_lab_e2e_double_clic_jusqu_au_rapport(tmp_path):
    _ecrire_donnees(tmp_path)
    res = lancer_lab(racine=tmp_path, source="SYNTHETIQUE", budget=8, horodatage="2026-08-01T12:00:00Z")
    assert res["events"] > 0 and res["events_valides"] > 0
    latest = Path(res["rapport"]["latest"])
    assert latest.exists() and "VERDICT" in latest.read_text(encoding="utf-8")
    assert Path(res["rapport"]["json"]).exists() and Path(res["rapport"]["manifeste"]).exists()
    par_nom = {b["brique"]: b["statut"] for b in res["audit"]["bricks"]}
    assert par_nom["feed_adapter"] == "CABLE ET UTILISE" and par_nom["risk gates"] == "CABLE ET UTILISE"
    assert res["recherche"]["evalues"] > 0
    assert res["verdict"].startswith("NON MESURABLE")            # synthétique exclu de l'économique
    assert "LABORATOIRE ALPHA" in res["tableau"] and Path(res["journal"]).exists()


def test_lab_e2e_cross_venue_deux_jambes_et_lead_lag(tmp_path):
    _ecrire_donnees(tmp_path)
    res = lancer_lab(racine=tmp_path, source="SYNTHETIQUE", budget=6, horodatage="H")
    assert res["lead_lag"]["score"] != "UNMEASURABLE"           # lead-lag mesuré sur la séquence
    par_nom = {b["brique"]: b["statut"] for b in res["audit"]["bricks"]}
    assert par_nom["Cross-Venue"] == "CABLE ET UTILISE"
    assert any(c.get("cross_venue", 0) for c in res["recherche"]["candidats"])   # 2 jambes exécutées


def test_lab_e2e_reprise_et_paper_strict(tmp_path):
    _ecrire_donnees(tmp_path)
    cp = tmp_path / "ckpt.jsonl"
    r1 = lancer_lab(racine=tmp_path, source="SYNTHETIQUE", budget=8, checkpoint_path=cp, horodatage="H")
    r2 = lancer_lab(racine=tmp_path, source="SYNTHETIQUE", budget=8, checkpoint_path=cp, horodatage="H")
    assert r1["recherche"]["evalues"] > 0 and r2["recherche"]["caches"] > 0       # reprise sans tout refaire
    assert main(["--no-dry-run"]) == 2                                             # paper strict
