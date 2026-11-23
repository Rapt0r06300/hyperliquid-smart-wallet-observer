"""Données externes gratuites au coffre (23/11/2026) : étiquetées, recoupées, sans doublon, comptées à part.

Ce que ces tests verrouillent, chacun pour une panne réelle ou évitée de justesse :
- le certificateur reconnaît les rubans externes et l'index du coffre dit leur PROVENANCE ;
- le funding n'est jamais compté deux fois à la même heure (444 073 règlements d'Alina étaient en double au coffre
  le 23/11, et le portage du labo les additionnait), Alina restant prioritaire sur une source externe ;
- le pont du labo range les signaux externes à part (``signaux_externes_par_famille``) ;
- l'open interest d'Ironflow, daté du début de l'heure mais mesuré à sa fin, entre daté de la fin (jamais en avance) ;
- un fichier dont la quarantaine dépasse 0,1 % est refusé en entier ; un groupe non recoupé n'entre pas, mais il
  reste candidat quand une version suivante le recoupe, sans reverser ce qui l'a déjà été ;
- ``--plan`` n'écrit rien.
"""
from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
for _p in (RACINE / "src", RACINE / "tools"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

import coffre_donnees_externes as X  # noqa: E402
from hl_observer.datasets import coffre_certifie as C  # noqa: E402

H = 3_600_000
T0 = 1_790_812_800_000          # 2026-10-01T00:00Z


def _shard(root: Path, famille: str, nom: str, rows: list[dict], **index) -> dict:
    rel = f"runtime/coffre_certifie/local/shards/{famille}/{nom}.jsonl.gz"
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(p, "wt", encoding="utf-8") as h:
        for r in rows:
            h.write(json.dumps(r) + "\n")
    import hashlib
    ts = [r.get("ts_ms") or r.get("open_ts_ms") for r in rows]
    return {"famille": famille, "shard": rel, "sha256": hashlib.sha256(p.read_bytes()).hexdigest(),
            "coins": sorted({r["coin"] for r in rows}), "ts_min_ms": min(ts), "ts_max_ms": max(ts),
            "deposes": len(rows), **index}


def _index(root: Path, shards: list[dict]) -> None:
    p = root / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"shards": shards}), encoding="utf-8")


EXTERNE = {"provenance": C.ORIGINE_EXTERNE, "source_tag": "EXTERNE_IRONFLOW"}


# --------------------------------------------------------------------------- reconnaissance et index

@pytest.mark.parametrize("jeu", list(X.JEUX))
def test_chaque_ruban_externe_est_reconnu_dans_sa_famille_avec_une_etiquette_externe(jeu):
    nom = X.nom_du_ruban({"jeu": jeu, "cle": f"{jeu}/data/2026-10.parquet", "version": "abc", "bornes": (T0, T0 + H)})
    famille, tag = C.detecter_famille(nom)
    assert famille == X.JEUX[jeu][1]
    assert tag.startswith(C.PREFIXE_SOURCE_EXTERNE)
    # une nouvelle version du même fichier source porte un autre nom : jamais d'écrasement d'un ruban scellé
    assert X.nom_du_ruban({"jeu": jeu, "cle": f"{jeu}/data/2026-10.parquet", "version": "abd",
                           "bornes": (T0, T0 + H)}) != nom


