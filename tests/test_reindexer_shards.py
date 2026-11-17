"""RÉINDEXER SANS JAMAIS TOUCHER LA DONNÉE — ni fabriquer une date qui n'existe pas.

D'OÙ VIENT CET OUTIL. `_ts_primaire` du scelleur ne connaissait pas les horloges de `position`
(`received_at_ms`) ni de `trades_marche` (`exchange_ts_ms`). Leurs 363 shards ont été indexés
`jours = ["0000-00-00"]`, sans bornes de temps : **aucune étude ne peut les découper par jour**,
alors que la seule hypothèse non réfutée (opérateurs lents, réplication d'inventaire) exige des
transitions de position sur des jours indépendants.

Le correctif du 16/11 répare les lots suivants ; cet outil répare les précédents. Ces tests
verrouillent ses quatre refus : jamais toucher un shard, jamais écrire sans SHA vérifié, jamais
fabriquer une date, jamais écrire pendant une certification.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
for chemin in (str(RACINE / "src"), str(RACINE / "tools")):
    if chemin not in sys.path:
        sys.path.insert(0, chemin)

import reindexer_shards as R                       # noqa: E402
from hl_observer.ops import verrou_pid as VP       # noqa: E402

T0 = 1_794_844_365_779          # 16/11/2026 UTC


def _coffre(tmp_path: Path, lignes: list[dict], *, famille="position", sha_juste=True):
    """Un mini-coffre : un shard gzip + un index qui le décrit, sans bornes de temps."""
    rel = f"runtime/coffre_certifie/local/shards/{famille}/lot__{famille}.jsonl.gz"
    chemin = tmp_path / rel
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(chemin, "wt", encoding="utf-8") as fh:
        for l in lignes:
            fh.write(json.dumps(l) + "\n")
    sha = hashlib.sha256(chemin.read_bytes()).hexdigest() if sha_juste else "0" * 64
    index = tmp_path / R.INDEX
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(json.dumps({"tier": "LOCAL", "shards": [{
        "famille": famille, "shard": rel, "sha256": sha, "octets": chemin.stat().st_size,
        "deposes": len(lignes), "coins": sorted({str(l.get("coin")) for l in lignes if l.get("coin")}),
        "jours": [R.SENTINELLE],
    }]}), encoding="utf-8")
    return chemin, index


def _position(ts, coin="BTC"):
    return {"vault": "0xabc", "coin": coin, "szi": 1.5, "received_at_ms": ts,
            "source": "CLEARINGHOUSE_WS"}


# ─────────────── qui a besoin d'être réindexé ───────────────
def test_un_shard_avec_bornes_ET_jours_vrais_n_est_PAS_candidat():
    assert R.a_reindexer({"ts_min_ms": 1, "ts_max_ms": 2, "jours": ["2026-11-16"]}) is False


def test_la_sentinelle_et_les_bornes_absentes_font_un_candidat():
    assert R.a_reindexer({"jours": [R.SENTINELLE]}) is True
    assert R.a_reindexer({"ts_min_ms": 1, "ts_max_ms": 2, "jours": [R.SENTINELLE]}) is True
    assert R.a_reindexer({"jours": ["2026-11-16"]}) is True, "sans bornes de temps, pas decoupable"
    assert R.a_reindexer({"ts_min_ms": 1, "ts_max_ms": 2}) is True, "sans jours non plus"


# ─────────────── la mesure : vraie, ou rien ───────────────
def test_les_bornes_sont_RELUES_dans_le_shard(tmp_path):
    _coffre(tmp_path, [_position(T0), _position(T0 + 86_400_000), _position(T0 - 3_600_000)])
    rapport = R.reindexer(tmp_path, appliquer=False)
    assert rapport["statuts"] == {"MESURE": 1}
    ex = rapport["exemples"][0]
    assert ex["ts_min_ms"] == T0 - 3_600_000 and ex["ts_max_ms"] == T0 + 86_400_000
    assert ex["jours"] == ["2026-11-16", "2026-11-17"], ex["jours"]


def test_un_SHA_divergent_laisse_le_shard_INTACT_et_le_signale(tmp_path):
    _coffre(tmp_path, [_position(T0)], sha_juste=False)
    rapport = R.reindexer(tmp_path, appliquer=True)
    assert rapport["statuts"] == {"SHA_DIVERGENT": 1}
    assert rapport["index_reecrit"] is False, (
        "on ne reindexe pas une donnee dont l'integrite n'est pas prouvee")


def test_aucune_ligne_datable_GARDE_la_sentinelle(tmp_path):
    """On ne fabrique pas une date : un shard sans horloge reconnue reste `0000-00-00`."""
    _coffre(tmp_path, [{"vault": "0xabc", "coin": "BTC", "szi": 1.0}])
    rapport = R.reindexer(tmp_path, appliquer=True)
    assert rapport["statuts"] == {"AUCUNE_HORLOGE": 1}
    index = json.loads((tmp_path / R.INDEX).read_text(encoding="utf-8"))
    assert index["shards"][0]["jours"] == [R.SENTINELLE]


def test_un_shard_absent_est_signale_sans_planter(tmp_path):
    chemin, _ = _coffre(tmp_path, [_position(T0)])
    chemin.unlink()
    assert R.reindexer(tmp_path, appliquer=False)["statuts"] == {"ABSENT": 1}


# ─────────────── l'écriture : sauvegardée, atomique, et jamais sur la donnée ───────────────
def test_appliquer_ecrit_l_index_SANS_toucher_le_shard(tmp_path):
    chemin, index = _coffre(tmp_path, [_position(T0)])
    avant = chemin.read_bytes()
    rapport = R.reindexer(tmp_path, appliquer=True)
    assert rapport["index_reecrit"] is True and rapport["sauvegarde"]
    assert chemin.read_bytes() == avant, "le shard ne doit JAMAIS etre modifie"
    shard = json.loads(index.read_text(encoding="utf-8"))["shards"][0]
    assert shard["ts_min_ms"] == T0 and shard["jours"] == ["2026-11-16"]
    assert type(shard.get("reindexe_ms")) is int, "la reparation doit etre tracee"
    assert Path(rapport["sauvegarde"]).is_file(), "l'index d'origine doit etre sauvegarde"


def test_la_simulation_n_ecrit_RIEN(tmp_path):
    _chemin, index = _coffre(tmp_path, [_position(T0)])
    avant = index.read_bytes()
    rapport = R.reindexer(tmp_path, appliquer=False)
    assert rapport["statuts"] == {"MESURE": 1} and rapport["index_reecrit"] is False
    assert index.read_bytes() == avant


def test_le_verrou_du_SCELLEUR_interdit_de_reecrire_pendant_une_certification(tmp_path):
    """Réécrire l'index pendant que le scelleur le met à jour le corromprait."""
    _coffre(tmp_path, [_position(T0)])
    verrou = tmp_path / R.VERROU
    pris, _ = VP.prendre(verrou, quoi="un scellage")
    assert pris
    code = R.main(["--root", str(tmp_path), "--appliquer"])
    assert code == 3, "un reindexage pendant une certification doit etre REFUSE"
    index = json.loads((tmp_path / R.INDEX).read_text(encoding="utf-8"))
    assert index["shards"][0]["jours"] == [R.SENTINELLE], "rien ne doit avoir ete ecrit"
    VP.rendre(verrou)


def test_le_filtre_par_famille_limite_le_chantier(tmp_path):
    _coffre(tmp_path, [_position(T0)], famille="position")
    assert R.reindexer(tmp_path, appliquer=False, familles={"trades_marche"})["candidats"] == 0
    assert R.reindexer(tmp_path, appliquer=False, familles={"position"})["candidats"] == 1


def test_les_horloges_viennent_du_SCELLEUR_et_ne_sont_pas_recopiees():
    """Si les deux tables divergeaient, l'index décrirait un temps que le scelleur ignore."""
    ts_primaire, jour_utc = R._horloges()
    assert ts_primaire({"received_at_ms": T0}, "position") == T0
    assert ts_primaire({"exchange_ts_ms": T0}, "trades_marche") == T0
    assert jour_utc(T0) == "2026-11-16"
