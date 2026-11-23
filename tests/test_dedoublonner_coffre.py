"""Doublons du coffre (23/11/2026) : mesurés ligne par ligne, retirés de ce que lit le labo, sans rien supprimer.

Verrouille :
- la mesure désigne comme doublon la copie du lot le plus RÉCENT, jamais la première ;
- le remplaçant contient les lignes uniques À L'OCTET PRÈS ; l'original reste sur le disque, son entrée complète
  passe dans ``shards_remplaces`` ;
- un shard entièrement en double n'a pas de remplaçant ;
- une mesure périmée (le shard n'a plus le nombre de lignes mesuré) ne touche à rien ;
- après réparation, une nouvelle mesure ne trouve plus aucun doublon, et un scellage ultérieur garde ``shards_remplaces``.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
for _p in (RACINE / "src", RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import auditer_doublons_coffre as A  # noqa: E402
import dedoublonner_coffre as D  # noqa: E402

NOW = 1_795_000_000_000


def _ligne(i: int, mark: float = 2000.0) -> bytes:
    return (json.dumps({"coin": "ETH", "ts_ms": NOW - 100_000 + i, "mark": mark + i}) + "\n").encode()


def _shard(root: Path, lot: str, nom: str, lignes: list[bytes]) -> dict:
    rel = f"runtime/coffre_certifie/local/shards/asset_ctx/{lot}__{nom}.jsonl.gz"
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wb") as g:
        g.writelines(lignes)
    return {"batch_id": lot, "famille": "asset_ctx", "shard": rel, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "octets": p.stat().st_size, "deposes": len(lignes), "coins": ["ETH"], "jours": ["2026-11-18"],
            "ts_min_ms": NOW - 100_000, "ts_max_ms": NOW, "quality_status": "LOCAL_CERTIFIED", "tier": "LOCAL"}


def _coffre(root: Path, shards: list[dict]) -> None:
    (root / D.INDEX).write_text(json.dumps({"schema": "x", "tier": "LOCAL", "lots": [], "shards": shards}),
                                encoding="utf-8")


def _mesurer(root: Path) -> dict:
    r = A.mesurer(root, root / "_travail", ouvriers=1, log=lambda *_: None)
    (root / A.RAPPORT).write_text(json.dumps(r), encoding="utf-8")
    return r


def _lignes(root: Path, rel: str) -> list[bytes]:
    with gzip.open(root / rel, "rb") as g:
        return g.read().splitlines(keepends=True)


def test_le_doublon_est_la_copie_du_lot_recent_et_le_remplacant_garde_les_lignes_a_l_octet(tmp_path):
    ancien = _shard(tmp_path, "20261120T100000Z_aaaa", "asset_ctx_tape", [_ligne(i) for i in range(40)])
    recent_lignes = [_ligne(i) for i in range(30)] + [_ligne(i, mark=9.0) for i in range(100, 110)]
    recent = _shard(tmp_path, "20261123T100000Z_bbbb", "asset_ctx_tape", recent_lignes)
    _coffre(tmp_path, [recent, ancien])                      # l'ordre de l'index ne décide pas : le LOT décide
    r = _mesurer(tmp_path)
    assert r["total_doublons"] == 30
    assert [(s["shard"], s["lignes_en_double"]) for s in r["shards"]] == [(recent["shard"], [[0, 30]])]
    assert D.main(["--racine", str(tmp_path)]) == 0
    index = json.loads((tmp_path / D.INDEX).read_text(encoding="utf-8"))
    remplacant = next(s for s in index["shards"] if s.get("derive_de") == recent["shard"])
    assert _lignes(tmp_path, remplacant["shard"]) == recent_lignes[30:]          # à l'octet près
    assert remplacant["deposes"] == 10 and remplacant["lignes_retirees_en_double"] == 30
    assert remplacant["sha256"] == hashlib.sha256((tmp_path / remplacant["shard"]).read_bytes()).hexdigest()
    assert [s["shard"] for s in index["shards"]] == [remplacant["shard"], ancien["shard"]]   # place conservée
    assert index["shards_remplaces"][0]["shard"] == recent["shard"]
    assert index["shards_remplaces"][0]["remplace_par"] == remplacant["shard"]
    assert (tmp_path / recent["shard"]).exists()                                   # rien n'est supprimé
    assert sum(s["deposes"] for s in index["shards"]) == 50
    assert _mesurer(tmp_path)["total_doublons"] == 0                               # plus aucun doublon lu


def test_un_shard_entierement_en_double_sort_de_l_index_sans_remplacant(tmp_path):
    ancien = _shard(tmp_path, "20261120T100000Z_aaaa", "asset_ctx_tape", [_ligne(i) for i in range(20)])
    copie = _shard(tmp_path, "20261123T100000Z_bbbb", "asset_ctx_tape_1795", [_ligne(i) for i in range(20)])
    _coffre(tmp_path, [ancien, copie])
    _mesurer(tmp_path)
    assert D.main(["--racine", str(tmp_path)]) == 0
    index = json.loads((tmp_path / D.INDEX).read_text(encoding="utf-8"))
    assert [s["shard"] for s in index["shards"]] == [ancien["shard"]]
    assert index["shards_remplaces"][0]["remplace_par"] is None
    assert (tmp_path / copie["shard"]).exists()


def test_une_mesure_perimee_ne_touche_a_rien(tmp_path):
    ancien = _shard(tmp_path, "20261120T100000Z_aaaa", "asset_ctx_tape", [_ligne(i) for i in range(20)])
    recent = _shard(tmp_path, "20261123T100000Z_bbbb", "asset_ctx_tape", [_ligne(i) for i in range(25)])
    _coffre(tmp_path, [ancien, recent])
    _mesurer(tmp_path)
    avant = (tmp_path / D.INDEX).read_bytes()
    with gzip.open(tmp_path / recent["shard"], "ab") as g:                         # le shard a changé depuis
        g.write(_ligne(500))
    assert D.main(["--racine", str(tmp_path)]) == 0
    assert (tmp_path / D.INDEX).read_bytes() == avant
    bilan = json.loads((tmp_path / D.RAPPORT).read_text(encoding="utf-8"))[-1]
    assert [x["shard"] for x in bilan["ignores_mesure_perimee"]] == [recent["shard"]]


def test_meme_identite_mais_autre_contenu_n_est_jamais_retire(tmp_path):
    """23/11/2026 : 21 % des fills retirés par identité seule portaient des champs que la copie gardée n'avait pas
    (closedPnl, fee, pos_avant...). Seul un contenu identique à l'octet est un doublon."""
    ancien = _shard(tmp_path, "20261120T100000Z_aaaa", "asset_ctx_tape", [_ligne(i) for i in range(20)])
    enrichies = [(json.dumps({"coin": "ETH", "ts_ms": NOW - 100_000 + i, "mark": 2000.0 + i, "oi": 5.0}) + "\n").encode()
                 for i in range(20)]                                       # même identité (coin, ts), plus riche
    recent = _shard(tmp_path, "20261123T100000Z_bbbb", "asset_ctx_tape", enrichies + [_ligne(i) for i in range(5)])
    _coffre(tmp_path, [ancien, recent])
    r = _mesurer(tmp_path)
    assert r["total_doublons"] == 5                                         # les 5 copies exactes, rien d'autre
    assert r["bilan"]["asset_ctx"]["meme_identite_contenu_different"] == 20
    assert [s["lignes_en_double"] for s in r["shards"]] == [[[20, 25]]]


