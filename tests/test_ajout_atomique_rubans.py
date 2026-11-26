"""Rubans partagés : ajout ATOMIQUE, et fusions d'AlinaSync en ajout seul (26/11/2026).

Mesuré : sous Windows, deux processus qui ajoutent au même fichier en mode "a" perdent des lignes (23 à 41 sur
120 000, plus des lignes coupées). Et la fusion explorer d'AlinaSync a échoué le 26/11 à 04:13 avec `WinError 32` :
elle RENOMMAIT le ruban vivant pendant que son collecteur le tenait ouvert ; quand le renommage passait, les lignes
écrites entre-temps par le collecteur partaient dans un `.bak` effacé à la fusion suivante.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
for chemin in (RACINE / "src", RACINE / "tools"):
    if str(chemin) not in sys.path:
        sys.path.insert(0, str(chemin))

from hl_observer.collection import collecte_fiable as CF  # noqa: E402

NOW = 1_795_000_000_000


def test_append_jsonl_ecrit_exactement_les_memes_octets_qu_avant(tmp_path):
    enrs = [{"x": 1, "é": "ü"}, {"y": [1, 2], "z": "a\nb", "w": "c\r\nd"}]
    ancien, nouveau = tmp_path / "ancien.jsonl", tmp_path / "nouveau.jsonl"
    for _ in range(2):
        with ancien.open("a", encoding="utf-8") as fh:                   # le code d'avant, mot pour mot
            for e in enrs:
                fh.write(json.dumps(e, ensure_ascii=False) + "\n")
        assert CF.append_jsonl(nouveau, enrs) == 2
    assert nouveau.read_bytes() == ancien.read_bytes()
    CF.ajouter_atomique(tmp_path / "lf.jsonl", "a\nb\n", fins_texte=False)
    assert (tmp_path / "lf.jsonl").read_bytes() == b"a\nb\n"               # newline="\n" : octets tels quels
    assert CF.ajouter_atomique(tmp_path / "vide.jsonl", "") == 0


def test_deux_processus_qui_ajoutent_en_meme_temps_ne_perdent_aucune_ligne(tmp_path):
    cible = tmp_path / "ruban.jsonl"
    script = (
        "import sys, json\n"
        "from hl_observer.collection.collecte_fiable import ajouter_atomique\n"
        "nom, n, lot = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])\n"
        "for i in range(0, n, lot):\n"
        "    t = ''.join(json.dumps({'p': nom, 'i': j, 'r': 'x' * (40 + j % 200)}) + chr(10)"
        " for j in range(i, min(n, i + lot)))\n"
        f"    ajouter_atomique({str(cible)!r}, t)\n"
    )
    env = {**os.environ, "PYTHONPATH": str(RACINE / "src")}
    n = 15_000
    procs = [subprocess.Popen([sys.executable, "-c", script, nom, str(n), str(lot)], env=env)
             for nom, lot in (("collecteur", 5), ("fusion", 1500))]
    assert all(p.wait(timeout=300) == 0 for p in procs)
    vus: dict[str, set[int]] = {"collecteur": set(), "fusion": set()}
    for ligne in cible.read_text(encoding="utf-8").splitlines():
        d = json.loads(ligne)                                                 # aucune ligne coupée
        vus[d["p"]].add(d["i"])
    assert {k: len(v) for k, v in vus.items()} == {"collecteur": n, "fusion": n}


def _ecrire_lignes(path: Path, lignes: list[str], fin: str = "\n") -> bytes:
    path.parent.mkdir(parents=True, exist_ok=True)
    brut = "".join(lignes_ + fin for lignes_ in lignes).encode("utf-8")
    path.write_bytes(brut)
    return brut


def _artefact(art: Path, job: str, nom: str, rows: list[dict]) -> None:
    d = art / job
    d.mkdir(parents=True, exist_ok=True)
    (d / nom).write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")


def test_la_fusion_explorer_n_ajoute_que_l_absent_meme_ruban_ouvert(tmp_path):
    import telecharger_explorer_github as T

    cible = tmp_path / "runtime" / "data" / "explorer_tx_tape.jsonl"
    avant = _ecrire_lignes(cible, [json.dumps({"user": "0xa", "hash": "h2", "time": 5}),
                                   json.dumps({"user": "0xb", "note": "sans hash"}),
                                   "{ligne cassée du collecteur",
                                   json.dumps({"user": "0xa", "hash": "h9", "time": 1})], fin="\r\n")
    art = tmp_path / "art"
    _artefact(art, "explorer-leaders", "explorer_tx_tape.jsonl",
              [{"user": "0xa", "hash": "h2", "time": 5}, {"user": "0xc", "hash": "h3", "time": 9},
               {"user": "0xb", "note": "sans hash"}])
    _artefact(art, "explorer-decouverte", "explorer_tx_tape.jsonl",
              [{"user": "0xc", "hash": "h3", "time": 9}, {"user": "0xd", "hash": "h1", "time": 2}])
    with cible.open("r", encoding="utf-8"):                                   # le collecteur tient le ruban
        rap = T.fusionner_explorer(tmp_path, art)
    apres = cible.read_bytes()
    assert apres.startswith(avant)                                            # le local n'est jamais réécrit
    ajout = [json.loads(x) for x in apres[len(avant):].decode("utf-8").splitlines()]
    assert [r["hash"] for r in ajout] == ["h1", "h3"]                        # absents seulement, triés par instant
    assert rap["ajoutees"] == 2 and rap["locales"] == 3 and rap["mode"] == "AJOUT_SEUL"
    assert sorted(p.name for p in cible.parent.iterdir()) == ["explorer_tx_tape.jsonl"]   # ni .tmp ni .bak
    rap2 = T.fusionner_explorer(tmp_path, art)
    assert rap2["ajoutees"] == 0 and cible.read_bytes() == apres             # idempotent


def _carnet(coin: str, exch: int, *, valide: bool = True) -> dict:
    row = {"schema_version": "hypersmart.copy_vault_l2.v1", "coin": coin, "received_at_ms": exch + 50,
           "exchange_ts_ms": exch, "bid": 2000.0, "ask": 2001.0, "bids5": [[2000.0, 5.0]],
           "asks5": [[2001.0, 4.0]], "source": "HYPERLIQUID_L2_WS"}
    if not valide:
        row["bid"], row["ask"] = 2002.0, 2001.0                               # carnet croisé : quarantaine
        row["bids5"] = [[2002.0, 5.0]]
    return row


def test_la_fusion_l2_garde_chaque_carnet_local_et_n_ajoute_que_l_absent(tmp_path):
    import telecharger_l2_lanes_github as T

    cible = tmp_path / "runtime" / "data" / "copy_vault_l2_tape.jsonl"
    avant = _ecrire_lignes(cible, [json.dumps(_carnet("ETH", NOW - 3000)),
                                   json.dumps(_carnet("ETH", NOW - 2000, valide=False))])
    art = tmp_path / "art"
    _artefact(art, "l2-shard-0", "copy_vault_l2_lane.jsonl",
              [_carnet("ETH", NOW - 3000), _carnet("ETH", NOW - 2000), _carnet("BTC", NOW - 1000),
               _carnet("BTC", NOW - 1000), _carnet("SOL", NOW - 500, valide=False)])
    with cible.open("r", encoding="utf-8"):
        rap = T.fusionner_carnets(tmp_path, art, now_ms=NOW)
    apres = cible.read_bytes()
    assert apres.startswith(avant)                                            # le carnet local invalide RESTE
    ajout = [json.loads(x) for x in apres[len(avant):].decode("utf-8").splitlines()]
    assert [(r["coin"], r["exchange_ts_ms"]) for r in ajout] == [("ETH", NOW - 2000), ("BTC", NOW - 1000)]
    assert rap["ajoutees"] == 2 and rap["rejets_qualite"] == 1 and rap["total_final"] == 3
    assert sorted(p.name for p in cible.parent.iterdir()) == ["copy_vault_l2_tape.jsonl"]


def test_la_fusion_bbo_n_ajoute_que_l_absent(tmp_path):
    import telecharger_l2_lanes_github as T

    def bbo(exch):
        return {"schema_version": "hypersmart.copy_vault_bbo.v1", "coin": "ETH", "received_at_ms": exch + 50,
                "exchange_ts_ms": exch, "bid_px": 2000.0, "bid_sz": 5.0, "ask_px": 2001.0, "ask_sz": 4.0,
                "source": "HYPERLIQUID_BBO_WS"}

    cible = tmp_path / "runtime" / "data" / "copy_vault_bbo_tape.jsonl"
    avant = _ecrire_lignes(cible, [json.dumps(bbo(NOW - 1000))])
    art = tmp_path / "art"
    _artefact(art, "l2-shard-0", "copy_vault_bbo_lane.jsonl", [bbo(NOW - 1000), bbo(NOW - 500), bbo(NOW - 500)])
    with cible.open("r", encoding="utf-8"):
        rap = T.fusionner_bbo(tmp_path, art, now_ms=NOW)
    apres = cible.read_bytes()
    assert apres.startswith(avant) and len(apres[len(avant):].splitlines()) == 1
    assert rap["ajoutees"] == 1 and rap["total_final"] == 2


def test_les_ecrivains_des_rubans_partages_passent_tous_par_l_ajout_atomique():
    """Un seul ancien écrivain en "a" suffit à perdre des lignes : chaque ruban partagé est gardé ici."""
    gardes = {
        "collecter_explorer_lane.py": ["self.out_path"],
        "collecter_market_lane.py": ["self.trades_out", "self.candle_out"],
        "collecter_contexte_lane.py": ["self.snap_out", "self.ordres_out", "self.pos_out", "self.twap_out"],
        "telecharger_lanes_certifiees_github.py": ["cible"],
        "telecharger_explorer_github.py": ["cible"],
        "telecharger_l2_lanes_github.py": ["cible"],
    }
    for nom, ecrivains in gardes.items():
        src = (RACINE / "tools" / nom).read_text(encoding="utf-8")
        for var in ecrivains:
            assert f'{var}.open("a"' not in src, f"{nom} : {var} ajoute encore en mode \"a\""
            assert f"ajouter_atomique({var}" in src, f"{nom} : {var} n'écrit pas par ajouter_atomique"
        assert ".rename(" not in src or nom not in ("telecharger_explorer_github.py", "telecharger_l2_lanes_github.py")
    socle = (RACINE / "src" / "hl_observer" / "collection" / "copy_vault_checkpoint_socle.py").read_text(encoding="utf-8")
    corps = socle[socle.index("def _append_jsonl("):][:700]
    assert "ajouter_atomique(path" in corps and '.open("a"' not in corps          # 3e ecrivain du ruban L2
    fusion = (RACINE / "tools" / "fusionner_fills_lanes.py").read_text(encoding="utf-8")
    assert "_ajouter_au_ruban_live(root" in fusion                                   # ruban live : ajout seul
    ufv = (RACINE / "tools" / "collecter_userfills_vaults.py").read_text(encoding="utf-8")
    bloc = ufv[ufv.index("path = Path(root) / COPY_VAULT_L2_TAPE"):][:600]
    assert "ajouter_atomique(path" in bloc and '.open("a"' not in bloc
