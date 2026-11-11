"""Vérification par référence du magasin de ticks natifs : rien n'échappe, rien n'est recopié."""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "tools"))

import verifier_store_ticks as V  # noqa: E402


def _shard(root: Path, source: str, canal: str, instrument: str, nom: str, *, lignes: int = 3, manifeste: bool = True):
    dossier = root / V.STORE / source / canal / instrument
    (dossier / "shards").mkdir(parents=True, exist_ok=True)
    chemin = dossier / "shards" / nom
    with gzip.open(chemin, "wt", encoding="utf-8") as h:
        for i in range(lignes):
            h.write(json.dumps({"instrument": instrument, "i": i, "nom": nom}) + "\n")
    if manifeste:
        chemin.with_name(nom + ".manifest.json").write_text(json.dumps({
            "bytes": chemin.stat().st_size, "event_count": lignes, "file_name": nom,
            "first_received_ts_ms": 1000, "last_received_ts_ms": 2000,
            "sha256": hashlib.sha256(chemin.read_bytes()).hexdigest(), "schema_version": "alina.tick_shard_manifest.v2",
        }), encoding="utf-8")
    _toucher_manifeste(dossier)
    return chemin


def _toucher_manifeste(dossier: Path) -> None:
    """Le collecteur réécrit ticks.manifest.json à chaque rotation : c'est le signal « du nouveau »."""
    shards = sorted(p.name for p in (dossier / "shards").glob("*.jsonl.gz"))
    (dossier / "ticks.manifest.json").write_text(json.dumps({"immutable_shards": shards}), encoding="utf-8")


def test_verifie_reference_et_ne_recopie_rien(tmp_path):
    _shard(tmp_path, "hyperliquid_mainnet_readonly", "bbo", "BTC", "ticks.1-2.3.jsonl.gz", lignes=5)
    _shard(tmp_path, "hyperliquid_mainnet_readonly", "bbo", "kPEPE", "ticks.1-2.4.jsonl.gz")
    _shard(tmp_path, "binance_usdm_public", "l2Book", "BTCUSDT", "ticks.1-2.5.jsonl.gz")
    actif = tmp_path / V.STORE / "binance_usdm_public" / "l2Book" / "BTCUSDT" / "ticks.current.jsonl"
    actif.write_text('{"en":"cours"}\n', encoding="utf-8")
    avant = sorted(p.relative_to(tmp_path).as_posix() for p in (tmp_path / V.STORE).rglob("*") if p.is_file())
    resume = V.verifier_store(tmp_path)
    assert resume["complet"] and resume["shards_verifies"] == 3 and resume["anomalies"] == 0
    par_flux = {(f["source"], f["canal"]): f for f in resume["par_flux"]}
    assert par_flux[("hyperliquid_mainnet_readonly", "bbo")]["evenements"] == 8
    assert par_flux[("binance_usdm_public", "l2Book")]["rubans_en_cours"] == 1      # recensé, pas encore immuable
    assert resume["mode"] == "VERIFIE_ET_REFERENCE_EN_PLACE"
    # le magasin n'est ni modifié ni recopié : mêmes fichiers, aucun shard dans le coffre
    assert sorted(p.relative_to(tmp_path).as_posix() for p in (tmp_path / V.STORE).rglob("*") if p.is_file()) == avant
    assert not (tmp_path / "runtime" / "coffre_certifie" / "local").exists()
    assert json.loads((tmp_path / V.INDEX).read_text(encoding="utf-8"))["shards_verifies"] == 3


def test_shard_altere_tronque_ou_sans_manifeste_est_signale(tmp_path):
    bon = _shard(tmp_path, "hyperliquid_mainnet_readonly", "trades", "ETH", "ticks.1-2.1.jsonl.gz")
    altere = _shard(tmp_path, "hyperliquid_mainnet_readonly", "trades", "ETH", "ticks.1-2.2.jsonl.gz")
    tronque = _shard(tmp_path, "hyperliquid_mainnet_readonly", "trades", "ETH", "ticks.1-2.3.jsonl.gz")
    _shard(tmp_path, "hyperliquid_mainnet_readonly", "trades", "ETH", "ticks.1-2.4.jsonl.gz", manifeste=False)
    octets = bytearray(altere.read_bytes())
    octets[-1] ^= 0xFF                                              # même taille, contenu différent
    altere.write_bytes(bytes(octets))
    tronque.write_bytes(tronque.read_bytes()[:-4])                  # fichier incomplet
    resume = V.verifier_store(tmp_path)
    statuts = {Path(a["shard"]).name: a["statut"] for a in resume["liste_anomalies"]}
    assert statuts == {
        "ticks.1-2.2.jsonl.gz": V.SHA_DIFFERENT, "ticks.1-2.3.jsonl.gz": V.TAILLE_DIFFERENTE,
        "ticks.1-2.4.jsonl.gz": V.MANIFESTE_ABSENT,
    }
    assert resume["anomalies"] == 3 and V.verifier_shard(bon)[0] == V.OK
    assert V.main(["--root", str(tmp_path)]) == 4                   # une anomalie n'est jamais silencieuse


