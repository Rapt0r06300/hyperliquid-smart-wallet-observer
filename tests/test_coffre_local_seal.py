"""Tests du module de certification + scelleur du coffre-fort local (tier LOCAL)."""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.datasets.coffre_certifie import (  # noqa: E402
    FAMILLE_BOOK_L2, FAMILLE_FILLS_FORWARD, PASS, QUARANTAINE, REPARE,
    certifier_record, detecter_famille, identite,
)
import sceller_coffre_local as scl  # noqa: E402

NOW = 1_800_000_000_000  # horloge fixe pour des tests déterministes


def _fill(**kw):
    base = {"coin": "MINA", "px": "0.05307", "sz": "335.0", "side": "B",
            "time": NOW - 1000, "vault": "0x07fd993f0fa3a185f7207adccd29f7a87404689d",
            "source": "LIVE_POLL", "isSnapshot": False, "observed_at_ms": NOW - 500}
    base.update(kw)
    return base


def _book(**kw):
    base = {"coin": "XRP", "received_at_ms": NOW - 100, "exchange_ts_ms": NOW - 120,
            "bid": 1.2913, "ask": 1.2914,
            "bids5": [[1.2913, 1824.0], [1.2912, 10563.0]],
            "asks5": [[1.2914, 27409.0], [1.2915, 22559.0]]}
    base.update(kw)
    return base


def test_fill_forward_normalisation_est_pass():
    # format brut normal (px/sz texte, side="B") -> accepté (PASS), pas une "réparation"
    norm, decision, _ = certifier_record(_fill(), famille=FAMILLE_FILLS_FORWARD,
                                         source="LIVE_POLL", now_ms=NOW)
    assert decision == PASS
    assert isinstance(norm["px"], float) and isinstance(norm["sz"], float)
    assert norm["signe"] == 1 and norm["causal_forward_eligible"] is True


def test_fill_signe_reconstruit_depuis_dir_est_repare():
    # pas de side ni signe, mais dir="Close Long" -> sens reconstruit = RÉPARÉ
    norm, decision, _ = certifier_record(
        _fill(side=None, fill_side=None, dir="Close Long"),
        famille=FAMILLE_FILLS_FORWARD, source="LIVE_POLL", now_ms=NOW,
    )
    assert decision == REPARE and norm["signe"] == -1


def test_fill_forward_sans_observed_quarantaine():
    _, decision, raison = certifier_record(_fill(observed_at_ms=None),
                                           famille=FAMILLE_FILLS_FORWARD,
                                           source="LIVE_POLL", now_ms=NOW)
    assert decision == QUARANTAINE and raison == "forward_sans_observed_at_ms"


def test_fill_px_negatif_quarantaine():
    _, decision, raison = certifier_record(_fill(px="-1"), famille=FAMILLE_FILLS_FORWARD,
                                           source="LIVE_POLL", now_ms=NOW)
    assert decision == QUARANTAINE and raison == "px_invalide"


def test_fill_timestamp_futur_quarantaine():
    _, decision, raison = certifier_record(_fill(time=NOW + 10_000_000),
                                           famille=FAMILLE_FILLS_FORWARD,
                                           source="LIVE_POLL", now_ms=NOW)
    assert decision == QUARANTAINE and raison == "timestamp_futur"


def test_book_valide_pass():
    _, decision, _ = certifier_record(_book(), famille=FAMILLE_BOOK_L2, source="L2", now_ms=NOW)
    assert decision == PASS


def test_book_croise_quarantaine():
    b = _book(bids5=[[1.30, 10.0]], asks5=[[1.29, 10.0]], bid=1.30, ask=1.29)
    _, decision, raison = certifier_record(b, famille=FAMILLE_BOOK_L2, source="L2", now_ms=NOW)
    assert decision == QUARANTAINE and raison == "marche_croisee"


def test_book_lag_depasse_quarantaine():
    b = _book(received_at_ms=NOW, exchange_ts_ms=NOW - 10_000_000)
    _, decision, raison = certifier_record(b, famille=FAMILLE_BOOK_L2, source="L2", now_ms=NOW)
    assert decision == QUARANTAINE and raison in ("lag_causal_depasse", "timestamp_futur")


def test_detecter_famille():
    assert detecter_famille("vault_fills_poll.jsonl")[0] == FAMILLE_FILLS_FORWARD
    assert detecter_famille("copy_vault_l2_tape.jsonl")[0] == FAMILLE_BOOK_L2
    assert detecter_famille("vault_fills_poll.jsonl.gz")[0] == FAMILLE_FILLS_FORWARD
    assert detecter_famille("un_fichier_inconnu.jsonl") is None


def test_identite_dedup():
    a = certifier_record(_fill(), famille=FAMILLE_FILLS_FORWARD, source="LIVE_POLL", now_ms=NOW)[0]
    b = certifier_record(_fill(), famille=FAMILLE_FILLS_FORWARD, source="LIVE_POLL", now_ms=NOW)[0]
    assert identite(a, FAMILLE_FILLS_FORWARD) == identite(b, FAMILLE_FILLS_FORWARD)


