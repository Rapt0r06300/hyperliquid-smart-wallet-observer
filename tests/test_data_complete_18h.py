"""LOT18H-DATA-COMPLETE — e2e multi-format : toutes les sources -> corpus fusionné -> FAST_SCREEN ->
EXACT_REPLAY -> validation -> holdout -> forward paper -> PnL/ROI -> rapport, avec accounting sans plafond
silencieux, lecteurs (jsonl/csv/gz/sqlite/zip/parquet), dédup selon la source, logs->refus, lignée."""
from __future__ import annotations

import csv
import gzip
import json
import sqlite3
import sys
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import lecteurs_18h as LEC          # noqa: E402
import catalogue_archives_18h as CAT  # noqa: E402
import corpus_18h as COR            # noqa: E402
import logs_18h as LOGS             # noqa: E402
import lineage_18h as LIN           # noqa: E402
import pipeline_18h as PL           # noqa: E402


def _bbo(coin, ts, mid, snap=False):
    sp = mid * 0.0006
    return {"venue": "HL", "coin": coin, "ts_wall_ms": ts, "exchange_ts": ts - 5,
            "bid": mid - sp / 2, "ask": mid + sp / 2, "isSnapshot": snap, "reconnect_id": 1}


def _fixtures(root: Path):
    d = root / "runtime" / "data"
    d.mkdir(parents=True)
    # 1) JSONL BBO : 2 coins x 120 ticks + 5 doublons de snapshot (même payload) -> dédup.
    #    Dérive HAUSSIÈRE douce (~10 bps/tick) : une variante LONG à court horizon capte un edge net > coûts
    #    -> des survivants existent -> le forward paper produit des événements (fixtures, pas une promesse).
    lignes = []
    for i in range(120):
        for coin, base in (("BTC", 64000), ("ETH", 3200)):
            # dérive ~30 bps/tick : un LONG court horizon capte un edge net > coûts RÉELS (frais 9 bps A/R +
            # spread croisé aux deux jambes) -> des survivants existent -> le forward paper produit des events.
            lignes.append(_bbo(coin, 1_000_000 + i * 1000, base * (1 + i * 0.003)))
    dup = _bbo("BTC", 1_000_000, 64000 + (0 % 20) - 10, snap=True)
    lignes += [dup, dup, dup, dup, dup]                       # 5 doublons exacts
    (d / "bbo_tape.jsonl").write_text("\n".join(json.dumps(x) for x in lignes) + "\n")
    # 2) CSV trades
    with (d / "trades.csv").open("w", newline="") as f:
        w = csv.writer(f); w.writerow(["coin", "ts_ms", "px", "sz", "side", "tid"])
        for i in range(40):
            w.writerow(["BTC", 1_000_000 + i * 500, 64000 + i % 5, 0.1, "B", i])
    # 3) GZ BBO — SOL sur la MÊME plage temporelle (pour couvrir toutes les partitions), même dérive
    with gzip.open(d / "bbo2.jsonl.gz", "wt") as f:
        for i in range(120):
            f.write(json.dumps(_bbo("SOL", 1_000_000 + i * 1000, 150 * (1 + i * 0.001))) + "\n")
    # 4) SQLite RO (table bbo) — ADA sur la MÊME plage temporelle
    con = sqlite3.connect(d / "book.sqlite")
    con.execute("CREATE TABLE bbo(coin TEXT, ts_wall_ms INT, bid REAL, ask REAL)")
    for i in range(120):
        con.execute("INSERT INTO bbo VALUES (?,?,?,?)", ("ADA", 1_000_000 + i * 1000, 0.5, 0.5006))
    con.commit(); con.close()
    # 5) ZIP (inventorié, pending extraction)
    with zipfile.ZipFile(d / "arch.zip", "w") as z:
        z.writestr("inside.jsonl", json.dumps(_bbo("BTC", 9_000_000, 64000)) + "\n")
    # 6) JSONL tronqué (dernière ligne incomplète)
    (d / "trunc.jsonl").write_text('{"venue":"HL","coin":"BTC","ts_wall_ms":1,"bid":1,"ask":2}\n{"venue":"HL","coin":"BTC"')
    # 7) LOG avec refus + gap + reconnect
    with (d / "run.log.jsonl").open("w") as f:
        f.write(json.dumps({"kind": "REFUS", "motif": "MICRO_EDGE", "prix_entree": 100.0, "prix_sortie": 100.5, "sens": 1, "cout_entree_bps": 3}) + "\n")
        f.write(json.dumps({"kind": "REFUS", "motif": "STALE_SIGNAL", "prix_entree": 100.0, "prix_sortie": 99.7, "sens": 1, "cout_entree_bps": 3}) + "\n")
        f.write(json.dumps({"kind": "GAP", "gap": True, "recupere": True, "ts_ms": 5}) + "\n")
        f.write(json.dumps({"kind": "OPEN"}) + "\n")
    # 8) Parquet BIDON (aucun moteur pyarrow) -> doit être EXCLU avec raison, jamais VALID en aveugle
    (d / "data.parquet").write_bytes(b"PAR1\x00garbage-not-a-real-parquet")
    return d