def test_l_index_du_coffre_dit_la_provenance_externe_et_seulement_elle(tmp_path):
    import sceller_coffre_local as S

    hist = tmp_path / "runtime" / "history"
    hist.mkdir(parents=True)
    rec = {**X.PROVENANCE, "source": "IRONFLOW_HF", "coin": "BTC", "ts_ms": T0, "funding": 1e-5}
    nom_ext = X.nom_du_ruban({"jeu": "funding", "cle": "funding/data/2026-10.parquet", "version": "v", "bornes": (T0, T0)})
    with gzip.open(hist / nom_ext, "wt", encoding="utf-8") as f:
        f.write(json.dumps(rec) + "\n")
    (hist / "funding_1h.jsonl").write_text(json.dumps({"coin": "ETH", "ts_ms": T0, "funding": 2e-5}) + "\n",
                                           encoding="utf-8")
    assert S.main(["--root", str(tmp_path), "--now-ms", str(T0 + 10 * H),
                   "--nom", nom_ext, "--nom", "funding_1h.jsonl"]) == 0                    # --nom répétable
    shards = json.loads((tmp_path / "runtime/coffre_certifie/LOCAL_INDEX.json").read_text(encoding="utf-8"))["shards"]
    par = {Path(s["shard"]).name.split("__", 1)[1]: s for s in shards}
    ext = next(s for n, s in par.items() if n.startswith("externe_"))
    alina = next(s for n, s in par.items() if n.startswith("funding_1h"))
    assert ext["provenance"] == C.ORIGINE_EXTERNE and ext["source_tag"] == "EXTERNE_IRONFLOW"
    assert "provenance" not in alina and "source_tag" not in alina                     # le format d'Alina ne bouge pas


# --------------------------------------------------------------------------- lecteur du funding (portage)

def test_le_funding_n_est_jamais_compte_deux_fois_a_la_meme_heure_et_alina_est_prioritaire(tmp_path):
    from hl_observer.backtesting import copy_vault_funding_realise as FR

    alina = [{"coin": "BTC", "ts_ms": T0 + 50, "funding": 0.0001, "interval": "1h"},
             {"coin": "BTC", "ts_ms": T0 + H + 40, "funding": 0.0002, "interval": "1h"}]
    alina_bis = [{"coin": "BTC", "ts_ms": T0 + 70, "funding": 0.0001, "interval": "1h"}]   # même règlement, 2e ruban
    externe = [{"coin": "BTC", "ts_ms": T0 - H + 30, "funding": 0.0005, "interval": "1h", **X.PROVENANCE},
               {"coin": "BTC", "ts_ms": T0 + H + 40, "funding": 0.0009, "interval": "1h", **X.PROVENANCE},
               {"coin": "BTC", "ts_ms": T0 + 2 * H + 30, "funding": 0.0003, "interval": "1h", **X.PROVENANCE}]
    tardif = [{"coin": "BTC", "ts_ms": T0 + 50, "funding": 0.0007, "interval": "1h", **X.PROVENANCE}]
    # « a__externe » commence plus tôt : lu EN PREMIER, Alina le REMPLACE à l'heure partagée ; « d__externe » est lu
    # APRÈS Alina (même début, nom plus loin) : il ne la remplace pas.
    _index(tmp_path, [_shard(tmp_path, "funding_history", "a__externe", externe, **EXTERNE),
                      _shard(tmp_path, "funding_history", "b__alina", alina),
                      _shard(tmp_path, "funding_history", "c__alina_bis", alina_bis),
                      _shard(tmp_path, "funding_history", "d__externe", tardif, **EXTERNE)])
    taux, audit = FR.taux_du_coffre(tmp_path, coins=None, debut_ms=T0 - 2 * H, fin_ms=T0 + 5 * H)
    assert [float(v) for _, v in taux["BTC"]] == [0.0005, 0.0001, 0.0002, 0.0003]  # une valeur par heure, Alina d'abord
    assert audit["doublons_horaires_ecartes"] == 3                                  # 2e ruban d'Alina + 2 externes
    assert audit["doublons_de_valeur_differente"] == 2                              # 0,0009 et 0,0007 : dits
    assert audit["reglements_externes_gardes"] == 2


def test_le_rattrapage_ne_prend_pas_une_source_externe_pour_une_couverture_d_alina(tmp_path):
    from hl_observer.ops import rattrapage_coffre as R

    _index(tmp_path, [_shard(tmp_path, "funding_history", "a__externe",
                             [{"coin": "BTC", "ts_ms": T0, "funding": 1e-5, **X.PROVENANCE}], **EXTERNE),
                      _shard(tmp_path, "funding_history", "b__funding_1h",
                             [{"coin": "ETH", "ts_ms": T0, "funding": 1e-5, "source": "REST_FUNDING_HISTORY"}])])
    assert R.couverture_du_coffre(tmp_path, cache=False) == {"funding": {"ETH": [T0, T0]}}


