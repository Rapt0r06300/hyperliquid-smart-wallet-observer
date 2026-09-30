"""RECABLAGE — `market_truth` n'est plus un orphelin testé-seulement.

Avant ce lot, `src/hl_observer/market_truth/` (1145 lignes : canonicalisation, replay
exécutable, chaîne de vérité, validation) avait **zéro appelant de production** : la
maladie connue du projet (« mention ≠ porte »). Ces tests prouvent deux choses :

1. la sonde `market_truth_replay` fait réellement tourner la chaîne sur des ticks
   durables écrits par le **vrai** `TickDatasetWriter` ;
2. elle est réellement **enregistrée** comme étape du lanceur d'analyse officiel
   `ANALYSER_BACKTESTS_REPLAYS.cmd` (via `historical_analysis_suite.build_stage_plan`).

Paper-only, read-only, 0 réseau.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection.tick_dataset import TickDatasetWriter, TickEnvelope  # noqa: E402
from hl_observer.ops import market_truth_replay as MTR  # noqa: E402
from hl_observer.ops.historical_analysis_suite import build_stage_plan  # noqa: E402


def _carnet(px: float) -> dict:
    """Payload l2Book au format Hyperliquid réel (levels[0]=bids, levels[1]=asks)."""
    return {
        "channel": "l2Book",
        "data": {
            "levels": [
                [{"px": "%.2f" % px, "sz": "5"}, {"px": "%.2f" % (px - 1), "sz": "9"}],
                [{"px": "%.2f" % (px + 1), "sz": "5"}, {"px": "%.2f" % (px + 2), "sz": "9"}],
            ]
        },
    }


def _ecrire_ticks(dossier: Path, *, n=40, coin="BTC", gate_ready=True, t0=1_700_000_000_000):
    """Écrit de VRAIS enregistrements durables via le writer de production."""
    writer = TickDatasetWriter(dossier)
    enveloppes = []
    for i in range(n):
        ts = t0 + i * 100
        enveloppes.append(
            TickEnvelope(
                source_id="test_l2",
                channel="l2Book",
                instrument=coin,
                event_kind="SNAPSHOT",
                raw_payload=_carnet(64_000 + i),
                received_ts_ms=ts,
                exchange_ts_ms=ts - 5,
                provenance={"access": "read_only", "venue": "hyperliquid"},
                parsed_summary={"feed_quality_score": 95.0, "data_gate_ready": bool(gate_ready)},
                written_ts_ms=ts,
            )
        )
    writer.append_batch(enveloppes)
    return writer


def _config(**kw):
    base = dict(every=5, max_intents=40, horizon_ms=5_000)
    base.update(kw)
    return MTR.ProbeConfig(**base)


# ══════════════════ deny-by-default : rien d'inventé ══════════════════
def test_sans_donnee_le_statut_est_no_data_et_rien_n_est_fabrique(tmp_path):
    r = MTR.run_probe(tmp_path / "vide", _config())
    assert r["statut"] == "NO_DATA"
    assert "raison" in r and r["inventaire"]["ticks_retenus"] == 0
    # aucune métrique fabriquée : pas de bloc de coûts, pas de taux à 0 %
    assert "couts_bps_medians" not in r
    assert "intentions" not in r


def test_qualite_insuffisante_ne_produit_aucun_prix_invente(tmp_path):
    d = tmp_path / "ticks"
    _ecrire_ticks(d, gate_ready=False)
    r = MTR.run_probe(d, _config())
    assert r["statut"] == "AUCUNE_INTENTION_EXECUTABLE"
    assert r["intentions"]["executables"] == 0
    # les médianes restent None — jamais 0.0 présenté comme une mesure
    assert r["couts_bps_medians"]["spread"] is None
    assert r["fill_ratio_median"] is None
    assert "DATA_QUALITY_GATE_NOT_READY" in json.dumps(r["intentions"]["raisons"])


def test_schema_de_tick_inconnu_est_compte_pas_ignore_en_silence(tmp_path):
    d = tmp_path / "ticks"
    d.mkdir()
    (d / "faux.jsonl").write_text(
        json.dumps({"schema_version": "autre.v9", "instrument": "BTC"}) + "\n", encoding="utf-8"
    )
    r = MTR.run_probe(d, _config())
    assert r["statut"] == "NO_DATA"
    assert r["inventaire"]["rejets_schema"] == 1


# ══════════════════ la chaîne tourne vraiment ══════════════════
def test_ticks_reels_produisent_des_fills_executables_et_des_couts(tmp_path):
    d = tmp_path / "ticks"
    _ecrire_ticks(d)
    r = MTR.run_probe(d, _config())
    assert r["statut"] == "OK"
    assert r["intentions"]["executables"] > 0
    assert 0.0 < r["intentions"]["taux_executable"] <= 1.0
    # le spread mesuré vient du carnet réel (bid 64000+i, ask +1) : strictement positif
    assert r["couts_bps_medians"]["spread"] > 0
    assert r["fill_ratio_median"] is not None
    assert r["par_instrument"]["BTC"]["executables"] > 0


def test_les_deux_sens_sont_testes_donc_aucun_biais_directionnel(tmp_path):
    d = tmp_path / "ticks"
    _ecrire_ticks(d)
    ticks, _ = MTR.load_ticks(d)
    intents = MTR.build_intents(ticks, _config())
    sens = {i.position_side for i, _ in intents}
    assert sens == {"LONG", "SHORT"}
    assert len(intents) % 2 == 0


def test_la_fenetre_de_replay_ne_regarde_jamais_le_passe(tmp_path):
    d = tmp_path / "ticks"
    _ecrire_ticks(d)
    ticks, _ = MTR.load_ticks(d)
    intents = MTR.build_intents(ticks, _config(every=10))
    intent, index = intents[-1]
    fenetre = MTR._fenetre(ticks, index, intent.signal_observable_at_ms + 5_000)
    assert fenetre, "la fenêtre doit contenir au moins l'ancre"
    # aucun événement antérieur au signal ne peut entrer dans la fenêtre
    assert min(int(t["_observable_at_ms"]) for t in fenetre) >= intent.signal_observable_at_ms


def test_l_horizon_borne_reellement_la_fenetre(tmp_path):
    d = tmp_path / "ticks"
    _ecrire_ticks(d, n=200)
    ticks, _ = MTR.load_ticks(d)
    intents = MTR.build_intents(ticks, _config())
    intent, index = intents[0]
    courte = MTR._fenetre(ticks, index, intent.signal_observable_at_ms + 300)
    longue = MTR._fenetre(ticks, index, intent.signal_observable_at_ms + 10_000)
    assert len(courte) < len(longue)


def test_les_shards_gzip_sont_relus(tmp_path):
    d = tmp_path / "ticks"
    _ecrire_ticks(d, n=10)
    shards = d / "shards"
    shards.mkdir(exist_ok=True)
    import gzip

    source = next(d.glob("*.current.jsonl"))
    lignes = source.read_text(encoding="utf-8")
    with gzip.open(shards / "vieux.jsonl.gz", "wt", encoding="utf-8") as fh:
        fh.write(lignes)
    _, inv = MTR.load_ticks(d)
    assert inv["ticks_retenus"] == 20  # courant + shard archivé


def test_rapport_ecrit_sur_disque_et_cli_rend_zero(tmp_path):
    d = tmp_path / "ticks"
    _ecrire_ticks(d)
    out = tmp_path / "rapports"
    code = MTR.main(
        ["--root", str(tmp_path), "--ticks-dir", str(d), "--output-dir", str(out), "--every", "5"]
    )
    assert code == 0
    rapport = json.loads((out / "market_truth_replay.json").read_text(encoding="utf-8"))
    assert rapport["schema_version"] == MTR.SCHEMA_VERSION
    assert rapport["paper_only"] is True and rapport["real_execution"] is False
    # le rapport dit explicitement ce qu'il ne mesure pas
    assert "aucun edge" in rapport["ne_mesure_pas"]


# ══════════════════ le câblage : l'étape existe vraiment ══════════════════
def test_l_etape_est_enregistree_dans_le_lanceur_analyse(tmp_path):
    plan = build_stage_plan(tmp_path, tmp_path / "out")
    etapes = {s.key: s for s in plan}
    assert "market_truth_replay" in etapes, "market_truth resterait un orphelin"
    stage = etapes["market_truth_replay"]
    assert "hl_observer.ops.market_truth_replay" in stage.command
    # deny-by-default : sans dataset de ticks, l'étape est SKIPPED, jamais en échec
    assert any("market_ticks" in str(p) for p in stage.required_paths)


def test_l_etape_reste_dans_les_modes_full_et_deep(tmp_path):
    for kwargs in ({}, {"full": True}, {"full": True, "deep": True}):
        plan = build_stage_plan(tmp_path, tmp_path / "out", **kwargs)
        assert any(s.key == "market_truth_replay" for s in plan)


def test_securite_aucun_appel_reel(tmp_path):
    src = (RACINE / "src" / "hl_observer" / "ops" / "market_truth_replay.py").read_text(
        encoding="utf-8"
    )
    for interdit in (
        '"/exchange"',
        "'/exchange'",
        "requests.get",
        "requests.post",
        "import websocket",
        "websockets.connect",
        "eth_account",
        "Account.from_key",
        "private_key",
    ):
        assert interdit not in src, "appel interdit dans market_truth_replay: %s" % interdit
