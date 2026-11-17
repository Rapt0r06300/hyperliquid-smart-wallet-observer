"""LIRE UNE TRANCHE, PAS LE CORPUS — et ne jamais laisser entrer une valeur postérieure.

D'OÙ VIENT CE MODULE (chantier 10 de l'audit du 15/11). Le chemin principal du labo appelle
``_charger_tier_local(..., garder_signaux=False)`` : les 16 familles de contexte — dont
``funding_history`` et ``candle`` — sont COMPTÉES PUIS JETÉES. 13 354 078 lignes comptées pour rien
au run du 12/11.

Ce ``False`` n'est pas une erreur : garder 154 millions de lignes ferait sauter la machine, et la
règle est « on rétrécit, on ne crashe jamais ». Le défaut, c'est qu'il n'existait aucun moyen
intermédiaire. Mesure sur le coffre réel : `funding_history` pèse 3 285 943 lignes ; la tranche
BTC+ETH sur 30 jours en rend **1 440**, soit 2 282 fois moins, pour la même réponse.

Ces tests verrouillent les quatre garanties : as-of strictement antérieur, SHA obligatoire,
mémoire plafonnée ET dite, shard sans bornes jamais jeté en silence.
"""
from __future__ import annotations

import gzip
import hashlib
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting import coffre_tranches as T  # noqa: E402

JOUR = 86_400_000
T0 = 1_790_000_000_000


def _ecrire_shard(tmp_path: Path, nom: str, lignes: list[dict], *, famille="funding_history"):
    """Écrit un shard gzip + son entrée d'index, SHA compris, comme le fait le scelleur."""
    rel = f"runtime/coffre_certifie/local/shards/{famille}/{nom}.jsonl.gz"
    chemin = tmp_path / rel
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(chemin, "wt", encoding="utf-8") as fh:
        for l in lignes:
            fh.write(json.dumps(l) + "\n")
    champ = T.horloge_de(famille)
    instants = [l[champ] for l in lignes if champ in l]
    return {
        "famille": famille, "shard": rel,
        "sha256": hashlib.sha256(chemin.read_bytes()).hexdigest(),
        "octets": chemin.stat().st_size, "deposes": len(lignes),
        "coins": sorted({str(l.get("coin")) for l in lignes if l.get("coin")}),
        "ts_min_ms": min(instants) if instants else None,
        "ts_max_ms": max(instants) if instants else None,
    }


def _funding(coin, ts, taux=0.0001):
    return {"coin": coin, "ts_ms": ts, "funding": taux, "premium": -0.0004, "interval": "1h"}


# ─────────────── la sélection : viser juste sans rien jeter en silence ───────────────
def test_la_selection_ecarte_par_TEMPS_et_par_COIN():
    shards = [
        {"famille": "funding_history", "shard": "a", "coins": ["BTC"], "ts_min_ms": T0, "ts_max_ms": T0 + JOUR},
        {"famille": "funding_history", "shard": "b", "coins": ["ETH"], "ts_min_ms": T0, "ts_max_ms": T0 + JOUR},
        {"famille": "funding_history", "shard": "c", "coins": ["BTC"], "ts_min_ms": T0 + 10 * JOUR,
         "ts_max_ms": T0 + 11 * JOUR},
        {"famille": "candle", "shard": "d", "coins": ["BTC"], "ts_min_ms": T0, "ts_max_ms": T0 + JOUR},
    ]
    sel = T.selectionner(shards, famille="funding_history", coins=["BTC"],
                         debut_ms=T0, fin_ms=T0 + JOUR)
    assert [s["shard"] for s in sel["retenus"]] == ["a"]
    assert sel["ecartes_coin"] == 1 and sel["ecartes_temps"] == 1
    assert sel["sans_bornes"] == []