# --------------------------------------------------------------------------- pont du labo

def test_le_pont_du_labo_range_les_signaux_externes_a_part(tmp_path):
    from hl_observer.backtesting import copy_vault_tier_local as TL

    alina = [{"coin": "ETH", "ts_ms": T0 + i, "px": 2000.0, "sz": 1.0} for i in range(3)]
    ext = [{"coin": "ETH", "ts_ms": T0 + 10 + i, "px": 2000.0, "sz": 1.0, **X.PROVENANCE} for i in range(5)]
    _index(tmp_path, [_shard(tmp_path, "liquidation", "a__liq", alina),
                      _shard(tmp_path, "liquidation", "b__liq_ext", ext, **EXTERNE)])
    r = TL._charger_tier_local(tmp_path)
    assert r["signaux_par_famille"] == {"liquidation": 3} and r["signaux_total"] == 3
    assert r["signaux_externes_par_famille"] == {"liquidation": 5}
    assert len(r["_signaux"]["liquidation" + TL.SUFFIXE_SIGNAL_EXTERNE]) == 5           # disponibles à la recherche


# --------------------------------------------------------------------------- conversion

def test_l_open_interest_entre_date_de_la_fin_de_son_heure_jamais_en_avance():
    rec, motif = X.convertir("open-interest", {"ts": T0, "coin": "BTC", "mark_price": 1.0, "oracle_price": 1.0,
                                               "open_interest": 3.0, "open_interest_usd": 3.0}, {})
    assert motif == "" and rec["ts_ms"] == T0 + H and rec["ironflow_horodatage_ms"] == T0
    assert X.convertir("open-interest", {"ts": T0, "coin": "BTC", "open_interest": -1.0}, {})[1] == \
        "open_interest_negatif_ou_absent"


def test_les_marches_spot_sans_nom_hyperliquid_sont_exclus_avec_leur_motif():
    assert X.convertir("liquidations", {"ts": T0, "market": "HYPE/USDC", "avg_price": 1.0, "size": 1.0}, {})[1] == \
        "liquidation_spot_sans_nom_hyperliquid"
    assert X.convertir("candles-1h", {"ts": T0, "coin": "X", "market_class": "spot"}, {})[1] == \
        "bougie_spot_sans_nom_hyperliquid"
    rec, _ = X.convertir("liquidations", {"ts": T0, "market": "xyz:GOLD-PERP", "avg_price": 1.0, "size": 2.0,
                                          "tx_hash": "0xh", "wallet": "0xw"}, {})
    assert rec["coin"] == "xyz:GOLD" and rec["stable_event_id"] == "0xh:0xw"
    rec, _ = X.convertir("funding", {"ts": T0, "coin": "cash:AMZN", "funding_rate": 1e-5, "premium": float("nan")}, {})
    assert rec["coin"] == "cash:AMZN" and rec["premium"] is None                     # jamais « cash:cash:AMZN », jamais NaN