def test_scellage_bout_en_bout(tmp_path):
    root = tmp_path
    data = root / "runtime" / "data"
    data.mkdir(parents=True)
    lignes = [
        json.dumps(_fill(tid=1)),               # bon (réparé)
        json.dumps(_fill(tid=1)),               # doublon
        json.dumps(_fill(tid=2, px="-5")),      # quarantaine px
        json.dumps(_fill(tid=3, observed_at_ms=None)),  # quarantaine forward
        "ligne non json",                       # quarantaine json
    ]
    (data / "vault_fills_poll.jsonl").write_text("\n".join(lignes), encoding="utf-8")

    rc = scl.main(["--root", str(root), "--now-ms", str(NOW)])
    assert rc == 0

    coffre = root / "runtime" / "coffre_certifie"
    local_index = json.loads((coffre / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
    assert len(local_index["shards"]) == 1
    shard = local_index["shards"][0]
    assert shard["deposes"] == 1 and shard["tier"] == "LOCAL"
    assert "MINA" in shard["coins"]

    # shard gzip contient 1 enregistrement étiqueté LOCAL
    shard_path = root / shard["shard"]
    with gzip.open(shard_path, "rt", encoding="utf-8") as h:
        deposes = [json.loads(l) for l in h if l.strip()]
    assert len(deposes) == 1 and deposes[0]["tier"] == "LOCAL"
    assert deposes[0]["reconciliation_status"] == "LOCAL_UNRECONCILED"

    # quarantaine : 3 rejets (px, forward, json) écrits avec raison
    quar_files = list((coffre / "quarantine").rglob("*.jsonl"))
    assert quar_files, "fichier de quarantaine attendu"
    rejets = [json.loads(l) for l in quar_files[0].read_text(encoding="utf-8").splitlines() if l.strip()]
    assert len(rejets) == 3
    assert {r["raison"] for r in rejets} == {"px_invalide", "forward_sans_observed_at_ms", "json_invalide"}

    # COFFRE_INDEX + journal présents
    coffre_index = json.loads((coffre / "COFFRE_INDEX.json").read_text(encoding="utf-8"))
    assert coffre_index["tiers"]["LOCAL"]["deposes"] == 1
    assert coffre_index["tiers"]["SAFE_CLOUD"]["catalogue"] == "catalog/DATA_INDEX.json"
    assert (coffre / "CERTIF_JOURNAL.jsonl").exists()


def test_scellage_idempotent(tmp_path):
    root = tmp_path
    data = root / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "vault_fills_poll.jsonl").write_text(json.dumps(_fill(tid=7)), encoding="utf-8")
    assert scl.main(["--root", str(root), "--now-ms", str(NOW)]) == 0
    idx1 = json.loads((root / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
    # 2e passage : fichier inchangé -> sauté, pas de nouveau shard
    assert scl.main(["--root", str(root), "--now-ms", str(NOW)]) == 0
    idx2 = json.loads((root / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
    assert len(idx2["shards"]) == len(idx1["shards"]) == 1


def test_sniffer_fichier_nom_inconnu(tmp_path):
    """--tout attrape une donnée au NOM non standard, reconnue par son contenu."""
    root = tmp_path
    sousdossier = root / "vieilles_recoltes" / "2026-10"
    sousdossier.mkdir(parents=True)
    # nom arbitraire, contenu = fills forward valides, taille > 64 Ko (vrai flux)
    gros = "\n".join(json.dumps(_fill(tid=i)) for i in range(500))
    (sousdossier / "export_bizarre_123.jsonl").write_text(gros, encoding="utf-8")
    # un fichier jsonl NON-données (meme gros) ne doit PAS être pris
    bruit = "\n".join(json.dumps({"param": i, "autre": "x" * 200}) for i in range(500))
    (root / "config_truc.jsonl").write_text(bruit, encoding="utf-8")

    rc = scl.main(["--root", str(root), "--tout", "--now-ms", str(NOW)])
    assert rc == 0
    local_index = json.loads((root / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
    sources = [s["shard"] for s in local_index["shards"]]
    assert any("export_bizarre_123" in s for s in sources), "le fichier au nom inconnu doit être certifié"
    assert not any("config_truc" in s for s in sources), "un jsonl non-données ne doit pas être pris"


def test_inventaire_safe_absent_est_failsoft(tmp_path):
    """Sans catalog/DATA_INDEX, l'inventaire SAFE est 'present: False' sans planter."""
    root = tmp_path
    data = root / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "vault_fills_poll.jsonl").write_text(json.dumps(_fill(tid=5)), encoding="utf-8")
    assert scl.main(["--root", str(root), "--now-ms", str(NOW)]) == 0
    coffre_index = json.loads((root / "runtime" / "coffre_certifie" / "COFFRE_INDEX.json").read_text(encoding="utf-8"))
    assert coffre_index["tiers"]["SAFE_CLOUD"]["present"] is False


def test_reset_affichage_vide_le_brut(tmp_path):
    root = tmp_path
    data = root / "runtime" / "data"
    data.mkdir(parents=True)
    src = data / "vault_fills_poll.jsonl"
    src.write_text(json.dumps(_fill(tid=9)), encoding="utf-8")
    assert scl.main(["--root", str(root), "--now-ms", str(NOW), "--reset-affichage"]) == 0
    assert src.read_text(encoding="utf-8") == ""  # remis à zéro après scellage vérifié
