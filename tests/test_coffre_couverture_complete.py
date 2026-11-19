"""Tout doit entrer au coffre, et toujours par le certificateur (19/11/2026).

Le labo et le moteur ne lisent QUE le coffre certifié : une donnée écrite mais non scellée leur
est invisible, quelle que soit sa taille. Deux trous réels ont été trouvés et sont gardés ici.

1. ``--tout`` scellait MOINS que le mode par défaut. Le mode par défaut parcourt
   ``DOSSIERS_COLLECTE`` (``runtime/data``, ``runtime/history``, ``runtime/research_lab/data``),
   tandis que ``--tout`` partait en scan récursif en élaguant ``_EXCLUS``, qui contient
   ``history`` ET ``research_lab``. Les bougies de backfill et la microstructure n'entraient donc
   jamais au coffre par ``--tout`` — l'option qu'on lance justement en croyant « tout certifier ».

2. Le rattrapage mesurait ce qui lui manque depuis son seul fichier d'état, posé dans
   ``runtime/data`` — le dossier que le lanceur ARCHIVE à chaque démarrage de session. Cet état
   était donc un point unique de défaillance : disparu, la passe croyait ne rien détenir. Le
   coffre, magasin durable, est désormais recoupé.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]


def _mod(nom: str):
    spec = importlib.util.spec_from_file_location(nom, RACINE / "tools" / ("%s.py" % nom))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


SC = _mod("sceller_coffre_local")
BC = _mod("backfill_candles_vaults")

#: Un vrai nom de ruban par dossier de collecte. Tous reconnus par ``detecter_famille``.
RUBANS = {
    Path("runtime") / "data": "bbo_tape.jsonl",
    Path("runtime") / "history": "candles_1h.jsonl",
    Path("runtime") / "research_lab" / "data": "micro_bbo.jsonl",
}


def _arbre_de_collecte(racine: Path) -> list[Path]:
    """Écrit un ruban non vide dans chacun des dossiers de collecte."""
    ecrits = []
    for dossier, nom in RUBANS.items():
        (racine / dossier).mkdir(parents=True, exist_ok=True)
        chemin = racine / dossier / nom
        chemin.write_text('{"coin":"BTC","t":1}\n', encoding="utf-8")
        ecrits.append(chemin)
    return ecrits


# --------------------------------------------------------------------------- certificateur


def test_les_trois_dossiers_de_collecte_sont_des_rubans_reconnus() -> None:
    """Si un de ces noms cessait d'être reconnu, son flux n'entrerait plus au coffre."""
    for nom in RUBANS.values():
        assert SC.detecter_famille(nom) is not None, nom


def test_tout_est_un_sur_ensemble_strict_du_defaut(tmp_path: Path) -> None:
    _arbre_de_collecte(tmp_path)
    defaut = SC.collecter_fichiers(tmp_path, tout=False)
    tout = SC.collecter_fichiers(tmp_path, tout=True)
    cles_defaut = {SC._cle_fichier(c) for c, _f, _s in defaut}
    cles_tout = {SC._cle_fichier(c) for c, _f, _s in tout}
    manquants = sorted(cles_defaut - cles_tout)
    assert not manquants, f"--tout perd des fichiers que le defaut trouve : {manquants}"
    assert len(cles_defaut) == len(RUBANS)


def test_history_et_microstructure_entrent_bien_par_tout(tmp_path: Path) -> None:
    """Garde directe du trou n°1 : ces deux dossiers étaient élagués par ``_EXCLUS``."""
    _arbre_de_collecte(tmp_path)
    vus = {SC._cle_fichier(c) for c, _f, _s in SC.collecter_fichiers(tmp_path, tout=True)}
    for dossier in (Path("runtime") / "history", Path("runtime") / "research_lab" / "data"):
        attendu = SC._cle_fichier(tmp_path / dossier / RUBANS[dossier])
        assert attendu in vus, f"{dossier} reste invisible en mode --tout"


def test_tout_ne_compte_aucun_fichier_deux_fois(tmp_path: Path) -> None:
    """``--tout`` redescend dans ``runtime/data`` : sceller deux fois est du travail perdu."""
    _arbre_de_collecte(tmp_path)
    tout = SC.collecter_fichiers(tmp_path, tout=True)
    cles = [SC._cle_fichier(c) for c, _f, _s in tout]
    assert len(cles) == len(set(cles)), "doublons dans l'inventaire --tout"


# --------------------------------------------------------------------------- recoupement coffre


def _manifeste(racine: Path, entrees: list[dict]) -> Path:
    dossier = racine / BC.MANIFESTES_COFFRE
    dossier.mkdir(parents=True, exist_ok=True)
    chemin = dossier / "20261119T000000Z_test.json"
    chemin.write_text(json.dumps({"schema": "test", "fichiers": entrees}), encoding="utf-8")
    return chemin


def test_la_serie_vient_du_tag_pas_de_la_famille(tmp_path: Path) -> None:
    """La famille ``candle`` ne distingue PAS 5m de 1h : c'est le tag qui porte l'intervalle."""
    _manifeste(tmp_path, [
        {"famille": "candle", "source_tag": "REST_BACKFILL_1H",
         "source": r"runtime\history\candles_1h.jsonl", "coins": {"BTC": 3}},
        {"famille": "candle", "source_tag": "REST_BACKFILL_5M",
         "source": r"runtime\history\candles_5m.jsonl", "coins": {"ETH": 7}},
    ])
    couverture = BC.coins_du_coffre(tmp_path)
    assert couverture.get("1h") == {"BTC"}
    assert couverture.get("5m") == {"ETH"}


def test_le_chemin_source_sert_de_repli_sans_tag(tmp_path: Path) -> None:
    _manifeste(tmp_path, [
        {"famille": "candle", "source": r"runtime\history\candles_4h.jsonl", "coins": {"SOL": 1}},
    ])
    assert BC.coins_du_coffre(tmp_path).get("4h") == {"SOL"}


def test_un_flux_etranger_au_backfill_est_ignore(tmp_path: Path) -> None:
    """Le coffre contient 22 familles ; seules celles de cette passe comptent ici."""
    _manifeste(tmp_path, [
        {"famille": "bbo", "source_tag": "BBO_TAPE",
         "source": r"runtime\data\bbo_tape.jsonl", "coins": {"BTC": 900}},
    ])
    assert BC.coins_du_coffre(tmp_path) == {}


def test_un_manifeste_illisible_ne_casse_pas_la_passe(tmp_path: Path) -> None:
    dossier = tmp_path / BC.MANIFESTES_COFFRE
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "20261119T000001Z_casse.json").write_text("{ pas du json", encoding="utf-8")
    _manifeste(tmp_path, [
        {"famille": "funding_history", "source_tag": "REST_FUNDING_HISTORY",
         "source": r"runtime\history\funding_1h.jsonl", "coins": {"BTC": 5}},
    ])
    assert BC.coins_du_coffre(tmp_path).get(BC.SERIE_FUNDING) == {"BTC"}


def test_coffre_absent_ne_leve_pas(tmp_path: Path) -> None:
    assert BC.coins_du_coffre(tmp_path) == {}


def test_le_coffre_rend_l_univers_quand_l_etat_a_disparu(tmp_path: Path) -> None:
    """LE point unique de défaillance : sans cet appel, l'univers tombait à zéro coin."""
    _manifeste(tmp_path, [
        {"famille": "candle", "source_tag": "REST_BACKFILL_1H",
         "source": r"runtime\history\candles_1h.jsonl", "coins": {"BTC": 3, "ETH": 3}},
    ])
    assert not (tmp_path / BC.ETAT).exists()
    assert sorted(BC.coins_deja_commences(tmp_path)) == ["BTC", "ETH"]