def test_un_shard_SANS_BORNES_n_est_jamais_jete_en_silence():
    """Cas réel : 171 shards `position` et 192 `trades_marche` scellés avant le correctif
    d'horloge du 16/11 n'ont pas de `ts_min_ms`. On ne peut pas prouver qu'ils sont hors fenêtre :
    l'appelant doit SAVOIR qu'ils existent."""
    shards = [{"famille": "position", "shard": "vieux", "coins": ["BTC"], "octets": 1234}]
    sel = T.selectionner(shards, famille="position", coins=["BTC"], debut_ms=T0, fin_ms=T0 + JOUR)
    assert sel["retenus"] == []
    assert [s["shard"] for s in sel["sans_bornes"]] == ["vieux"]
    assert sel["octets_sans_bornes"] == 1234


def test_un_shard_sans_liste_de_coins_reste_candidat():
    """Absence d'information n'est pas absence du coin : on ne l'écarte pas sur une supposition."""
    shards = [{"famille": "funding_history", "shard": "x", "coins": [],
               "ts_min_ms": T0, "ts_max_ms": T0 + JOUR}]
    sel = T.selectionner(shards, famille="funding_history", coins=["BTC"], debut_ms=T0, fin_ms=T0 + JOUR)
    assert len(sel["retenus"]) == 1


# ─────────────── le chargement : vérifié, borné, et honnête sur ce qu'il refuse ───────────────
def test_la_tranche_ne_charge_que_la_fenetre_et_les_coins_demandes(tmp_path):
    e = _ecrire_shard(tmp_path, "s1", [
        _funding("BTC", T0), _funding("BTC", T0 + JOUR), _funding("ETH", T0),
        _funding("BTC", T0 + 10 * JOUR),
    ])
    tr = T.charger(tmp_path, [e], famille="funding_history", coins=["BTC"],
                   debut_ms=T0, fin_ms=T0 + 2 * JOUR)
    assert tr["n"] == 2 and tr["shards_refuses"] == [] and tr["tronque"] is False
    assert [l["ts_ms"] for l in tr["lignes"]] == [T0, T0 + JOUR]


def test_un_SHA_divergent_refuse_le_shard_ENTIER(tmp_path):
    e = _ecrire_shard(tmp_path, "s2", [_funding("BTC", T0)])
    e["sha256"] = "0" * 64
    tr = T.charger(tmp_path, [e], famille="funding_history")
    assert tr["n"] == 0 and tr["shards_refuses"] == [{"shard": e["shard"], "motif": "SHA_DIVERGENT"}]


def test_un_SHA_absent_est_refuse_aussi(tmp_path):
    e = _ecrire_shard(tmp_path, "s3", [_funding("BTC", T0)])
    e.pop("sha256")
    assert T.charger(tmp_path, [e], famille="funding_history")["shards_refuses"][0]["motif"] == "SHA_ABSENT"


def test_un_chemin_HORS_du_coffre_est_refuse(tmp_path):
    e = _ecrire_shard(tmp_path, "s4", [_funding("BTC", T0)])
    e["shard"] = "../../ailleurs.jsonl.gz"
    assert T.charger(tmp_path, [e], famille="funding_history")["shards_refuses"][0]["motif"] == "HORS_COFFRE"


def test_la_troncature_est_DITE_jamais_silencieuse(tmp_path):
    e = _ecrire_shard(tmp_path, "s5", [_funding("BTC", T0 + i) for i in range(50)])
    tr = T.charger(tmp_path, [e], famille="funding_history", max_lignes=10)
    assert tr["n"] == 10 and tr["tronque"] is True, (
        "mesurer sur un echantillon tronque sans le savoir, c'est mesurer n'importe quoi")


def test_un_shard_absent_du_disque_est_un_refus_motive(tmp_path):
    e = _ecrire_shard(tmp_path, "s6", [_funding("BTC", T0)])
    (tmp_path / e["shard"]).unlink()
    assert T.charger(tmp_path, [e], famille="funding_history")["shards_refuses"][0]["motif"] == "ABSENT_DU_DISQUE"