def test_annuler_un_lot_remet_les_originaux_et_garde_la_trace(tmp_path):
    ancien = _shard(tmp_path, "20261120T100000Z_aaaa", "asset_ctx_tape", [_ligne(i) for i in range(40)])
    recent = _shard(tmp_path, "20261123T100000Z_bbbb", "asset_ctx_tape",
                    [_ligne(i) for i in range(30)] + [_ligne(i, mark=9.0) for i in range(100, 110)])
    copie = _shard(tmp_path, "20261123T110000Z_cccc", "asset_ctx_tape_1795", [_ligne(i) for i in range(10)])
    _coffre(tmp_path, [ancien, recent, copie])
    avant = json.loads((tmp_path / D.INDEX).read_text(encoding="utf-8"))["shards"]
    _mesurer(tmp_path)
    assert D.main(["--racine", str(tmp_path)]) == 0
    lot = json.loads((tmp_path / D.RAPPORT).read_text(encoding="utf-8"))[-1]["lot"]
    assert D.main(["--racine", str(tmp_path), "--annuler", lot, "--motif", "test"]) == 0
    index = json.loads((tmp_path / D.INDEX).read_text(encoding="utf-8"))
    assert sorted(s["shard"] for s in index["shards"]) == sorted(s["shard"] for s in avant)
    assert {s["shard"]: s for s in index["shards"]}[recent["shard"]] == recent          # entrée d'origine intacte
    sortis = [s for s in index["shards_remplaces"] if s.get("annule_ms")]
    assert len(sortis) == 1 and sortis[0]["derive_de"] == recent["shard"]              # le remplaçant est gardé
    assert index["historique_dedoublonnage"][-1]["originaux_remis"] == 2


