"""Tests de l'archivage des tapes (reset de session sans perte)."""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import archiver_tapes as A  # noqa: E402


def _marquer_certifies(root: Path, *noms: str) -> None:
    """État du coffre tel que le certificateur l'écrit : ce contenu exact a été traité."""
    import json

    etat = root / A.ETAT_COFFRE
    etat.parent.mkdir(parents=True, exist_ok=True)
    courant = json.loads(etat.read_text(encoding="utf-8")) if etat.exists() else {}
    for nom in noms:
        chemin = root / "runtime" / "data" / nom
        courant[str(Path("runtime") / "data" / nom)] = {"sha256": A._sha256(chemin), "batch": "lot"}
    etat.write_text(json.dumps(courant), encoding="utf-8")


def test_archive_deplace_les_tapes_et_vide_data(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "vault_fills_live.jsonl").write_text('{"a":1}\n', encoding="utf-8")
    (data / "copy_vault_trades_lane.jsonl").write_text('{"b":2}\n', encoding="utf-8")
    (data / "collecteurs.lock").write_text("123", encoding="utf-8")       # operationnel -> reste
    (data / "explorer_autonome.pid").write_text("456", encoding="utf-8")  # operationnel -> reste
    _marquer_certifies(tmp_path, "vault_fills_live.jsonl", "copy_vault_trades_lane.jsonl")
    rap = A.archiver(tmp_path)
    assert rap["deplaces"] == 2
    # les tapes ont quitte runtime/data
    assert not (data / "vault_fills_live.jsonl").exists()
    assert not (data / "copy_vault_trades_lane.jsonl").exists()
    # les operationnels restent
    assert (data / "collecteurs.lock").exists()
    assert (data / "explorer_autonome.pid").exists()
    # elles sont dans l'archive (rien perdu)
    dest = Path(rap["dest"])
    assert (dest / "vault_fills_live.jsonl").read_text(encoding="utf-8") == '{"a":1}\n'
    assert (dest / "copy_vault_trades_lane.jsonl").exists()


def test_archive_vide_ne_fait_rien(tmp_path):
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    rap = A.archiver(tmp_path)
    assert rap["deplaces"] == 0 and rap["dest"] is None


def test_aucun_ruban_ne_quitte_data_sans_etre_passe_par_le_certificateur(tmp_path):
    """Certification échouée, interrompue ou jamais lancée : les rubans restent en place."""
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "vault_fills_poll.jsonl").write_text('{"a":1}\n', encoding="utf-8")       # jamais certifié
    (data / "bbo_tape.jsonl").write_text('{"b":2}\n', encoding="utf-8")               # certifié, puis modifié
    (data / "hl_allmids_tape.jsonl").write_text('{"c":3}\n', encoding="utf-8")        # certifié, intact
    (data / "flux_jamais_vu.jsonl").write_text('{"d":4}\n', encoding="utf-8")         # inconnu du certificateur
    (data / "explorer_inferred_fills.jsonl").write_text('{"e":5}\n', encoding="utf-8")  # écarté par conception
    (data / "vault_ledger.jsonl").write_text("", encoding="utf-8")                      # vide : rien à certifier
    _marquer_certifies(tmp_path, "bbo_tape.jsonl", "hl_allmids_tape.jsonl")
    with (data / "bbo_tape.jsonl").open("a", encoding="utf-8") as h:
        h.write('{"b":3}\n')                                                          # écrit après la certification
    rap = A.archiver(tmp_path)
    assert rap["deplaces"] == 3
    assert sorted(p.name for p in Path(rap["dest"]).iterdir()) == [
        "explorer_inferred_fills.jsonl", "hl_allmids_tape.jsonl", "vault_ledger.jsonl"]
    assert {l["fichier"]: l["raison"] for l in rap["retenus"]} == {
        "vault_fills_poll.jsonl": "jamais_certifie",
        "bbo_tape.jsonl": "modifie_depuis_la_certification",
        "flux_jamais_vu.jsonl": "jamais_certifie",
    }
    for nom in ("vault_fills_poll.jsonl", "bbo_tape.jsonl", "flux_jamais_vu.jsonl"):
        assert (data / nom).exists()                                   # toujours là, rien de perdu


def test_chaine_reelle_certifier_puis_archiver(tmp_path):
    """Le vrai certificateur puis le vrai archiveur : ce qui est certifié part, le reste attend."""
    import json

    import sceller_coffre_local as scl

    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    now = 1_800_000_000_000
    fill = {"coin": "MINA", "px": "0.05", "sz": "3.0", "side": "B", "time": now - 1000, "tid": 1,
            "vault": "0x07fd993f0fa3a185f7207adccd29f7a87404689d", "source": "LIVE_POLL",
            "isSnapshot": False, "observed_at_ms": now - 500}
    (data / "vault_fills_poll.jsonl").write_text(json.dumps(fill) + "\n", encoding="utf-8")
    (data / "flux_jamais_vu.jsonl").write_text('{"mystere":1}\n', encoding="utf-8")
    assert A.archiver(tmp_path)["deplaces"] == 0                       # rien n'a encore été certifié
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(now)]) == 0
    rap = A.archiver(tmp_path)
    assert rap["deplaces"] == 1 and not (data / "vault_fills_poll.jsonl").exists()
    assert [l["fichier"] for l in rap["retenus"]] == ["flux_jamais_vu.jsonl"]
    assert (data / "flux_jamais_vu.jsonl").exists()                    # signalé INCONNU, jamais déplacé en silence