# ─────────────── la jointure as-of : strictement avant, sinon rien ───────────────
def test_la_jointure_prend_la_DERNIERE_valeur_connue_avant_l_evenement():
    serie = [_funding("BTC", T0), _funding("BTC", T0 + 3_600_000, taux=0.0002)]
    evts = [{"coin": "BTC", "signal_ms": T0 + 5_000_000}]
    r = T.jointure_as_of(evts, serie, horloge_evenement="signal_ms", horloge_serie="ts_ms")
    assert r[0]["contexte"]["funding"] == 0.0002 and r[0]["age_ms"] == 5_000_000 - 3_600_000


def test_une_valeur_POSTERIEURE_ne_peut_jamais_entrer():
    serie = [_funding("BTC", T0 + 10_000, taux=0.9)]
    evts = [{"coin": "BTC", "signal_ms": T0}]
    r = T.jointure_as_of(evts, serie, horloge_evenement="signal_ms", horloge_serie="ts_ms")
    assert r[0]["contexte"] is None, "c'est toute la difference entre une mesure et une fuite"


def test_une_EGALITE_a_la_milliseconde_est_refusee():
    """Même règle que la liaison du carnet de référence : dans la même milliseconde, l'ordre
    des deux réceptions n'est pas observable."""
    serie = [_funding("BTC", T0)]
    r = T.jointure_as_of([{"coin": "BTC", "signal_ms": T0}], serie,
                         horloge_evenement="signal_ms", horloge_serie="ts_ms")
    assert r[0]["contexte"] is None


def test_sans_contexte_anterieur_on_rend_None_et_jamais_un_zero():
    r = T.jointure_as_of([{"coin": "BTC", "signal_ms": T0}], [],
                         horloge_evenement="signal_ms", horloge_serie="ts_ms")
    assert r[0]["contexte"] is None and r[0]["age_ms"] is None


def test_les_coins_ne_se_contaminent_pas():
    serie = [_funding("ETH", T0, taux=0.5)]
    r = T.jointure_as_of([{"coin": "BTC", "signal_ms": T0 + 10_000}], serie,
                         horloge_evenement="signal_ms", horloge_serie="ts_ms")
    assert r[0]["contexte"] is None, "le funding d'ETH n'est pas celui de BTC"


# ─────────────── l'entrée en un appel ───────────────
def test_contexte_as_of_ne_regarde_JAMAIS_apres_le_dernier_evenement(tmp_path):
    e = _ecrire_shard(tmp_path, "s7", [
        _funding("BTC", T0 - JOUR, taux=0.1), _funding("BTC", T0 + 10 * JOUR, taux=0.9),
    ])
    out = T.contexte_as_of(tmp_path, [e], [{"coin": "BTC", "signal_ms": T0}],
                           famille="funding_history")
    assert out["raison"] == "OK"
    assert out["couverture"] == {"evenements": 1, "avec_contexte": 1, "sans_contexte": 0}
    assert out["resultats"][0]["contexte"]["funding"] == 0.1
    assert out["fenetre_ms"][1] == T0, "la fenetre ne doit pas depasser le dernier evenement"


def test_contexte_as_of_publie_ce_qu_il_n_a_pas_pu_lire(tmp_path):
    e = _ecrire_shard(tmp_path, "s8", [_funding("BTC", T0 - 1)])
    e["sha256"] = "f" * 64
    out = T.contexte_as_of(tmp_path, [e], [{"coin": "BTC", "signal_ms": T0}],
                           famille="funding_history")
    assert out["couverture"]["sans_contexte"] == 1
    assert out["tranche"]["shards_refuses"][0]["motif"] == "SHA_DIVERGENT", (
        "une etude doit pouvoir dire sur quoi elle a mesure, ET ce qu'elle n'a pas pu lire")


