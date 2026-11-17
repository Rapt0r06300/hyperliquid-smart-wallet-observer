"""AUCUNE FAMILLE DU COFFRE NE DOIT RESTER EN LIMBE — ni consommée, ni exclue avec motif.

D'OÙ VIENT CE TEST (chantier 10 de l'audit du 15/11). « Présent dans le coffre » ne veut dire ni
« lu », ni « utilisé », ni « admissible à une preuve ». Le run du 12/11 comptait 13 354 078 lignes
de signaux LOCAL que le chemin principal comptait **puis jetait**. La matrice du 16/11 a trouvé
pire : `explorer_tx` (196 shards, 7 914 792 lignes) était indexée **sans aucun chemin de
chargement ni motif d'exclusion** — un troisième état, invisible.

Ce test interdit ce troisième état : toute famille est soit chargée pour une destination, soit
exclue avec un motif ÉCRIT. Une nouvelle famille qui apparaîtrait au coffre fera rougir ici.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
for chemin in (str(RACINE / "src"), str(RACINE / "tools")):
    if chemin not in sys.path:
        sys.path.insert(0, chemin)

import matrice_coffre as M                                            # noqa: E402
from hl_observer.backtesting import copy_vault_tier_local as TL       # noqa: E402

INDEX = RACINE / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"


def test_chaque_destination_connue_est_une_des_cinq():
    assert M.destination("fills_forward") == "REPLAY_PNL"
    assert M.destination("bbo") == "CARNETS" and M.destination("book_l2") == "CARNETS"
    assert M.destination("candle") == "CONTEXTE"
    assert M.destination("explorer_tx") == "EXCLUE_MOTIVEE"
    assert M.destination("une_famille_inventee") == "NON_CHARGEE"


def test_toute_famille_exclue_porte_un_motif_ECRIT():
    exclues = getattr(TL, "FAMILLES_EXCLUES_DU_REPLAY", {})
    assert exclues, "l'exclusion doit etre declaree dans le code, pas dans un commentaire"
    for famille, motif in exclues.items():
        assert isinstance(motif, str) and len(motif) > 40, (
            f"{famille} : un motif d'exclusion doit expliquer ET dire ce qui permettrait de "
            f"readmettre la famille (obtenu : {motif!r})")


def test_une_famille_ne_peut_etre_a_la_fois_chargee_et_exclue():
    exclues = set(getattr(TL, "FAMILLES_EXCLUES_DU_REPLAY", {}))
    chargees = TL._COFFRE_FAMILLES_FILLS | TL._COFFRE_FAMILLES_SIGNAUX | {"book_l2", "bbo"}
    assert not (exclues & chargees), f"contradiction : {exclues & chargees}"


@pytest.mark.skipif(not INDEX.exists(), reason="coffre LOCAL absent de ce clone")
def test_AUCUNE_famille_du_coffre_reel_n_est_en_limbe():
    """Le test qui compte : sur l'index RÉEL, zéro famille sans destination déclarée."""
    index = json.loads(INDEX.read_text(encoding="utf-8"))
    familles = {str(s.get("famille")) for s in index.get("shards") or []
                if isinstance(s, dict) and s.get("famille")}
    assert familles, "index sans famille : la matrice ne mesurerait rien"
    orphelines = sorted(f for f in familles if M.destination(f) == "NON_CHARGEE")
    assert orphelines == [], (
        f"familles indexees sans destination declaree : {orphelines}. Il faut soit les brancher "
        "avec un role, soit les inscrire dans FAMILLES_EXCLUES_DU_REPLAY avec un motif.")


# ───────── 17/11 : LA RÉCONCILIATION LOCAL -> SAFE, et le bloc SAFE qui annonçait zéro ─────────
#
# DÉFAUT DE CET OUTIL. L'ancien bloc lisait `lots` ou `shards` à la racine de `COFFRE_INDEX.json`.
# Ces clés n'existent pas : l'index range ses tiers sous `tiers`. La matrice annonçait donc
# **0 entrée SAFE pour 15 456 shards SAFE réels**. Mesure du 17/11 avec le bloc corrigé :
#
#   SAFE : 15 456 shards, 66 releases, dernier tag connu 2026-10-18
#   copy_vault_fills : 5 shards SAFE   contre   24 399 868 lignes LOCAL   (LOCAL +30,5 jours)
#   premier jour où une référence pré-signal est liable : 2026-11-13
#   fenêtre causale couverte par SAFE : False
#
# LOCAL sert à explorer ; seule une chaîne SAFE peut soutenir OOS, forward et PnL. Tant que la
# fenêtre causalement complète est postérieure au dernier tag SAFE, rien de ce que le labo y
# mesure n'est prouvable — et la matrice doit le dire, pas afficher un zéro.
def _index_deux_tiers(tmp_path, *, tags, par_famille, shards_safe=10):
    import json as _json
    chemin = tmp_path / M.COFFRE_INDEX
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(_json.dumps({
        "schema": "hypersmart.coffre_certifie.index.v1",
        "tiers": {"SAFE_CLOUD": {"present": True, "shards_safe": shards_safe, "n_releases": 3,
                                 "par_famille": par_famille, "derniers_tags": tags}},
    }), encoding="utf-8")


