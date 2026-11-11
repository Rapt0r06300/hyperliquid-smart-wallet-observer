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


# ───────────── reprise incrémentale, déplacement en archive, écriture atomique ─────────────

def _shards_fills(root):
    idx = json.loads((root / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
    out = []
    for shard in idx["shards"]:
        with gzip.open(root / shard["shard"], "rt", encoding="utf-8") as h:
            out.append([json.loads(l)["tid"] for l in h if l.strip()])
    return out


def test_ruban_qui_grossit_seule_la_suite_est_scellee_sans_doublon_entre_lots(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    tape = data / "vault_fills_poll.jsonl"
    tape.write_text("".join(json.dumps(_fill(tid=i)) + "\n" for i in (1, 2, 3)), encoding="utf-8")
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    with tape.open("a", encoding="utf-8") as h:                       # le collecteur continue d'écrire
        h.write("".join(json.dumps(_fill(tid=i)) + "\n" for i in (4, 5)))
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    lots = _shards_fills(tmp_path)
    assert sorted(lots, key=len) == [[4, 5], [1, 2, 3]]               # aucun fill re-scellé
    assert sorted(t for lot in lots for t in lot) == [1, 2, 3, 4, 5]  # aucun fill perdu


def test_ligne_en_cours_d_ecriture_est_relue_complete_au_passage_suivant(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    tape = data / "vault_fills_poll.jsonl"
    complet = json.dumps(_fill(tid=2))
    tape.write_text(json.dumps(_fill(tid=1)) + "\n" + complet[:40], encoding="utf-8")   # ligne coupée
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    tape.write_text(json.dumps(_fill(tid=1)) + "\n" + complet + "\n", encoding="utf-8")  # écriture terminée
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    assert sorted(t for lot in _shards_fills(tmp_path) for t in lot) == [1, 2]


def test_ruban_reecrit_est_rescelle_en_entier_jamais_saute(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    tape = data / "vault_fills_poll.jsonl"
    tape.write_text("".join(json.dumps(_fill(tid=i)) + "\n" for i in (1, 2)), encoding="utf-8")
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    # nouvelle session : même nom, contenu différent et plus long -> aucun préfixe reconnu
    tape.write_text("".join(json.dumps(_fill(tid=i)) + "\n" for i in (7, 8, 9)), encoding="utf-8")
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    assert sorted(t for lot in _shards_fills(tmp_path) for t in lot) == [1, 2, 7, 8, 9]


def test_ruban_deplace_en_archive_n_est_pas_rescelle(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    tape = data / "vault_fills_poll.jsonl"
    tape.write_text("".join(json.dumps(_fill(tid=i)) + "\n" for i in (1, 2)), encoding="utf-8")
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    archive = tmp_path / "runtime" / "archive" / "session-1"
    archive.mkdir(parents=True)
    tape.rename(archive / "vault_fills_poll.jsonl")
    assert scl.main(["--root", str(tmp_path), "--tout", "--now-ms", str(NOW)]) == 0
    assert _shards_fills(tmp_path) == [[1, 2]]                       # un seul lot, pas de doublon


def test_interruption_ne_laisse_aucun_shard_tronque(tmp_path, monkeypatch):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "vault_fills_poll.jsonl").write_text(
        "".join(json.dumps(_fill(tid=i)) + "\n" for i in range(1, 6)), encoding="utf-8")
    vrai = scl.certifier_record
    appels = {"n": 0}

    def coupe(*a, **k):
        appels["n"] += 1
        if appels["n"] == 3:
            raise KeyboardInterrupt()                                  # Ctrl+C en plein scellage
        return vrai(*a, **k)

    monkeypatch.setattr(scl, "certifier_record", coupe)
    try:
        scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)])
    except KeyboardInterrupt:
        pass
    shards = tmp_path / "runtime" / "coffre_certifie" / "local" / "shards"
    assert [p for p in shards.rglob("*") if p.is_file()] == []        # ni shard partiel ni .partial
    monkeypatch.setattr(scl, "certifier_record", vrai)
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0   # reprise complète
    assert _shards_fills(tmp_path) == [[1, 2, 3, 4, 5]]


# ───────────── instantanés de portefeuille de vault (cible de la réplication d'inventaire) ─────────────

def _snap(**kw):
    base = {"vault": "0x1E37A337ED460039D1B15BD3BC489DE789768D5E", "ts_ms": NOW - 1000, "nav_usd": 1000.5,
            "positions": [{"coin": "BTC", "szi": 2.5, "entryPx": 79404.5}, {"coin": "kPEPE", "szi": "-100", "entryPx": 0.003}],
            "source": "clearinghouseState", "read_only": True}
    base.update(kw)
    return base


def test_snapshot_vault_portefeuille_complet_est_certifie():
    from hl_observer.datasets.coffre_certifie import FAMILLE_SNAPSHOT, SCHEMA_SNAPSHOT_VAULT

    norm, decision, raison = certifier_record(_snap(), famille=FAMILLE_SNAPSHOT, source="SNAPSHOT", now_ms=NOW)
    assert decision == REPARE and raison == ""                    # szi "-100" (texte) normalisé en nombre
    assert norm["vault"] == "0x1e37a337ed460039d1b15bd3bc489de789768d5e"
    assert norm["schema_version"] == SCHEMA_SNAPSHOT_VAULT and norm["n_positions"] == 2
    assert [(p["coin"], p["szi"]) for p in norm["positions"]] == [("BTC", 2.5), ("kPEPE", -100.0)]  # casse native
    a_plat, decision, _ = certifier_record(_snap(positions=[], nav_usd=None), famille=FAMILLE_SNAPSHOT,
                                           source="SNAPSHOT", now_ms=NOW)
    assert decision == PASS and a_plat["positions"] == [] and a_plat["nav_usd"] is None   # NAV inconnue : jamais 0
    assert identite(norm, FAMILLE_SNAPSHOT) == ("vault_snapshot", norm["vault"], NOW - 1000)


def test_snapshot_vault_ampute_ou_incoherent_est_quarantaine_en_entier():
    from hl_observer.datasets.coffre_certifie import FAMILLE_SNAPSHOT

    cas = {
        "vault_absent_ou_invalide": _snap(vault="pas-une-adresse"),
        "timestamp_absent": _snap(ts_ms=None),
        "timestamp_futur": _snap(ts_ms=NOW + 60_000),
        "positions_absentes": _snap(positions=None),
        "position_invalide": _snap(positions=["BTC"]),
        "position_coin_absent": _snap(positions=[{"szi": 1.0}]),
        "position_szi_invalide": _snap(positions=[{"coin": "BTC", "szi": 1.0}, {"coin": "ETH", "szi": "nan"}]),
        "position_coin_duplique": _snap(positions=[{"coin": "BTC", "szi": 1.0}, {"coin": "BTC", "szi": 2.0}]),
        "nav_invalide": _snap(nav_usd="beaucoup"),
    }
    for raison_attendue, record in cas.items():
        norm, decision, raison = certifier_record(record, famille=FAMILLE_SNAPSHOT, source="SNAPSHOT", now_ms=NOW)
        assert (norm, decision, raison) == (None, QUARANTAINE, raison_attendue)


def test_snapshots_deja_rejetes_par_l_ancienne_regle_sont_recertifies(tmp_path):
    """Un fichier « déjà traité » avec une version plus ancienne du certificateur est repris."""
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    snaps = data / "vault_snapshots.jsonl"
    snaps.write_text("".join(json.dumps(_snap(ts_ms=NOW - 1000 * i)) + "\n" for i in (3, 2, 1)), encoding="utf-8")
    fills = data / "vault_fills_poll.jsonl"
    fills.write_text(json.dumps(_fill(tid=1)) + "\n", encoding="utf-8")
    coffre = tmp_path / "runtime" / "coffre_certifie"
    coffre.mkdir(parents=True)
    # état hérité : les deux fichiers marqués traités, sans version (= version 1)
    (coffre / "SOURCES_TRAITEES.json").write_text(json.dumps({
        str(snaps.relative_to(tmp_path)): {"sha256": scl._sha256_fichier(snaps), "batch": "ancien"},
        str(fills.relative_to(tmp_path)): {"sha256": scl._sha256_fichier(fills), "batch": "ancien"},
    }), encoding="utf-8")
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    index = json.loads((coffre / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
    assert [(s["famille"], s["deposes"]) for s in index["shards"]] == [("snapshot", 3)]   # fills non repris
    etat = json.loads((coffre / "SOURCES_TRAITEES.json").read_text(encoding="utf-8"))
    assert etat[str(snaps.relative_to(tmp_path))]["certif_version"] == 2
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0               # idempotent ensuite
    assert len(json.loads((coffre / "LOCAL_INDEX.json").read_text(encoding="utf-8"))["shards"]) == 1


def test_option_famille_ne_certifie_que_la_famille_demandee(tmp_path):
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "vault_snapshots.jsonl").write_text(json.dumps(_snap()) + "\n", encoding="utf-8")
    (data / "vault_fills_poll.jsonl").write_text(json.dumps(_fill(tid=1)) + "\n", encoding="utf-8")
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW), "--famille", "snapshot"]) == 0
    index = json.loads((tmp_path / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
    assert [s["famille"] for s in index["shards"]] == ["snapshot"]
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0               # le reste passe ensuite
    index = json.loads((tmp_path / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
    assert sorted(s["famille"] for s in index["shards"]) == ["fills_forward", "snapshot"]
