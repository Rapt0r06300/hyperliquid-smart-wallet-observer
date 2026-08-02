"""[LAB α item 11/5] Ingestion en STREAMING à mémoire bornée : plus de plafond arbitraire 200k, spill
disque, checkpoint/reprise, fenêtre RAM bornée. 0 réseau.
"""
from __future__ import annotations

import json
import types
from pathlib import Path

from hl_observer.ops import lab_flux as F


def _fichier_events(tmp_path, n, nom="data.jsonl"):
    p = Path(tmp_path) / nom
    with p.open("w", encoding="utf-8") as fh:
        for i in range(n):
            fh.write(json.dumps({"coin": "BTC", "ts_ms": 1000 + i, "signe": 1, "mid": 100.0 + i}) + "\n")
    return p


def test_flux_est_un_generateur_paresseux_et_borne(tmp_path):
    f = _fichier_events(tmp_path, 100)
    flux = F.flux_evenements_stream([f], max_events=5)
    assert isinstance(flux, types.GeneratorType)             # paresseux : ne matérialise rien
    evs = list(flux)
    assert len(evs) == 5                                     # max_events borne réellement (pas 100)


def test_max_events_zero_lit_tout(tmp_path):
    f = _fichier_events(tmp_path, 40)
    evs = list(F.flux_evenements_stream([f], max_events=0))
    assert len(evs) == 40                                    # 0 = pas de plafond arbitraire


def test_materialiser_shard_spill_disque_et_checkpoint(tmp_path):
    f = _fichier_events(tmp_path, 30)
    shard = tmp_path / "shard.jsonl"
    cp = tmp_path / "cp.json"
    info = F.materialiser_shard([f], shard, checkpoint_path=cp)
    assert info["n"] == 30 and info["repris"] is False and shard.is_file()
    assert F.compter_shard(shard) == 30
    assert json.loads(cp.read_text())["complet"] is True


def test_reprise_ne_recalcule_pas_un_shard_complet(tmp_path):
    f = _fichier_events(tmp_path, 20)
    shard = tmp_path / "shard.jsonl"
    cp = tmp_path / "cp.json"
    F.materialiser_shard([f], shard, checkpoint_path=cp)
    mtime1 = shard.stat().st_mtime_ns
    info2 = F.materialiser_shard([f], shard, checkpoint_path=cp)      # 2e passe : reprise
    assert info2["repris"] is True and info2["n"] == 20
    assert shard.stat().st_mtime_ns == mtime1                        # le shard n'a PAS été réécrit


def test_charger_borne_fenetre_memoire(tmp_path):
    f = _fichier_events(tmp_path, 50)
    shard = tmp_path / "shard.jsonl"
    F.materialiser_shard([f], shard)
    assert len(F.charger_borne(shard, max_ram=10)) == 10             # fenêtre RAM bornée explicite
    assert len(F.charger_borne(shard, max_ram=0)) == 50              # 0 = tout


def test_plusieurs_fichiers_streames_ensemble(tmp_path):
    f1 = _fichier_events(tmp_path, 12, "a.jsonl")
    f2 = _fichier_events(tmp_path, 8, "b.jsonl")
    assert sum(1 for _ in F.flux_evenements_stream([f1, f2])) == 20


def _fichier_ts(tmp_path, nom, ts_list, coin="BTC"):
    """Un fichier feed lab dont les evenements portent des ts_ms explicites (ordre causal testable)."""
    p = Path(tmp_path) / nom
    with p.open("w", encoding="utf-8") as fh:
        for t in ts_list:
            fh.write(json.dumps({"coin": coin, "ts_ms": t, "signe": 1, "mid": 100.0}) + "\n")
    return p


def test_cle_causale_ordonne_par_temps_puis_source():
    a = {"ts_ms": 1000, "source": "binance"}
    b = {"ts_ms": 2000, "source": "hyperliquid"}
    c = {"source": "x"}                                       # sans temps -> trie APRES (inf)
    assert F.cle_causale(a) < F.cle_causale(b) < F.cle_causale(c)


def test_fusion_causale_entrelace_deux_venues_dans_le_temps(tmp_path):
    # item 9 : le coeur du Lead-Lag. Binance a des ticks a 1000/3000/5000, Hyperliquid a 2000/4000.
    # Une concatenation naive donnerait 1000,3000,5000,2000,4000 (FAUX). La fusion causale DOIT donner
    # 1000,2000,3000,4000,5000 -> on peut alors mesurer qui bouge avant qui.
    fb = _fichier_ts(tmp_path, "binance.jsonl", [1000, 3000, 5000])
    fh = _fichier_ts(tmp_path, "hyperliquid.jsonl", [2000, 4000])
    shard = tmp_path / "global.jsonl"
    info = F.fusionner_causalement([fb, fh], shard)
    assert info["n"] == 5 and info["hors_ordre"] == 0          # ordre causal PROUVE (0 hors-ordre)
    evs = F.charger_borne(shard)
    assert [e["ts_ms"] for e in evs] == [1000, 2000, 3000, 4000, 5000]   # entrelace, pas concatene
    # la venue de chaque tick est preservee (indispensable au cross-venue).
    par_ts = {e["ts_ms"]: e["source"] for e in evs}
    assert par_ts[1000] == "binance" and par_ts[2000] == "hyperliquid"


