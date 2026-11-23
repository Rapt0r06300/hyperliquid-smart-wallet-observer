"""Recensement de toutes les données du projet (23/11/2026) : un verdict par fichier, aucun oubli, et le certificateur
scelle ce qui manquait.

Verrouille :
- chaque zone de l'inventaire réel a sa règle ; un dossier sans règle qui contient des données sort en INCONNU ;
- les verdicts de scellement (SCELLE, EN_COURS, A_SCELLER) se lisent dans l'état du certificateur ;
- une session archivée APRÈS la règle de l'archiveur est scellée par construction ; AVANT et sans trace : A_PROUVER ;
- une archive compressée par blocs est reconnue scellée par son index, sans décompression ;
- les magasins ne sont pas parcourus fichier par fichier (vitesse) mais sont déclarés ;
- le recensement n'utilise PAS la découverte du certificateur (sinon 100 % par construction) ;
- ``--recensement`` fait sceller une donnée oubliée et la couverture remonte à 100 %.
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

from hl_observer.datasets import archive_gzip_blocs as A  # noqa: E402
from hl_observer.datasets import recensement_donnees as R  # noqa: E402

NOW = 1_795_000_000_000


def _ecrire(chemin: Path, n: int = 3) -> bytes:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    brut = "".join(json.dumps({"coin": "ETH", "ts_ms": NOW - 1000 + i, "mark": 2000.0}) + "\n" for i in range(n)).encode()
    chemin.write_bytes(brut)
    return brut


def _etat(root: Path, entrees: dict) -> None:
    p = root / R.ETAT_COFFRE
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(entrees), encoding="utf-8")


def test_les_zones_de_l_inventaire_reel_ont_chacune_leur_regle():
    attendu = {
        "runtime/data/market_ticks/hl/x": "MAGASIN", "runtime/recovery/full/a": "MAGASIN", "datasets/safe/x": "MAGASIN",
        "runtime/archive/session_20261120_100000/bbo_tape.jsonl": "COLLECTE", "runtime/data/bbo_tape.jsonl": "COLLECTE",
        "runtime/history/funding_1h.jsonl": "COLLECTE", "runtime/history/ironflow/funding/x.parquet": "EXTERNE",
        "runtime/reports/copy_vault_quant_lab/x.jsonl": "DERIVE", "runtime/labo_tranches_20261121/w/x.jsonl": "DERIVE",
        "runtime/research_lab/data/goal2_cache/fills.parquet": "DERIVE", "runtime/research_lab/data/micro_bbo.jsonl": "COLLECTE",
        "runtime/coffre_certifie/quarantine/b/x.jsonl": "QUARANTAINE", "runtime/coffre_certifie/CERTIF_JOURNAL.jsonl": "JOURNAL",
        "tools/python/Lib/x.csv": "ENVIRONNEMENT",
    }
    for rel, genre in attendu.items():
        assert R.zone_de(rel) is not None and R.zone_de(rel).genre == genre, rel
    assert R.zone_de("dossier_imprevu/x.jsonl") is None


def test_chaque_fichier_de_donnees_recoit_un_verdict_exact(tmp_path):
    root = tmp_path
    scelle = _ecrire(root / "runtime/data/asset_ctx_tape.jsonl")
    _ecrire(root / "runtime/data/bbo_tape.jsonl", 5)
    _ecrire(root / "runtime/data/liquidations_confirmees.jsonl")                        # aucune trace
    (root / "runtime/data/vide.jsonl").write_bytes(b"")
    _ecrire(root / "runtime/data/poll_cadence_plan.ndjson")
    _ecrire(root / "runtime/archive/session_20261120_100000/asset_ctx_tape.jsonl", 4)   # après la règle
    _ecrire(root / "runtime/archive/session_20261109_100000/asset_ctx_tape.jsonl", 6)   # avant la règle (contenu propre)
    _ecrire(root / "runtime/reports/x/sortie.jsonl")
    _ecrire(root / "runtime/history/ironflow/funding/data/2026-10.parquet")
    _ecrire(root / "runtime/history/ironflow/funding/data/2026-11.parquet")             # hors manifeste
    (root / "runtime/history/ironflow/MANIFESTE.json").write_text(json.dumps(
        {"fichiers": {"funding/data/2026-10.parquet": {"statut": "EXTERNAL_VALIDATED"}}}), encoding="utf-8")
    _ecrire(root / "runtime/data/market_ticks/hl/btc.jsonl.gz")                         # magasin : non parcouru
    _ecrire(root / "un_dossier_sans_regle/export.jsonl")
    _etat(root, {
        "runtime\\data\\asset_ctx_tape.jsonl": {"taille": len(scelle), "prefixe_octets": len(scelle),
                                                "prefixe_sha256": hashlib.sha256(scelle).hexdigest()},
        "runtime\\data\\bbo_tape.jsonl": {"taille": 10, "prefixe_octets": 10, "prefixe_sha256": "x"},
    })
    r = R.recenser(root)
    verdict = {x["fichier"]: v for v, liste in r["listes"].items() for x in liste}
    assert verdict["runtime/data/liquidations_confirmees.jsonl"] == "A_SCELLER"
    assert verdict["runtime/archive/session_20261109_100000/asset_ctx_tape.jsonl"] == "A_PROUVER"
    assert verdict["runtime/history/ironflow/funding/data/2026-11.parquet"] == "EXTERNE_NON_MANIFESTE"
    assert verdict["un_dossier_sans_regle/export.jsonl"] == "INCONNU"
    t = r["totaux"]
    assert t["SCELLE"]["fichiers"] == 2                       # la session récente l'est par l'archiveur
    assert t["EN_COURS"]["fichiers"] == 1 and t["VIDE"]["fichiers"] == 1 and t["EXTERNE_VALIDE"]["fichiers"] == 1
    assert t["PAR_CONCEPTION"]["fichiers"] == 2               # le plan du collecteur + la sortie du labo
    assert "runtime/data/market_ticks" in r["non_parcourus"]
    assert r["fichiers_de_donnees"] == 11 and not r["cent_pour_cent"]             # le magasin n'est pas compté


def test_une_archive_compressee_est_reconnue_scellee_par_son_index(tmp_path):
    session = tmp_path / "runtime/archive/session_20261109_100000/asset_ctx_tape.jsonl"    # avant la règle
    brut = _ecrire(session, 50)
    _etat(tmp_path, {"runtime\\data\\asset_ctx_tape.jsonl": {
        "taille": 1, "prefixes_precedents": [[len(brut), hashlib.sha256(brut).hexdigest()]]}})
    A.remplacer_par_archive(session)
    r = R.recenser(tmp_path)
    assert r["totaux"] == {"SCELLE": {"fichiers": 1, "octets": (session.with_name(session.name + ".gz")).stat().st_size}}


def test_une_rotation_d_un_ruban_deja_scelle_se_prouve_et_ne_se_scelle_jamais_a_l_aveugle(tmp_path):
    """23/11/2026 : deux rotations BBO du 13/11, sans trace exacte dans l'état mais issues d'un ruban scellé au fil
    de l'eau, ont été prises pour des oubliées. Les sceller en entier redéposerait ce que le coffre a déjà."""
    rotation = tmp_path / "runtime/data/bbo_shards_archive/bbo_tape_1794923250698696700.jsonl.gz"
    rotation.parent.mkdir(parents=True)
    with gzip.open(rotation, "wb") as g:
        g.write(_ecrire(tmp_path / "tmp.jsonl", 5))
    (tmp_path / "tmp.jsonl").unlink()
    _etat(tmp_path, {"runtime\\data\\bbo_tape.jsonl": {"taille": 10, "prefixe_octets": 10, "prefixe_sha256": "x"}})
    r = R.recenser(tmp_path)
    assert r["totaux"] == {"A_PROUVER": {"fichiers": 1, "octets": rotation.stat().st_size}}
    assert r["a_sceller"] == []                                      # jamais « à sceller » à l'aveugle…
    assert [x["fichier"] for x in r["a_prouver_gz"]] == [             # …mais le certificateur la PROUVE (identités
        "runtime/data/bbo_shards_archive/bbo_tape_1794923250698696700.jsonl.gz"]   # préchargées sur sa période)


