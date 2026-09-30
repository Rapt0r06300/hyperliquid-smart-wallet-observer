from __future__ import annotations

import json
import sys
import zipfile
from datetime import datetime, timezone
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import release_artifacts as RA  # noqa: E402


def _archive(tmp_path: Path) -> Path:
    manifeste = {
        "hypersmart_version": "24.1.0",
        "git_sha": "a" * 40,
        "source_date_epoch": 1_700_000,
        "empreinte_globale": "b" * 64,
        "etat_git": {"dirty": False},
        "deps": [
            "httpx==0.28.1 --hash=sha256:" + "c" * 64,
            "pytest==9.0.2 --hash=sha256:" + "d" * 64,
        ],
        "fichiers": {
            "LICENSE": {"sha256": "e" * 64, "taille": 3},
            "src/hl_observer/app.py": {"sha256": "f" * 64, "taille": 10},
            "src/hl_observer/collection/source.py": {"sha256": "1" * 64, "taille": 20},
        },
        "sbom": {"licences": ["LICENSE"]},
        "donnees_exclues": [
            ".git/", "dist/", ".env", "moisson_console.txt",
            "outils de test/rapports/analyse_599.txt",
        ],
    }
    archive = tmp_path / "hypersmart.zip"
    with zipfile.ZipFile(archive, "w") as z:
        z.writestr("PORTABLE_MANIFEST.json", json.dumps(manifeste))
    return archive


def test_sbom_cyclonedx_exact_et_deterministe(tmp_path):
    archive = _archive(tmp_path)
    with zipfile.ZipFile(archive) as z:
        manifeste = json.loads(z.read("PORTABLE_MANIFEST.json"))
    a = RA.construire_sbom_cyclonedx(manifeste)
    b = RA.construire_sbom_cyclonedx(manifeste)
    assert a == b
    assert a["bomFormat"] == "CycloneDX" and a["specVersion"] == "1.6"
    assert [(x["name"], x["version"]) for x in a["components"]] == [
        ("httpx", "0.28.1"), ("pytest", "9.0.2"),
    ]


def test_produit_tous_les_artefacts_externes(tmp_path):
    archive = _archive(tmp_path)
    validation = {
        "tests": {"ok": True, "passes": 321},
        "modules": {"ok": True, "verifies": 2},
        "zero_ecriture_externe": {"ok": True, "observations": []},
    }
    verdict = {
        "RELEASE_READY": True,
        "manquants": [],
        "gates": [{"gate": "tests", "ok": True, "detail": "321 passes"}],
    }
    res = RA.produire_artefacts_release(
        archive, validation=validation, verdict=verdict,
        horloge=lambda: datetime(2026, 8, 2, 12, 0, tzinfo=timezone.utc),
    )
    attendus = set(RA.NOMS_ARTEFACTS.values()) | {archive.name + ".sha256"}
    assert set(res["artefacts"]) == attendus
    assert all((tmp_path / nom).is_file() for nom in attendus)
    rapport = json.loads((tmp_path / "RELEASE_REPORT.json").read_text(encoding="utf-8"))
    assert rapport["RELEASE_READY"] is True
    assert rapport["archive_sha256"] == res["archive_sha256"]
    assert rapport["date_rapport_utc"] == "2026-08-02T12:00:00+00:00"
    inventaire = json.loads((tmp_path / "INVENTAIRE_RELEASE.json").read_text(encoding="utf-8"))
    assert "src/hl_observer/app.py" in inventaire["inclus"]
    assert {x["justification"] for x in inventaire["exclus"]} >= {
        "controle_version_source", "ancienne_release_interdite", "secret_interdit",
        "sortie_runtime_machine",
    }
    modules = json.loads(
        (tmp_path / "MODULES_COLLECTEURS_VERIFIES.json").read_text(encoding="utf-8")
    )
    assert "src/hl_observer/collection/source.py" in modules["collecteurs"]
    checksum = (tmp_path / (archive.name + ".sha256")).read_text(encoding="ascii")
    assert checksum == "%s  %s\n" % (res["archive_sha256"], archive.name)
