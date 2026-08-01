"""[LAB α] lab_rapport : RAPPORT_LATEST.md + JSON + manifeste (hashes) + verdict affiché."""

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops.lab_rapport import ecrire_rapport, verdict_affiche   # noqa: E402

_INV = {"total_fichiers": 1, "total_octets": 50, "lisibles": 1, "bloques": 0,
        "dossiers": [{"dossier": "runtime/data", "present": True, "n_fichiers": 1, "octets": 50}],
        "fichiers": [{"rel": "a.jsonl", "format": "JSONL", "octets": 50, "hash": "deadbeef",
                      "lisible": True, "raison": "OK"}]}
_AUDIT = {"bricks": [{"brique": "feed_adapter", "statut": "CABLE ET UTILISE"}], "resume": {}}
_RECH = {"verdict_global": "NON_MESURABLE", "evalues": 3, "caches": 0, "n_candidats": 3,
         "prometteuses": 0, "candidats": [], "meilleur": None}


def test_ecrire_rapport_ecrit_les_fichiers(tmp_path):
    res = ecrire_rapport(tmp_path, horodatage="2026-08-01T12:00:00", inventaire=_INV, audit=_AUDIT,
                         recherche=_RECH, source="REEL")
    assert Path(res["latest"]).exists() and Path(res["json"]).exists() and Path(res["manifeste"]).exists()
    md = Path(res["latest"]).read_text(encoding="utf-8")
    assert "VERDICT" in md and "NON MESURABLE" in md and "feed_adapter" in md and res["verdict"] == "NON MESURABLE"


def test_manifeste_porte_les_hashes(tmp_path):
    res = ecrire_rapport(tmp_path, horodatage="H", inventaire=_INV, audit=_AUDIT, recherche=_RECH)
    man = json.loads(Path(res["manifeste"]).read_text(encoding="utf-8"))
    assert man["fichiers"][0]["hash"] == "deadbeef" and man["total_octets"] == 50


def test_verdict_mapping():
    assert verdict_affiche("POSITIF") == "POSITIF"
    assert verdict_affiche("NON_ECONOMIQUE_SYNTHETIQUE").startswith("NON MESURABLE")