def test_une_session_recente_compressee_reste_scellee_par_l_archiveur(tmp_path):
    """23/11/2026 : la règle des rotations (« à prouver ») avait fait perdre leur garantie à 255 archives de session
    compressées. Une session postérieure à la règle de l'archiveur reste scellée, compressée ou non."""
    session = tmp_path / "runtime/archive/session_20261120_100000/bbo_tape.jsonl"
    _ecrire(session, 50)
    A.remplacer_par_archive(session)
    _etat(tmp_path, {"runtime\\data\\bbo_tape.jsonl": {"taille": 10, "prefixe_octets": 10, "prefixe_sha256": "x"}})
    r = R.recenser(tmp_path)
    assert list(r["totaux"]) == ["SCELLE"]


def test_le_recensement_n_utilise_pas_la_decouverte_du_certificateur(tmp_path, monkeypatch):
    import sceller_coffre_local as S

    def interdit(*a, **k):
        raise AssertionError("le recensement a appelé la découverte du certificateur")

    monkeypatch.setattr(S, "collecter_fichiers", interdit)
    _ecrire(tmp_path / "runtime/data/asset_ctx_tape.jsonl")
    assert R.recenser(tmp_path)["fichiers_de_donnees"] == 1


def test_le_certificateur_scelle_la_donnee_oubliee_et_la_couverture_atteint_100(tmp_path):
    import sceller_coffre_local as S

    oublie = tmp_path / "runtime/data/bbo_shards/asset_ctx_tape_1795000000000.jsonl.gz"   # sous-dossier : oublié
    oublie.parent.mkdir(parents=True)
    with gzip.open(oublie, "wb") as g:
        g.write(_ecrire(tmp_path / "tmp_source.jsonl", 20))
    (tmp_path / "tmp_source.jsonl").unlink()
    assert R.recenser(tmp_path)["totaux"]["A_SCELLER"]["fichiers"] == 1
    assert S.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0                  # passage habituel : l'oublie
    assert R.recenser(tmp_path)["totaux"]["A_SCELLER"]["fichiers"] == 1
    assert S.main(["--root", str(tmp_path), "--now-ms", str(NOW), "--recensement"]) == 0
    rapport = json.loads((tmp_path / R.RAPPORT).read_text(encoding="utf-8"))
    assert rapport["cent_pour_cent"] and rapport["couverture_pct"] == 100.0
    assert rapport["avant_ce_passage"]["totaux"]["A_SCELLER"]["fichiers"] == 1
    index = json.loads((tmp_path / "runtime/coffre_certifie/LOCAL_INDEX.json").read_text(encoding="utf-8"))
    assert sum(s["deposes"] for s in index["shards"]) == 20