def test_lecteurs_tous_formats(tmp_path):
    _fixtures(tmp_path)
    d = tmp_path / "runtime" / "data"
    assert sum(1 for _ in LEC.lire_jsonl(d / "bbo_tape.jsonl")) > 200          # jsonl stream
    assert sum(1 for _ in LEC.lire_csv(d / "trades.csv")) == 40                # csv
    assert sum(1 for _ in LEC.lire_gz(d / "bbo2.jsonl.gz")) == 120             # gz stream
    assert sum(1 for _ in LEC.lire_sqlite(d / "book.sqlite")) == 120          # sqlite RO
    assert len(LEC.inventorier_zip(d / "arch.zip")) == 1                       # zip inventaire
    # SHA256 intégral != prefix hash tronqué
    assert len(LEC.sha256_integral(d / "bbo_tape.jsonl")) == 64


def test_catalogue_complet_accounting_sans_plafond(tmp_path):
    _fixtures(tmp_path)
    rd = tmp_path / "rd"
    cat = CAT.cataloguer_complet(tmp_path, rd, dossiers=("runtime/data",))
    acc = cat["accounting"]
    assert acc["n_total_detected"] >= 8 and acc["n_parsed"] >= 4         # jsonl/csv/gz/sqlite parsés
    assert acc["events"] > 200
    # parquet bidon -> exclu/corrompu avec raison (jamais VALID en aveugle)
    formats = {s["format"]: s for s in cat["sources"]}
    assert formats["parquet"]["statut"] in ("EXCLUDED", "CORRUPTED")
    assert (rd / "results" / "data_source_accounting.csv").exists()
    assert (rd / "results" / "data_source_exclusions.csv").exists()


def test_corpus_dedup_selon_source(tmp_path):
    _fixtures(tmp_path)
    rd = tmp_path / "rd"
    cat = CAT.cataloguer_complet(tmp_path, rd, dossiers=("runtime/data",))
    cons = COR.construire(cat["sources"], root=tmp_path)
    assert cons["comptes"]["dedup"] >= 4         # les 5 snapshots doublons collapsés (dedup selon source)
    assert cons["comptes"]["utilises"] > 0 and cons["episodes"]        # corpus réellement construit
    assert "BBO" in cons["comptes"]["par_type"]


def test_e2e_donnees_completes_toutes_sources_vers_rapport(tmp_path, monkeypatch):
    import recherche_18h as ORCH
    _fixtures(tmp_path)
    monkeypatch.setattr(ORCH, "RACINE", tmp_path)
    rd = Path(ORCH.demarrer(tmp_path, exiger_flux=False)["rundir"])
    resume = PL.executer_pipeline_donnees_completes(tmp_path, rd, code_sha="e2e", dossiers=("runtime/data",))
    # les sources sont RÉELLEMENT consommées jusqu'au bout
    assert resume["accounting"]["n_parsed"] >= 4
    assert resume["corpus_comptes"]["utilises"] > 0 and resume["corpus_comptes"]["episodes"] > 0
    assert resume["n_fast_screen"] > 0 and resume["n_exact_replays"] > 0
    assert resume["n_forward_events"] > 0
    # logs -> refus rejoués (gate vs no-gate) + gaps
    assert resume["log_analyse"]["gate_vs_nogate"]["n_refuses_rejoues"] >= 2
    # CSV d'utilisation + lignée produits
    for f in ("data_source_accounting.csv", "trial_source_usage.csv", "archive_live_coverage.csv",
              "log_analysis.csv", "gap_recovery.csv", "data_lineage.jsonl"):
        assert (rd / "results" / f).exists(), f
    lignee = LIN.charger(rd)
    assert lignee and any(x.get("statut") == "AUDITABLE" for x in lignee)
    # rapport contient la section d'utilisation des données
    fin = ORCH.finaliser(tmp_path)
    md = (tmp_path / "RAPPORT-RECHERCHE-18H.md").read_text(encoding="utf-8")
    assert "UTILISATION DE TOUTES LES DONNÉES" in md and "Sources : détectées" in md
