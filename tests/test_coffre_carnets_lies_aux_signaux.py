"""Un carnet LIÉ À UN SIGNAL n'est pas le doublon du même carnet vu sans liaison.

Défaut réel mesuré le 22/11/2026 en vérifiant qu'une session avait bien atterri au coffre : le
certificateur identifiait un carnet par (coin, instant, meilleur achat, meilleure vente). Or le
moteur écrit DEUX fois certains carnets — une fois comme simple observation, une fois comme point
de contrôle d'un signal (`REFERENCE`, `ENTRY`, `EXIT_*`) avec `checkpoint_id` et `metaorder_id`.
Le second était jeté « doublon » dès que le premier (ou sa copie par la lane) était passé.

Sur la session du jour : 69 points de contrôle sur 177 perdus, dont 28 RÉFÉRENCES sur 28. Sur les
29 sessions archivées : 28 990 sur 127 346. Le labo ne garde QUE les lignes portant un
`checkpoint_id` : un épisode sans sa référence n'est pas mesurable.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.datasets import coffre_registre_fichiers as REG  # noqa: E402
from hl_observer.datasets.coffre_certifie import FAMILLE_BOOK_L2, identite  # noqa: E402
import sceller_coffre_local as scl  # noqa: E402

NOW = 1_800_000_000_000
TAPE = "copy_vault_l2_tape.jsonl"
LANE = "copy_vault_l2_lane.jsonl"


def _carnet(decalage_ms: int = 0, **champs) -> dict:
    base = {"coin": "XRP", "received_at_ms": NOW - 100 - decalage_ms, "exchange_ts_ms": NOW - 120 - decalage_ms,
            "bid": 1.2913, "ask": 1.2914,
            "bids5": [[1.2913, 1824.0], [1.2912, 10563.0]], "asks5": [[1.2914, 27409.0], [1.2915, 22559.0]]}
    base.update(champs)
    return base


def _lie(stage: str, ident: str, decalage_ms: int = 0, **champs) -> dict:
    return _carnet(decalage_ms, checkpoint_id=ident, checkpoint_stage=stage, metaorder_id="meta-1",
                   checkpoint_target_ms=NOW - 110 - decalage_ms, **champs)


def _ecrire(chemin: Path, lignes: list[dict]) -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text("".join(json.dumps(x) + "\n" for x in lignes), encoding="utf-8")


def _carnets_au_coffre(root: Path) -> list[dict]:
    lignes: list[dict] = []
    for shard in sorted((root / "runtime" / "coffre_certifie" / "local" / "shards" / "book_l2").glob("*.jsonl.gz")):
        with gzip.open(shard, "rt", encoding="utf-8") as h:
            lignes += [json.loads(x) for x in h if x.strip()]
    return lignes


def _lies(lignes: list[dict]) -> list[tuple[str, str]]:
    return sorted((x["checkpoint_stage"], x["checkpoint_id"]) for x in lignes if x.get("checkpoint_id"))


def test_un_carnet_lie_a_un_signal_n_est_pas_le_doublon_de_son_observation() -> None:
    nu, reference, entree = _carnet(), _lie("REFERENCE", "cp-1"), _lie("ENTRY", "cp-2")
    assert identite(nu, FAMILLE_BOOK_L2) != identite(reference, FAMILLE_BOOK_L2)
    assert identite(reference, FAMILLE_BOOK_L2) != identite(entree, FAMILLE_BOOK_L2)
    assert identite(reference, FAMILLE_BOOK_L2) == identite(_lie("REFERENCE", "cp-1"), FAMILLE_BOOK_L2)   # vrai doublon
    # deux SIGNAUX différents peuvent pointer le même carnet à la même étape : deux preuves, pas un doublon
    assert identite(_lie("ENTRY", "cp-2"), FAMILLE_BOOK_L2) != identite(_lie("ENTRY", "cp-3"), FAMILLE_BOOK_L2)
    # un carnet SANS liaison garde exactement son ancienne identité : rien de déjà déposé ne change de clé
    assert identite(nu, FAMILLE_BOOK_L2) == ("book", "XRP", NOW - 120, 1.2913, 1.2914)


def test_les_points_de_controle_atteignent_le_coffre_meme_si_la_lane_a_deja_ce_carnet(tmp_path) -> None:
    data = tmp_path / "runtime" / "data"
    _ecrire(data / LANE, [_carnet(connection_id="lane-1")])                      # traitée AVANT la tape (ordre des noms)
    _ecrire(data / TAPE, [_carnet(connection_id="moteur-1"),                     # même carnet, simple observation
                          _lie("REFERENCE", "cp-ref"),                           # le même, lié au signal
                          _lie("ENTRY", "cp-in"),
                          _lie("ENTRY", "cp-in"),                                # vrai doublon : une seule fois
                          _lie("EXIT_60000", "cp-out", decalage_ms=5)])
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    au_coffre = _carnets_au_coffre(tmp_path)
    assert _lies(au_coffre) == [("ENTRY", "cp-in"), ("EXIT_60000", "cp-out"), ("REFERENCE", "cp-ref")]
    assert sum(1 for x in au_coffre if not x.get("checkpoint_id")) == 1          # l'observation nue : une fois, comme avant


def test_le_rattrapage_des_archives_depose_les_liaisons_perdues_une_seule_fois(tmp_path, monkeypatch) -> None:
    """Session scellée avec l'ANCIENNE règle puis archivée : `--archives` rend ce qui a été jeté,
    sans redéposer ce qui y est déjà ni les observations nues."""
    data = tmp_path / "runtime" / "data"
    _ecrire(data / LANE, [_carnet(connection_id="lane-1")])
    _ecrire(data / TAPE, [_carnet(connection_id="moteur-1"), _lie("REFERENCE", "cp-ref"),
                          _lie("EXIT_60000", "cp-out", decalage_ms=5)])
    # 1) l'ancienne règle : identité aveugle à la liaison, fichier en version 1
    monkeypatch.setattr(scl, "identite", lambda r, f: ("book", r.get("coin"), r.get("exchange_ts_ms"), r.get("bid"), r.get("ask"))
                        if f == FAMILLE_BOOK_L2 else identite(r, f))
    monkeypatch.delitem(REG.VERSIONS_CERTIFICATEUR, TAPE, raising=False)
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    assert _lies(_carnets_au_coffre(tmp_path)) == [("EXIT_60000", "cp-out")]     # la référence a été jetée : c'est le défaut
    archive = tmp_path / "runtime" / "archive" / "session_1"
    archive.mkdir(parents=True)
    for nom in (LANE, TAPE):
        (data / nom).rename(archive / nom)
    # 2) la règle corrigée, puis le rattrapage
    monkeypatch.undo()
    assert REG.version_certificateur(TAPE) >= 2
    assert scl.main(["--root", str(tmp_path), "--archives", "--now-ms", str(NOW)]) == 0
    au_coffre = _carnets_au_coffre(tmp_path)
    assert _lies(au_coffre) == [("EXIT_60000", "cp-out"), ("REFERENCE", "cp-ref")]    # rendue, et la sortie pas doublée
    assert sum(1 for x in au_coffre if not x.get("checkpoint_id")) == 1               # aucune observation nue redéposée
    assert scl.main(["--root", str(tmp_path), "--archives", "--now-ms", str(NOW)]) == 0   # idempotent
    assert _lies(_carnets_au_coffre(tmp_path)) == [("EXIT_60000", "cp-out"), ("REFERENCE", "cp-ref")]


def test_au_rattrapage_seules_les_lignes_liees_sont_nouvelles() -> None:
    assert REG.nouvellement_accepte(TAPE, _lie("REFERENCE", "cp-1")) is True
    assert REG.nouvellement_accepte(TAPE, _carnet()) is False
    assert REG.nouvellement_accepte("runtime/archive/s/" + TAPE + ".gz", _carnet()) is False