def test_une_entree_qui_a_change_entre_construction_et_echange_n_est_pas_remplacee(tmp_path):
    ancien = _shard(tmp_path, "20261120T100000Z_aaaa", "asset_ctx_tape", [_ligne(i) for i in range(20)])
    recent = _shard(tmp_path, "20261123T100000Z_bbbb", "asset_ctx_tape", [_ligne(i) for i in range(25)])
    index = {"shards": [ancien, dict(recent, sha256="autre")], "lots": []}
    bilan = {"ignores_entree_changee": [], "par_famille": {}, "lignes_retirees": 0, "lignes_gardees": 0,
             "remplaces": 0, "sans_remplacant": 0}
    construits = {recent["shard"]: {"entree": recent, "resultat": {"remplace_par": None, "retirees": 20,
                                                                    "gardees": 0}}}
    assert D.echanger(index, construits, "LOT", 1, bilan) == []
    assert [s["shard"] for s in index["shards"]] == [ancien["shard"], recent["shard"]]
    assert bilan["ignores_entree_changee"] == [recent["shard"]]


def test_un_scellage_ulterieur_garde_les_shards_remplaces(tmp_path):
    import sceller_coffre_local as S

    ancien = _shard(tmp_path, "20261120T100000Z_aaaa", "asset_ctx_tape", [_ligne(i) for i in range(20)])
    copie = _shard(tmp_path, "20261123T100000Z_bbbb", "asset_ctx_tape_1795", [_ligne(i) for i in range(20)])
    _coffre(tmp_path, [ancien, copie])
    _mesurer(tmp_path)
    assert D.main(["--racine", str(tmp_path)]) == 0
    vivant = tmp_path / "runtime" / "data" / "asset_ctx_tape.jsonl"
    vivant.parent.mkdir(parents=True, exist_ok=True)              # le verrou du certificateur y vit déjà
    vivant.write_bytes(b"".join(_ligne(i, mark=1.0) for i in range(1000, 1005)))
    assert S.main(["--root", str(tmp_path), "--now-ms", str(NOW), "--nom", vivant.name]) == 0
    index = json.loads((tmp_path / D.INDEX).read_text(encoding="utf-8"))
    assert [s["shard"] for s in index["shards_remplaces"]] == [copie["shard"]]
    assert copie["shard"] not in {s["shard"] for s in index["shards"]}
