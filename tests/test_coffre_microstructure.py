"""Microstructure Hyperliquid (micro_bbo / micro_l2book / micro_trades) dans le coffre LOCAL.

Ces flux denses étaient écrits dans ``runtime/research_lab/data``, un dossier que le
certificateur ne visitait jamais. Ils portent séquence et somme de contrôle par ligne : la
certification les revérifie, et la rotation ``.jsonl -> _<horodatage>.jsonl.gz`` ne crée ni
perte ni doublon.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.datasets import coffre_certifie as C  # noqa: E402
import sceller_coffre_local as scl  # noqa: E402

NOW = 1_800_000_000_000


def _signer(corps: dict) -> dict:
    """Même somme de contrôle que ``collecter_lab_microstructure.ecrire_micro``."""
    corps = {k: v for k, v in corps.items() if k != "checksum"}
    corps["checksum"] = hashlib.sha256(json.dumps(corps, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    return corps


def _bbo(i: int = 0, **kw) -> dict:
    base = {"flux": "bbo", "coin": "BTC", "ts_ex": NOW - 5_000 + i, "bid": 73752.0, "bid_sz": 14.2, "bid_n": 33,
            "ask": 73753.0, "ask_sz": 1.1, "ask_n": 4, "ts_wall_ms": NOW - 4_200 + i, "ts_mono_ns": 1, "seq": i + 1,
            "gap": None, "schema_version": 2, "source": "hl_ws_public", "read_only": True, "real_execution": False}
    base.update(kw)
    return _signer(base)


def _l2(**kw) -> dict:
    base = {"flux": "l2book", "coin": "AAVE", "ts_ex": NOW - 5_000, "bids": [[123.62, 3.24, 1], [123.61, 0.94, 1]],
            "asks": [[123.63, 3.33, 2], [123.64, 2.72, 2]], "ts_wall_ms": NOW - 4_000, "ts_mono_ns": 1, "seq": 1,
            "gap": None, "schema_version": 2, "source": "hl_ws_public", "read_only": True, "real_execution": False}
    base.update(kw)
    return _signer(base)


def _trade(**kw) -> dict:
    base = {"flux": "trade", "coin": "ETH", "px": 2063.2, "sz": 0.006, "side": -1, "ts_ex": NOW - 5_000, "tid": 86,
            "ts_wall_ms": NOW - 4_000, "ts_mono_ns": 1, "seq": 1, "gap": None, "schema_version": 2,
            "source": "hl_ws_public", "read_only": True, "real_execution": False}
    base.update(kw)
    return _signer(base)


def _certifier(record, famille):
    return C.certifier_record(record, famille=famille, source="HL_WS_PUBLIC", now_ms=NOW)


def test_les_trois_flux_de_microstructure_sont_certifies_avec_horloges_communes():
    norm, decision, _ = _certifier(_bbo(), C.FAMILLE_MICRO_BBO)
    assert decision == C.PASS and (norm["exchange_ts_ms"], norm["received_at_ms"]) == (NOW - 5_000, NOW - 4_200)
    norm, decision, _ = _certifier(_l2(), C.FAMILLE_MICRO_L2)
    assert decision == C.PASS and (norm["bid"], norm["ask"]) == (123.62, 123.63)
    assert _certifier(_trade(), C.FAMILLE_MICRO_TRADES)[1] == C.PASS


def test_ligne_alteree_apres_collecte_est_rejetee_par_la_somme_de_controle():
    falsifiee = dict(_bbo())
    falsifiee["ask"] = 73999.0                                    # prix modifié, checksum d'origine
    assert _certifier(falsifiee, C.FAMILLE_MICRO_BBO)[1:] == (C.QUARANTAINE, "checksum_invalide")
    sans = {k: v for k, v in _trade().items() if k != "checksum"}
    assert _certifier(sans, C.FAMILLE_MICRO_TRADES)[1:] == (C.QUARANTAINE, "checksum_invalide")


def test_carnets_et_cotations_incoherents_sont_rejetes():
    assert _certifier(_bbo(bid=73760.0, ask=73753.0), C.FAMILLE_MICRO_BBO)[1:] == (C.QUARANTAINE, "bbo_croise")
    assert _certifier(_bbo(bid_sz=None), C.FAMILLE_MICRO_BBO)[1:] == (C.QUARANTAINE, "bbo_taille_invalide")
    assert _certifier(_l2(bids=[[123.61, 1.0, 1], [123.62, 1.0, 1]]), C.FAMILLE_MICRO_L2)[1:] == (
        C.QUARANTAINE, "niveaux_l2_desordonnes")
    assert _certifier(_l2(asks=[]), C.FAMILLE_MICRO_L2)[1:] == (C.QUARANTAINE, "niveaux_l2_invalides")
    assert _certifier(_l2(bids=[[123.70, 1.0, 1]]), C.FAMILLE_MICRO_L2)[1:] == (C.QUARANTAINE, "marche_croisee")
    assert _certifier(_trade(side=0), C.FAMILLE_MICRO_TRADES)[1:] == (C.QUARANTAINE, "sens_inconnu")
    assert _certifier(_trade(ts_ex=NOW + 60_000), C.FAMILLE_MICRO_TRADES)[1:] == (C.QUARANTAINE, "timestamp_futur")


def test_noms_tournants_reconnus_sans_confondre_un_autre_fichier():
    assert C.detecter_famille("micro_bbo_1794306635046325200.jsonl.gz") == (C.FAMILLE_MICRO_BBO, "HL_WS_PUBLIC")
    assert C.detecter_famille("micro_l2book.jsonl") == (C.FAMILLE_MICRO_L2, "HL_WS_PUBLIC")
    assert C.detecter_famille("micro_bbo_notes.jsonl") is None
    assert C.detecter_famille("vault_fills_poll.jsonl")[0] == C.FAMILLE_FILLS_FORWARD   # pas « vault_fills » + rotation
    assert scl._tronc("micro_bbo_1794306635046325200.jsonl.gz") == scl._tronc("micro_bbo.jsonl") == "micro_bbo"
    assert scl._tronc("vault_fills_poll.jsonl") == "vault_fills_poll"


def _seqs(root: Path) -> list[list[int]]:
    index = json.loads((root / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
    lots = []
    for shard in index["shards"]:
        assert shard["famille"] == C.FAMILLE_MICRO_BBO
        with gzip.open(root / shard["shard"], "rt", encoding="utf-8") as h:
            lots.append([json.loads(l)["seq"] for l in h if l.strip()])
    return lots


def test_rotation_du_ruban_ni_perte_ni_doublon(tmp_path):
    """Ruban actif scellé, puis le collecteur écrit encore et fait tourner le fichier en .gz,
    puis recommence un ruban neuf : chaque ligne entre au coffre une fois et une seule."""
    dossier = tmp_path / "runtime" / "research_lab" / "data"       # dossier jamais visité auparavant
    dossier.mkdir(parents=True)
    actif = dossier / "micro_bbo.jsonl"
    texte = lambda rang: "".join(json.dumps(_bbo(i)) + "\n" for i in rang)   # noqa: E731
    actif.write_text(texte(range(0, 3)), encoding="utf-8")
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    assert _seqs(tmp_path) == [[1, 2, 3]]
    # le collecteur ajoute 2 lignes puis fait tourner : micro_bbo.jsonl -> micro_bbo_<ts>.jsonl.gz
    contenu = texte(range(0, 5))
    with gzip.open(dossier / "micro_bbo_1794306635046325200.jsonl.gz", "wt", encoding="utf-8") as h:
        h.write(contenu)
    actif.write_text(texte(range(10, 12)), encoding="utf-8")        # nouveau ruban actif
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    lots = _seqs(tmp_path)
    assert sorted(seq for lot in lots for seq in lot) == [1, 2, 3, 4, 5, 11, 12]   # tout, une seule fois
    assert [4, 5] in lots                                           # l'archive n'a apporté que sa suite
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0             # idempotent
    assert sorted(seq for lot in _seqs(tmp_path) for seq in lot) == [1, 2, 3, 4, 5, 11, 12]


def test_interruption_en_cours_de_lot_les_fichiers_finis_restent_au_coffre_sans_doublon(tmp_path, monkeypatch):
    """Coupure pendant le 2e fichier : le 1er est déjà indexé ; la reprise ne le refait pas."""
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    lab = tmp_path / "runtime" / "research_lab" / "data"
    lab.mkdir(parents=True)
    (data / "bbo_tape.jsonl").write_text(json.dumps({
        "venue": "HL", "coin": "BTC", "bid": 1.0, "ask": 2.0, "recv_wall_ts_ms": NOW - 9, "event_id": "q1"}) + "\n",
        encoding="utf-8")
    (lab / "micro_bbo.jsonl").write_text("".join(json.dumps(_bbo(i)) + "\n" for i in range(4)), encoding="utf-8")
    vrai = scl.certifier_record
    vus = {"micro": 0}

    def coupe(record, **kw):
        if kw.get("famille") == C.FAMILLE_MICRO_BBO:
            vus["micro"] += 1
            if vus["micro"] == 2:
                raise KeyboardInterrupt()
        return vrai(record, **kw)

    monkeypatch.setattr(scl, "certifier_record", coupe)
    try:
        scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)])
    except KeyboardInterrupt:
        pass
    coffre = tmp_path / "runtime" / "coffre_certifie"
    index = json.loads((coffre / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
    assert [(s["famille"], s["deposes"]) for s in index["shards"]] == [("bbo", 1)]     # 1er fichier acquis
    assert not list((coffre / "local" / "shards").rglob("*.partial"))
    monkeypatch.setattr(scl, "certifier_record", vrai)
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    index = json.loads((coffre / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
    assert sorted((s["famille"], s["deposes"]) for s in index["shards"]) == [("bbo", 1), ("micro_bbo", 4)]