def test_aucun_evenement_horodate_ne_declenche_aucune_lecture(tmp_path):
    out = T.contexte_as_of(tmp_path, [], [{"coin": "BTC"}], famille="funding_history")
    assert out["raison"] == "AUCUN_EVENEMENT_HORODATE" and out["tranche"]["shards_lus"] == 0


# ─────────────── le catalogue publié par le chemin principal du labo ───────────────
def test_le_catalogue_dit_l_etat_EXACT_de_chaque_famille(tmp_path):
    """« tranchable=True » pour 4 shards sur 175 serait un demi-mensonge.

    `position` avait 171 de ses 175 shards sans bornes de temps (scellés avant le correctif
    d'horloge du 16/11). Un booléen aurait laissé croire la famille utilisable ; l'état à trois
    valeurs dit la vérité, et la part le quantifie.
    """
    import json as _json

    from hl_observer.backtesting.copy_vault_contexte_tranchable import (
        catalogue_tranchable as _catalogue_tranchable,
    )

    index = tmp_path / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(_json.dumps({"shards": [
        {"famille": "funding_history", "shard": "a", "deposes": 10, "octets": 1,
         "ts_min_ms": T0, "ts_max_ms": T0 + 1},
        {"famille": "position", "shard": "b", "deposes": 5, "octets": 1},
        {"famille": "position", "shard": "c", "deposes": 5, "octets": 1,
         "ts_min_ms": T0, "ts_max_ms": T0 + 1},
        {"famille": "trades_marche", "shard": "d", "deposes": 7, "octets": 1},
    ]}), encoding="utf-8")

    cat = _catalogue_tranchable(tmp_path)
    assert cat["disponible"] is True
    assert cat["familles"]["funding_history"]["tranchable"] == "COMPLETE"
    assert cat["familles"]["position"]["tranchable"] == "PARTIELLE"
    assert cat["familles"]["position"]["part_tranchable"] == 0.5
    assert cat["familles"]["trades_marche"]["tranchable"] == "AUCUNE", (
        "aucun shard borne : la famille n'est pas decoupable par le temps, et il faut le DIRE")
    assert "contexte_as_of" in cat["appel"], "le catalogue doit dire COMMENT prendre la tranche"


def test_un_index_illisible_ne_fait_pas_planter_le_labo(tmp_path):
    from hl_observer.backtesting.copy_vault_contexte_tranchable import (
        catalogue_tranchable as _catalogue_tranchable,
    )

    assert _catalogue_tranchable(tmp_path) == {"disponible": False, "raison": "LOCAL_INDEX_ILLISIBLE"}
    index = tmp_path / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text("pas du json", encoding="utf-8")
    assert _catalogue_tranchable(tmp_path)["disponible"] is False


# ─────────────── AUCUNE famille du coffre ne doit rester silencieuse ───────────────
def _familles_consommees_par_les_etudes() -> dict[str, set[str]]:
    """Les familles réellement lues par `tools/etude_copiabilite.py`, extraites de l'AST.

    On lit le CODE, pas une liste tenue à la main : une étude qui cesse de lire une famille le
    dira ici tout seul.
    """
    import ast
    import collections

    arbre = ast.parse((RACINE / "tools" / "etude_copiabilite.py").read_text(encoding="utf-8"))
    consommateurs: dict[str, set[str]] = collections.defaultdict(set)

    class Visiteur(ast.NodeVisitor):
        def __init__(self):
            self.fonction = "<module>"

        def visit_FunctionDef(self, node):
            avant, self.fonction = self.fonction, node.name
            self.generic_visit(node)
            self.fonction = avant

        def visit_Call(self, node):
            nom = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
            if nom == "select_shards":
                args = list(node.args) + [k.value for k in node.keywords if k.arg == "wanted"]
                for arg in args:
                    if isinstance(arg, ast.Dict):
                        for cle in arg.keys:
                            if isinstance(cle, ast.Constant) and isinstance(cle.value, str):
                                consommateurs[cle.value].add(self.fonction)
            self.generic_visit(node)

    Visiteur().visit(arbre)
    return dict(consommateurs)