def test_le_bloc_SAFE_lit_les_TIERS_et_n_annonce_plus_zero(tmp_path):
    _index_deux_tiers(tmp_path, tags=["data-v2-campaign-copy-vault-e8-broad-2026101800-v8-u0"],
                      par_famille={"copy_vault_fills": 5, "copy_vault_l2": 14_642},
                      shards_safe=15_456)
    bloc = M.reconcilier_local_et_safe(tmp_path, {}, [])
    assert bloc["present"] is True
    assert bloc["shards_safe"] == 15_456, "l'ancien bloc rendait 0"
    assert bloc["correspondances"]["copy_vault_fills"]["shards_safe"] == 5
    assert bloc["dernier_tag_safe"] == "2026-10-18 00:00"


def test_l_avance_de_LOCAL_sur_SAFE_est_mesuree_en_jours(tmp_path):
    _index_deux_tiers(tmp_path, tags=["x-2026101800-v8"], par_famille={"copy_vault_l2": 1})
    safe_ms = M._date_du_tag_ms("x-2026101800-v8")
    local = {"book_l2": {"ts_max_ms": safe_ms + 30 * 86_400_000, "lignes_deposees": 1_000}}
    bloc = M.reconcilier_local_et_safe(tmp_path, local, [])
    c = bloc["correspondances"]["copy_vault_l2"]
    assert c["jours_local_en_avance_sur_safe"] == 30.0
    assert c["lignes_local"] == 1_000


def test_une_fenetre_causale_POSTERIEURE_au_dernier_tag_SAFE_n_est_pas_couverte(tmp_path):
    """Le fait qui borne toute preuve, rendu calculable au lieu d'être affirmé."""
    import gzip as _gzip
    import json as _json

    _index_deux_tiers(tmp_path, tags=["x-2026101800-v8"], par_famille={"copy_vault_l2": 1})
    jour_ms = M._date_du_tag_ms("x-2026111300-v8")          # 13/11 : apres le tag SAFE du 18/10
    rel = "runtime/coffre_certifie/local/shards/book_l2/liable.jsonl.gz"
    chemin = tmp_path / rel
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with _gzip.open(chemin, "wt", encoding="utf-8") as fh:
        for i in range(20):
            fh.write(_json.dumps({"coin": "BTC", "received_at_ms": jour_ms + i,
                                  "connection_id": "hl-1", "l2_gap_epoch": 0}) + "\n")
    shards = [{"famille": "book_l2", "shard": rel, "ts_max_ms": jour_ms + 20}]
    bloc = M.reconcilier_local_et_safe(tmp_path, {}, shards)
    assert bloc["liaison_pre_signal"]["premier_jour_liable"] == "2026-11-13"
    assert bloc["fenetre_causale_couverte_par_safe"] is False
    assert "campagne cloud" in bloc["condition_de_levee"]


def test_des_carnets_SANS_identite_de_connexion_ne_sont_PAS_liables(tmp_path):
    """Avant le 13/11, 0 % des lignes : aucun jour ne doit être déclaré liable."""
    import gzip as _gzip
    import json as _json

    rel = "runtime/coffre_certifie/local/shards/book_l2/ancien.jsonl.gz"
    chemin = tmp_path / rel
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with _gzip.open(chemin, "wt", encoding="utf-8") as fh:
        for i in range(20):
            fh.write(_json.dumps({"coin": "BTC", "received_at_ms": 1_790_000_000_000 + i}) + "\n")
    sonde = M.premier_jour_liable(
        tmp_path, [{"famille": "book_l2", "shard": rel, "ts_max_ms": 1_790_000_000_020}])
    assert sonde["premier_jour_liable"] is None
    assert sonde["jours_sondes"] == 1


def test_un_index_SANS_tier_SAFE_est_DIT_et_non_compte_pour_zero(tmp_path):
    import json as _json
    chemin = tmp_path / M.COFFRE_INDEX
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(_json.dumps({"schema": "x", "tiers": {}}), encoding="utf-8")
    bloc = M.reconcilier_local_et_safe(tmp_path, {}, [])
    assert bloc == {"present": False, "raison": "TIER_SAFE_CLOUD_ABSENT_DE_L_INDEX"}
    assert M.reconcilier_local_et_safe(tmp_path / "ailleurs", {}, [])["raison"] == "COFFRE_INDEX_ABSENT"
