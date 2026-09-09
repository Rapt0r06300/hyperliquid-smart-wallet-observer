from __future__ import annotations

import json

from hl_observer.signals.porte_copy_whitelist import signal_copy_autorise


def test_whitelist_legacy_seule_ne_peut_pas_autoriser(tmp_path) -> None:
    whitelist = tmp_path / "runtime" / "data" / "copy_whitelist.json"
    whitelist.parent.mkdir(parents=True, exist_ok=True)
    whitelist.write_text(
        json.dumps(
            {
                "genere_ts": 1_000.0,
                "gardes": [{"adresse": "0xabc"}],
            }
        ),
        encoding="utf-8",
    )

    autorise, motif = signal_copy_autorise(["0xabc"], root=tmp_path, now=1_001.0)

    assert autorise is False
    assert motif == "COPY_CERTIFICATION_VNEXT_ABSENTE_OU_INVALIDE"