def test_deja_au_coffre_et_premiere_observation_d_alina(tmp_path):
    _index(tmp_path, [
        _shard(tmp_path, "funding_history", "a__funding_1h", [{"coin": "BTC", "ts_ms": T0 + 50, "funding": 1e-5}]),
        _shard(tmp_path, "asset_ctx", "a__ctx", [{"coin": "BTC", "ts_ms": T0 + 5 * H, "mark": 1.0}]),
        _shard(tmp_path, "funding_history", "b__ext", [{"coin": "ETH", "ts_ms": T0, "funding": 1e-5}], **EXTERNE)])
    coffre = X.deja_au_coffre(tmp_path, depuis_ms=0)
    assert ("ETH", T0 // H) not in coffre["cles"]["funding"]                         # l'externe n'est pas « Alina »
    assert X.motif_deja_la("funding", {"coin": "BTC", "ts_ms": T0 - 20}, coffre) == "deja_au_coffre_alina"
    assert X.motif_deja_la("funding", {"coin": "BTC", "ts_ms": T0 + H}, coffre) == ""
    assert X.motif_deja_la("funding", {"coin": "BTC", "ts_ms": T0 + H + 9}, coffre) == "deja_au_coffre_alina"
    assert X.motif_deja_la("open-interest", {"ts_ms": T0 + 5 * H}, coffre) == "apres_la_premiere_observation_alina"
    assert X.motif_deja_la("open-interest", {"ts_ms": T0 + 4 * H}, coffre) == ""


# --------------------------------------------------------------------------- versement d'un fichier

def _parquet_funding(chemin: Path, lignes: list[tuple[int, str, float]]) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq

    chemin.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(pa.table({
        "timestamp": pa.array([t * 1000 for t, _, _ in lignes], pa.timestamp("us", tz="UTC")),
        "coin": [c for _, c, _ in lignes], "dex": [X.dex_de(c) for _, c, _ in lignes],
        "funding_rate": [v for _, _, v in lignes], "premium": [0.0] * len(lignes)}), chemin)


def _src(root: Path, lignes, version="v1") -> dict:
    cle = "funding/data/2026-10.parquet"
    _parquet_funding(root / X.IRON / cle, lignes)
    return {"jeu": "funding", "cle": cle, "chemin": root / X.IRON / cle, "version": version,
            "bornes": (min(t for t, _, _ in lignes), max(t for t, _, _ in lignes))}


def _vide() -> dict:
    return {"cles": {"funding": set(), "candles-1h": set(), "liquidations": set()},
            "debut_alina": {"asset_ctx": None, "trades_marche": None}}


def test_un_fichier_trop_mis_en_quarantaine_est_refuse_en_entier(tmp_path):
    lignes = [(T0 + i * H, "BTC", 1e-5) for i in range(500)] + [(T0 + 600 * H, "BTC", 5.0)]   # 1 sur 501 > 0,1 %
    src = _src(tmp_path, lignes)
    etat: dict = {}
    b = X.verser_un_fichier(tmp_path, src, {""}, _vide(), etat, depuis_ms=0, now_ms=T0 + 10_000 * H)
    assert b["statut"].startswith("REFUSE_QUARANTAINE") and b["quarantaine"] == {"taux_invalide": 1}
    assert not list((tmp_path / X.HISTOIRE).glob("externe_*")) and etat == {}         # rien de versé, rien de retenu


def test_un_horodatage_hors_des_bornes_du_manifeste_arrete_tout(tmp_path):
    src = _src(tmp_path, [(T0, "BTC", 1e-5), (T0 + H, "BTC", 1e-5)])
    src["bornes"] = (T0, T0)                                                           # unité ou fichier faux
    with pytest.raises(ValueError, match="hors des bornes"):
        X.verser_un_fichier(tmp_path, src, {""}, _vide(), {}, depuis_ms=0, now_ms=T0 + 100 * H)
    assert not list((tmp_path / X.HISTOIRE).glob("externe_*"))                         # ni ruban ni morceau


def test_un_groupe_recoupe_plus_tard_entre_sans_reverser_ce_qui_l_a_ete(tmp_path):
    lignes = [(T0 + i * H, c, 1e-5) for i in range(3) for c in ("BTC", "xyz:GOLD")]
    etat: dict = {}
    b1 = X.verser_un_fichier(tmp_path, _src(tmp_path, lignes, "v1"), {""}, _vide(), etat, 0, T0 + 100 * H)
    assert b1["ecrits"] == 3 and b1["exclus"] == {"groupe_non_recoupe": 3}
    # nouvelle version du fichier (une heure de plus), et le dex xyz est désormais recoupé
    lignes2 = lignes + [(T0 + 3 * H, c, 1e-5) for c in ("BTC", "xyz:GOLD")]
    b2 = X.verser_un_fichier(tmp_path, _src(tmp_path, lignes2, "v2"), {"", "xyz"}, _vide(), etat, 0, T0 + 100 * H)
    assert b2["statut"] == "VERSE" and b2["ecrits"] == 5                              # 4 xyz + 1 BTC nouvelle
    assert b2["exclus"] == {"deja_verse_version_precedente": 3}                        # les 3 BTC déjà versés
    rubans = sorted((tmp_path / X.HISTOIRE).glob("externe_ironflow_funding_1h_*.jsonl.gz"))
    assert len(rubans) == 2
    lus = [json.loads(l) for r in rubans for l in gzip.open(r, "rt", encoding="utf-8")]
    assert all(x["data_origin"] == C.ORIGINE_EXTERNE and x["causal_observation"] is False for x in lus)
    assert len({(x["coin"], x["ts_ms"]) for x in lus}) == len(lus) == 8                # aucun doublon


def test_le_plan_n_ecrit_rien(tmp_path):
    _src(tmp_path, [(T0, "BTC", 1e-5)])
    avant = sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*"))
    assert X.main(["--racine", str(tmp_path), "--plan"]) == 0
    assert sorted(str(p.relative_to(tmp_path)) for p in tmp_path.rglob("*")) == avant


# --------------------------------------------------------------------------- clôture : le coffre fait foi

def test_un_ruban_deja_au_coffre_n_est_jamais_reverse_meme_sans_ruban_ni_etat(tmp_path):
    src = _src(tmp_path, [(T0, "BTC", 1e-5), (T0 + H, "BTC", 2e-5)])
    nom = X.nom_du_ruban(src)
    shard = _shard(tmp_path, "funding_history", f"lot__{X.nom_sans_extension(nom)[:-6]}",
                   [{"coin": "BTC", "ts_ms": T0, "funding": 1e-5}], **EXTERNE)
    _index(tmp_path, [shard])
    coffre = {**_vide(), "rubans_scelles": X.rubans_scelles({"shards": [shard]})}
    b = X.verser_un_fichier(tmp_path, src, {""}, coffre, {}, 0, T0 + 100 * H)           # état perdu, ruban absent
    assert b["statut"] == "DEJA_AU_COFFRE" and not list((tmp_path / X.HISTOIRE).glob("externe_*"))


def test_la_purge_ne_retire_un_ruban_que_si_le_coffre_en_a_toutes_les_lignes(tmp_path):
    hist = tmp_path / X.HISTOIRE
    hist.mkdir(parents=True)
    complet, partiel, absent = (hist / f"externe_ironflow_funding_1h_{n:023d}.jsonl.gz" for n in (1, 2, 3))
    for chemin, n in ((complet, 2), (partiel, 3), (absent, 1)):
        with gzip.open(chemin, "wt", encoding="utf-8") as g:
            g.writelines(json.dumps({"coin": "BTC", "ts_ms": T0 + i}) + "\n" for i in range(n))
    shards = [{"famille": "funding_history", "provenance": C.ORIGINE_EXTERNE, "deposes": 2,
               "shard": f"runtime/coffre_certifie/local/shards/funding_history/lot__{X.nom_sans_extension(c.name)[:-6]}.jsonl.gz"}
              for c in (complet, partiel)]
    _index(tmp_path, shards)
    (tmp_path / X.VERROU).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / X.VERROU).write_text("{}", encoding="utf-8")
    assert X.purger_rubans_de_transit(tmp_path)["supprimes"] == 0 and complet.exists()   # certificateur actif : rien
    (tmp_path / X.VERROU).unlink()
    b = X.purger_rubans_de_transit(tmp_path)
    assert b["supprimes"] == 1 and not complet.exists()
    assert partiel.exists() and absent.exists()                                          # 3 lignes contre 2 ; pas au coffre
    assert "3 lignes contre 2" in b["gardes"][partiel.name] and b["gardes"][absent.name] == "pas encore au coffre"


def test_l_open_interest_sans_mark_ni_oracle_est_exclu_nomme_jamais_mis_en_quarantaine():
    assert X.convertir("open-interest", {"ts": T0, "coin": "xyz:A", "mark_price": None, "oracle_price": 0.0,
                                         "open_interest": 0.0}, {})[1] == "ni_mark_ni_oracle_jamais_recoupe"