def test_le_coffre_n_abrege_jamais_l_univers(tmp_path: Path) -> None:
    """Un coin connu de l'état mais absent du coffre doit rester suivi."""
    (tmp_path / BC.ETAT).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / BC.ETAT).write_text(json.dumps({
        "_schema": BC.SCHEMA_ETAT,
        "intervalles": {BC.SERIE_FUNDING: {"VIEUXCOIN": [1, 2]}},
    }), encoding="utf-8")
    _manifeste(tmp_path, [
        {"famille": "candle", "source_tag": "REST_BACKFILL_1H",
         "source": r"runtime\history\candles_1h.jsonl", "coins": {"BTC": 3}},
    ])
    univers = sorted(BC.coins_deja_commences(tmp_path))
    assert univers == ["BTC", "VIEUXCOIN"], univers


def test_le_recoupement_ne_rend_aucune_borne_de_temps(tmp_path: Path) -> None:
    """Les bornes du manifeste valent pour le shard ENTIER, donc pour tous ses coins à la fois.

    S'en servir pour déclarer un coin « à jour » pourrait sauter un vrai trou. Retélécharger est
    idempotent ; un trou sauté ne se voit jamais. Le recoupement ne rend donc que des coins.
    """
    _manifeste(tmp_path, [
        {"famille": "candle", "source_tag": "REST_BACKFILL_1H",
         "source": r"runtime\history\candles_1h.jsonl", "coins": {"BTC": 3},
         "ts_min_ms": 1_000, "ts_max_ms": 9_000},
    ])
    for valeur in BC.coins_du_coffre(tmp_path).values():
        assert isinstance(valeur, set)
        assert all(isinstance(x, str) for x in valeur)