def test_les_etudes_lisent_bien_les_familles_qu_on_croit():
    """Garde-fou de la méthode : si l'extraction cassait, le test suivant deviendrait vide."""
    consommees = _familles_consommees_par_les_etudes()
    assert len(consommees) >= 12, f"extraction suspecte : {sorted(consommees)}"
    assert "funding_history" in consommees and "candle" in consommees
    assert "position" in consommees, (
        "la famille `position` (879 541 lignes, 54 vaults, 179 coins) a ete branchee le 16/11 "
        "dans run_positions et run_replication_350 : si elle disparait, l'hypothese des "
        "operateurs lents reperd sa seconde source")


def test_AUCUNE_famille_du_coffre_reel_n_est_silencieuse():
    """LE test du chantier 10 : consommée, exclue avec motif, ou inscrite au backlog. Jamais rien.

    Au run du 12/11, dix familles étaient comptées sans que personne sache qu'elles dormaient.
    Trois états déclarés rendent ce silence impossible.
    """
    import json as _json

    from hl_observer.backtesting import copy_vault_tier_local as TL

    index = RACINE / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    if not index.exists():
        import pytest as _pytest
        _pytest.skip("coffre LOCAL absent de ce clone")
    familles = {str(s.get("famille")) for s in
                _json.loads(index.read_text(encoding="utf-8")).get("shards") or []
                if isinstance(s, dict) and s.get("famille")}
    consommees = set(_familles_consommees_par_les_etudes())
    consommees |= TL._COFFRE_FAMILLES_FILLS | TL._COFFRE_FAMILLES_SIGNAUX | {"book_l2", "bbo"}
    exclues = set(TL.FAMILLES_EXCLUES_DU_REPLAY)
    a_role = set(getattr(TL, "FAMILLES_A_ROLE_MESURE", {}))

    silencieuses = sorted(familles - consommees - exclues - a_role)
    assert silencieuses == [], (
        f"familles sans aucun etat declare : {silencieuses}. Il faut soit les brancher, soit les "
        "inscrire dans FAMILLES_EXCLUES_DU_REPLAY avec un motif, soit dans FAMILLES_A_ROLE_MESURE "
        "avec la fonction qui mesure leur role.")


def test_chaque_famille_a_role_mesure_pointe_vers_une_VRAIE_fonction_de_mesure():
    """17/11 : l'etat d'attente `A_CABLER` est remplace par un role MESURE.

    Une fiche qui nommerait une mesure inexistante serait un etat d'attente deguise : la fonction
    doit s'importer, et chaque fiche doit dire ce que la famille ne fait PAS.
    """
    from hl_observer.backtesting import copy_vault_roles_familles as ROLES
    from hl_observer.backtesting import copy_vault_tier_local as TL

    registre = getattr(TL, "FAMILLES_A_ROLE_MESURE", {})
    assert registre, "un registre vide cacherait a nouveau les familles qui dorment"
    assert not hasattr(TL, "FAMILLES_A_CABLER"), "l'etat d'attente ne doit pas revenir"
    for famille, fiche in registre.items():
        assert isinstance(fiche, dict), famille
        assert callable(getattr(ROLES, str(fiche.get("mesure")), None)), (
            f"{famille} : la mesure `{fiche.get('mesure')}` n'existe pas dans "
            "copy_vault_roles_familles")
        assert str(fiche.get("role") or "").strip(), famille
        assert len(str(fiche.get("limite") or "")) > 30, (
            f"{famille} : il faut dire ce que ce role ne fait PAS")


def test_une_famille_ne_peut_pas_etre_a_la_fois_exclue_et_a_role_mesure():
    from hl_observer.backtesting import copy_vault_tier_local as TL

    exclues = set(TL.FAMILLES_EXCLUES_DU_REPLAY)
    a_role = set(getattr(TL, "FAMILLES_A_ROLE_MESURE", {}))
    assert not (exclues & a_role), f"contradiction : {exclues & a_role}"