def test_fusion_causale_nest_pas_une_concatenation(tmp_path):
    # preuve directe : la sortie DIFFERE de la simple concatenation fichier-par-fichier.
    fb = _fichier_ts(tmp_path, "b.jsonl", [10, 30])
    fh = _fichier_ts(tmp_path, "h.jsonl", [20, 40])
    concat = [e["ts_ms"] for e in F.flux_evenements_stream([fb, fh])]
    shard = tmp_path / "g.jsonl"
    F.fusionner_causalement([fb, fh], shard)
    causal = [e["ts_ms"] for e in F.charger_borne(shard)]
    assert concat == [10, 30, 20, 40]                         # concatenation naive (ordre FAUX)
    assert causal == [10, 20, 30, 40]                         # fusion causale (ordre VRAI)
    assert concat != causal


def test_fusion_causale_dedup_reconnexion_meme_source(tmp_path):
    # une source qui, apres reconnexion, renvoie DEUX FOIS le meme enregistrement (chevauchement snapshot).
    # Apres tri causal les doublons sont adjacents -> ecartes. Contenu identique = meme evenement.
    p = Path(tmp_path) / "hyperliquid.jsonl"
    ligne = json.dumps({"coin": "BTC", "ts_ms": 100, "signe": 1, "mid": 1.0})
    p.write_text(ligne + "\n" + ligne + "\n", encoding="utf-8")   # meme tick renvoye 2x
    shard = tmp_path / "g.jsonl"
    info = F.fusionner_causalement([p], shard)
    assert info["dedupes"] == 1 and info["n"] == 1               # doublon exact ecarte


def test_fusion_causale_ne_fusionne_pas_deux_venues_identiques(tmp_path):
    # meme prix/temps sur DEUX venues = DEUX evenements distincts (cross-venue) -> JAMAIS deduplique.
    pb = Path(tmp_path) / "binance.jsonl"
    ph = Path(tmp_path) / "hyperliquid.jsonl"
    rec = {"coin": "BTC", "ts_ms": 100, "signe": 1, "mid": 1.0}
    pb.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    ph.write_text(json.dumps(rec) + "\n", encoding="utf-8")
    shard = tmp_path / "g.jsonl"
    info = F.fusionner_causalement([pb, ph], shard)
    assert info["dedupes"] == 0 and info["n"] == 2               # 2 venues distinctes conservees
    sources = {e["source"] for e in F.charger_borne(shard)}
    assert sources == {"binance", "hyperliquid"}


def test_fusion_causale_memoire_bornee_petits_runs(tmp_path):
    # max_ram_tri tres petit -> plusieurs runs par source (tri-fusion externe), resultat toujours trie.
    f = _fichier_ts(tmp_path, "a.jsonl", [5, 3, 1, 4, 2])     # volontairement DESORDONNE dans le fichier
    shard = tmp_path / "g.jsonl"
    info = F.fusionner_causalement([f], shard, max_ram_tri=2)  # force le spill en runs de 2
    assert info["runs"] >= 3 and info["hors_ordre"] == 0
    assert [e["ts_ms"] for e in F.charger_borne(shard)] == [1, 2, 3, 4, 5]   # trie malgre l'entree en vrac


def test_fusion_causale_reprise_checkpoint(tmp_path):
    f = _fichier_ts(tmp_path, "a.jsonl", [1, 2, 3])
    shard = tmp_path / "g.jsonl"
    cp = tmp_path / "g.cp.json"
    F.fusionner_causalement([f], shard, checkpoint_path=cp)
    mtime1 = shard.stat().st_mtime_ns
    info2 = F.fusionner_causalement([f], shard, checkpoint_path=cp)
    assert info2["repris"] is True and shard.stat().st_mtime_ns == mtime1    # pas de recalcul


def test_lab_alpha_utilise_la_fusion_causale_pas_la_concatenation():
    # item 9 : le replay d'ANALYSER passe par la FUSION CAUSALE, jamais la concatenation naive.
    import inspect
    from hl_observer.ops import lab_alpha as LA
    src = inspect.getsource(LA)
    assert "fusionner_causalement(" in src                   # le shard global est fusionne causalement
    assert "materialiser_shard(" not in src                  # l'ancienne concatenation n'est plus appelee
    assert "_venue_du_fichier" in src                        # chaque artefact est etiquete de sa venue


def test_venue_du_fichier_detecte_la_venue():
    from hl_observer.ops.lab_alpha import _venue_du_fichier
    assert _venue_du_fichier("runtime/data/sessions/r/binance_book.jsonl") == "binance"
    assert _venue_du_fichier("x/hyperliquid_bbo.jsonl") == "hyperliquid"
    assert _venue_du_fichier("x/dydx_trades.jsonl") == "dydx"
    assert _venue_du_fichier("x/inconnu.jsonl") == "inconnu"  # defaut = nom de fichier


def test_inventaire_signale_la_troncature_item7(tmp_path, capsys):
    from hl_observer.ops.lab_inventaire import inventorier
    d = tmp_path / "runtime" / "replay"
    d.mkdir(parents=True)
    for i in range(6):
        (d / ("f%d.jsonl" % i)).write_text('{"coin":"BTC","ts_ms":1,"px":1,"signe":1}\n', encoding="utf-8")
    inv = inventorier(tmp_path, max_fichiers=3)               # plafond ATTEINT
    assert inv["tronque"] is True and inv["plafond_fichiers"] == 3
    assert "tronque" in capsys.readouterr().err.lower()       # SIGNALE, jamais silencieux
    inv2 = inventorier(tmp_path, max_fichiers=0)              # 0 = illimite -> tout traite
    assert inv2["tronque"] is False and inv2["total_fichiers"] >= 6