def test_incremental_et_reprise_apres_budget_epuise(tmp_path):
    for i in range(6):
        _shard(tmp_path, "hyperliquid_mainnet_readonly", "bbo", f"C{i}", f"ticks.1-2.{i}.jsonl.gz")
    tic = iter(range(0, 10_000, 10))                                # chaque lecture d'horloge avance de 10 s
    partiel = V.verifier_store(tmp_path, budget_s=25.0, horloge=lambda: next(tic))
    assert not partiel["complet"] and 0 < partiel["shards_verifies"] < 6 and partiel["dossiers_restants"] > 0
    complet = V.verifier_store(tmp_path, budget_s=1e9)
    assert complet["complet"] and complet["shards_verifies"] == 6
    assert complet["verifies_ce_passage"] == 6 - partiel["shards_verifies"]   # reprise, pas de recommencement
    encore = V.verifier_store(tmp_path, budget_s=1e9)
    assert encore["verifies_ce_passage"] == 0                       # rien de nouveau : rien n'est relu
    nouveau = _shard(tmp_path, "hyperliquid_mainnet_readonly", "bbo", "C0", "ticks.3-4.9.jsonl.gz")
    apres = V.verifier_store(tmp_path, budget_s=1e9)
    assert apres["verifies_ce_passage"] == 1 and apres["shards_verifies"] == 7
    # un shard modifié APRÈS sa vérification est relu et signalé
    octets = bytearray(nouveau.read_bytes())
    octets[-1] ^= 0xFF
    nouveau.write_bytes(bytes(octets))
    _toucher_manifeste(nouveau.parent.parent)
    assert V.verifier_store(tmp_path, budget_s=1e9)["anomalies"] == 1


def test_sans_magasin_ni_erreur_ni_fichier_cree(tmp_path):
    assert V.verifier_store(tmp_path) == {"present": False}
    assert not (tmp_path / "runtime").exists() and V.main(["--root", str(tmp_path)]) == 0


def test_le_certificateur_verifie_le_magasin_de_ticks_a_chaque_passage(tmp_path):
    """Déclenché à la fermeture des collecteurs : le magasin natif n'échappe plus au certificateur."""
    import sceller_coffre_local as scl

    now = 1_800_000_000_000
    _shard(tmp_path, "hyperliquid_mainnet_readonly", "bbo", "BTC", "ticks.1-2.3.jsonl.gz")
    data = tmp_path / "runtime" / "data"
    fill = {"coin": "MINA", "px": "0.05", "sz": "3.0", "side": "B", "time": now - 1000, "tid": 1,
            "vault": "0x07fd993f0fa3a185f7207adccd29f7a87404689d", "source": "LIVE_POLL",
            "isSnapshot": False, "observed_at_ms": now - 500}
    (data / "vault_fills_poll.jsonl").write_text(json.dumps(fill) + "\n", encoding="utf-8")
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(now)]) == 0
    coffre = tmp_path / "runtime" / "coffre_certifie"
    tier = json.loads((coffre / "COFFRE_INDEX.json").read_text(encoding="utf-8"))["tiers"]["MARKET_TICKS_STORE"]
    assert tier["shards_verifies"] == 1 and tier["anomalies"] == 0 and tier["complet"] is True
    # second passage sans nouveau ruban : le magasin est quand même contrôlé (nouveau shard altéré)
    mauvais = _shard(tmp_path, "hyperliquid_mainnet_readonly", "bbo", "BTC", "ticks.3-4.5.jsonl.gz")
    mauvais.write_bytes(mauvais.read_bytes()[:-3])
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(now)]) == 0
    index = json.loads((tmp_path / V.INDEX).read_text(encoding="utf-8"))
    assert index["shards_verifies"] == 2 and index["anomalies"] == 1