def test_les_familles_CROSS_VENUE_sont_exclues_par_le_SCOPE_et_non_oubliees():
    """La constitution ferme Cross-Venue : les brancher serait rouvrir un scope par la bande."""
    from hl_observer.backtesting import copy_vault_tier_local as TL

    for famille in ("venue_book", "venue_dispersion"):
        motif = TL.FAMILLES_EXCLUES_DU_REPLAY.get(famille, "")
        assert "DISABLED_BY_SCOPE" in motif, f"{famille} : {motif!r}"


# ─────────── 16/11 : L'HORLOGE MANQUANTE, un trou qui rendait 37 M lignes invisibles ───────────
def test_CHAQUE_famille_du_coffre_a_une_horloge_DECLAREE():
    """Une famille sans horloge déclarée retombait sur ``ts_ms`` — qu'elle n'a pas forcément.

    Mesure du 16/11 : la table ne couvrait que 9 familles sur 23. ``bbo`` (30 392 168 lignes) et
    ``book_l2`` (6 956 689 lignes) n'ont PAS de champ ``ts_ms`` : ``charger()`` ignorait donc
    chacune de leurs lignes et rendait ``n=0`` sans motif. Les deux familles les plus lourdes du
    replay étaient invisibles à l'outil censé les rendre exploitables.
    """
    attendues = {
        "fills_forward", "fills_backfill", "snapshot", "book_l2", "bbo", "trades_marche",
        "candle", "funding_history", "asset_ctx", "allmids", "position", "liquidation",
        "overshoot", "venue_book", "venue_dispersion", "explorer_tx", "leader_orders",
        "vault_ledger", "vault_portfolio", "micro_bbo", "micro_l2", "micro_trades",
    }
    manquantes = sorted(attendues - set(T.HORLOGE_PAR_FAMILLE))
    assert manquantes == [], f"familles sans horloge declaree : {manquantes}"
    # et les trois qui n'ont PAS ts_ms doivent porter la leur, pas le repli
    assert T.HORLOGE_PAR_FAMILLE["book_l2"] == "exchange_ts_ms"
    assert T.HORLOGE_PAR_FAMILLE["bbo"] == "recv_wall_ts_ms"
    assert T.HORLOGE_PAR_FAMILLE["venue_book"] == "snapshot_ts_ms"


def test_une_tranche_de_CARNETS_rend_ses_lignes_et_non_zero(tmp_path):
    """Le test qui aurait attrapé le défaut : un carnet n'a pas de ``ts_ms``."""
    carnets = [{"coin": "BTC", "exchange_ts_ms": T0 + i * 1_000,
                "received_at_ms": T0 + i * 1_000 + 20,
                "bids5": [[1.0, 2.0]], "asks5": [[1.1, 2.0]]} for i in range(5)]
    entree = _ecrire_shard(tmp_path, "l2", carnets, famille="book_l2")
    tranche = T.charger(tmp_path, [entree], famille="book_l2",
                        debut_ms=T0, fin_ms=T0 + 10_000)
    assert tranche["n"] == 5, "les carnets etaient jetes en silence avant le correctif du 16/11"
    assert tranche["horloge"] == "exchange_ts_ms"
    assert tranche["lignes_sans_horloge"] == 0


def test_une_ligne_NON_DATABLE_est_comptee_jamais_jetee_en_silence(tmp_path):
    lignes = [_funding("BTC", T0), {"coin": "BTC", "funding": 0.01}, _funding("BTC", T0 + 1_000)]
    entree = _ecrire_shard(tmp_path, "mixte", lignes, famille="funding_history")
    tranche = T.charger(tmp_path, [entree], famille="funding_history")
    assert tranche["n"] == 2
    assert tranche["lignes_sans_horloge"] == 1, (
        "une ligne sans horloge ne doit JAMAIS etre confondue avec une ligne hors fenetre")


def test_le_repli_d_horloge_est_AUTORISE_par_famille_et_par_elle_seule():
    """Le scelleur écrit ``exchange_ts_ms or received_at_ms`` pour ``trades_marche`` : idem ici."""
    assert T.instant_de({"exchange_ts_ms": 5, "received_at_ms": 9}, "trades_marche") == 5
    assert T.instant_de({"received_at_ms": 9}, "trades_marche") == 9
    # ailleurs, aucun repli : une ligne sans son horloge reste non datable
    assert T.instant_de({"received_at_ms": 9}, "funding_history") is None


def test_le_FLUX_ne_garde_rien_en_memoire_et_rend_les_memes_lignes(tmp_path):
    """``flux()`` est la primitive qui permet un corpus plus grand que la RAM."""
    lignes = [_funding("BTC", T0 + i * 1_000) for i in range(50)]
    entree = _ecrire_shard(tmp_path, "flux", lignes, famille="funding_history")
    compteurs: dict = {}
    vues = 0
    for _ in T.flux(tmp_path, [entree], famille="funding_history", compteurs=compteurs):
        vues += 1
    assert vues == 50
    assert compteurs["shards_lus"] == 1
    assert compteurs["shards_refuses"] == []
    # le flux et la version materialisee doivent voir EXACTEMENT la meme chose
    assert T.charger(tmp_path, [entree], famille="funding_history")["n"] == vues


def test_un_SHA_DIVERGENT_refuse_le_shard_ENTIER_dans_le_flux(tmp_path):
    lignes = [_funding("BTC", T0 + i * 1_000) for i in range(10)]
    entree = _ecrire_shard(tmp_path, "altere", lignes, famille="funding_history")
    entree = {**entree, "sha256": "f" * 64}
    compteurs: dict = {}
    assert list(T.flux(tmp_path, [entree], famille="funding_history", compteurs=compteurs)) == []
    assert compteurs["shards_refuses"] == [{"shard": entree["shard"], "motif": "SHA_DIVERGENT"}]


def test_le_catalogue_DIT_quelle_part_du_corpus_une_seule_charge_voit(tmp_path):
    """« Tronqué » reste une abstraction tant qu'on n'écrit pas la fraction réellement vue.

    Mesure sur le coffre réel du 16/11 : une charge de 8 000 000 de lignes voit **4,91 %** des
    163 053 257 lignes indexées, et il faut **21 galeries** pour tout voir. Un run qui écrit un
    verdict doit publier ce chiffre, sinon personne ne sait sur quoi le verdict porte.
    """
    import json as _json

    from hl_observer.backtesting.copy_vault_contexte_tranchable import (
        catalogue_tranchable as _catalogue_tranchable,
    )

    entrees = []
    for lot in range(4):
        lignes = [_funding("BTC", T0 + lot * JOUR + i * 1_000) for i in range(25)]
        entrees.append(_ecrire_shard(tmp_path, f"c{lot}", lignes, famille="funding_history"))
    index = tmp_path / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(_json.dumps({"schema": "x", "tier": "LOCAL", "shards": entrees}),
                     encoding="utf-8")

    catalogue = _catalogue_tranchable(tmp_path)
    fouille = catalogue["fouille"]
    assert fouille["disponible"] is True
    assert fouille["lignes_indexees"] == 100
    assert fouille["couverture_complete"] is True
    assert fouille["galeries_pour_tout_voir"] >= 1
    # 100 lignes tiennent dans n'importe quel budget : une seule charge voit TOUT, et le dit
    assert fouille["part_vue_en_une_charge"] == 1.0


def test_un_index_ILLISIBLE_ne_fabrique_pas_un_catalogue_optimiste(tmp_path):
    from hl_observer.backtesting.copy_vault_contexte_tranchable import (
        catalogue_tranchable as _catalogue_tranchable,
    )

    assert _catalogue_tranchable(tmp_path)["raison"] == "LOCAL_INDEX_ILLISIBLE"
