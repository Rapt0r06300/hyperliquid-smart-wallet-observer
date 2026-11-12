"""C110 / C82 / C83 — savoir en QUELQUES MINUTES si la collecte sera mesurable, pas en six jours.

Jusqu'ici la boucle de retour était : collecter des jours → certifier → lancer le labo (dizaines de
minutes, 16 Go) → découvrir que **77 008 signaux sur 98 138** étaient inexploitables faute de carnet
dans les 30 s précédant le signal. Six jours pour apprendre un échec visible immédiatement.

Cette jauge fait le constat directement sur les rubans. Ces tests verrouillent :

1. les TROIS carnets exigés (référence / entrée / sortie) et l'identité de connexion continue ;
2. un motif PRÉCIS par manque (on doit savoir quoi corriger, pas seulement que c'est cassé) ;
3. les seuils VIENNENT DU MOTEUR (une jauge qui dériverait des règles réelles mentirait) ;
4. l'honnêteté de portée : conditions nécessaires, pas une promesse d'exécution.
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.backtesting.copy_vault_executable import (  # noqa: E402
    COPY_DELAY_MS,
    HORIZONS_MS,
    MAX_TARGET_LAG_MS,
)
from hl_observer.collection import reconciliation_carnets as R  # noqa: E402

T = 1_800_000_000_000
HORIZON_MINI = min(HORIZONS_MS)
SOURCE = (RACINE / "src" / "hl_observer" / "collection" / "reconciliation_carnets.py")


def _c(ts: int, *, cx: str = "cx", epoque: int = 0) -> dict:
    return {"ts_ms": ts, "connection_id": cx, "l2_gap_epoch": epoque}


def _trois_carnets(**kw) -> list[dict]:
    """Les trois carnets minimaux qui rendent un fill a T exploitable."""
    return [_c(T - 20_000, **kw),
            _c(T + COPY_DELAY_MS + 1_000, **kw),
            _c(T + COPY_DELAY_MS + HORIZON_MINI + 1_000, **kw)]


def _fill(coin: str = "ETH", ts: int = T) -> dict:
    return {"coin": coin, "ts_ms": ts, "vault": "0xA"}


# ------------------------------------------------------------------ le cas complet

def test_un_fill_avec_ses_trois_carnets_est_complet():
    d = R.reconcilier_un_fill(_fill(), _trois_carnets())
    assert d["complet"] is True and d["motifs"] == []
    assert d["reference_ms"] == T - 20_000
    assert d["entree_ms"] >= T + COPY_DELAY_MS
    assert d["sortie_ms"] >= T + COPY_DELAY_MS + HORIZON_MINI


def test_la_reference_retenue_est_la_PLUS_PROCHE_du_signal():
    """Le coût d'entrée se calcule sur le carnet le plus récent avant le signal, pas le plus ancien."""
    carnets = [_c(T - 29_000), _c(T - 2_000), *_trois_carnets()[1:]]
    d = R.reconcilier_un_fill(_fill(), carnets)
    assert d["reference_ms"] == T - 2_000


# ------------------------------------------------------------------ un motif précis par manque

def test_sans_carnet_avant_le_signal_le_motif_est_explicite():
    """Le motif de refus n°1 mesuré : 77 008 signaux sur 98 138."""
    carnets = [c for c in _trois_carnets() if c["ts_ms"] > T]
    d = R.reconcilier_un_fill(_fill(), carnets)
    assert d["complet"] is False and R.SANS_REFERENCE in d["motifs"]


def test_un_carnet_trop_vieux_ne_compte_PAS_comme_reference():
    """Hors de la fenêtre de lag maximal, il ne prouve rien sur l'état du marché au signal."""
    carnets = [_c(T - int(MAX_TARGET_LAG_MS) - 1_000), *_trois_carnets()[1:]]
    d = R.reconcilier_un_fill(_fill(), carnets)
    assert R.SANS_REFERENCE in d["motifs"]


def test_sans_carnet_apres_le_delai_de_reaction():
    carnets = [_trois_carnets()[0]]
    d = R.reconcilier_un_fill(_fill(), carnets)
    assert R.SANS_ENTREE in d["motifs"] and R.SANS_SORTIE in d["motifs"]


def test_sans_carnet_a_l_horizon_la_position_ne_se_clature_jamais():
    carnets = _trois_carnets()[:2]
    d = R.reconcilier_un_fill(_fill(), carnets)
    assert d["complet"] is False
    assert R.SANS_SORTIE in d["motifs"] and R.SANS_REFERENCE not in d["motifs"]


def test_un_coin_sans_AUCUN_carnet_a_son_propre_motif():
    """C83 : un coin actif qu'on ne suit pas du tout doit sauter aux yeux."""
    d = R.reconcilier_un_fill(_fill(), [])
    assert d["motifs"] == [R.AUCUN_CARNET_DU_COIN]


# ------------------------------------------------------------------ identité de connexion

def test_un_carnet_sans_identite_de_connexion_invalide_le_fill():
    carnets = _trois_carnets()
    carnets[1] = {"ts_ms": carnets[1]["ts_ms"]}                     # ni connection_id ni epoque
    d = R.reconcilier_un_fill(_fill(), carnets)
    assert R.SANS_IDENTITE in d["motifs"]


def test_des_carnets_de_connexions_DIFFERENTES_ne_prouvent_pas_la_continuite():
    carnets = [_c(T - 20_000, cx="socketA"),
               _c(T + COPY_DELAY_MS + 1_000, cx="socketB"),
               _c(T + COPY_DELAY_MS + HORIZON_MINI + 1_000, cx="socketB")]
    d = R.reconcilier_un_fill(_fill(), carnets)
    assert R.IDENTITES_DIFFERENTES in d["motifs"]


def test_un_TROU_entre_les_carnets_invalide_aussi():
    """Même socket mais époque de trou différente : une déconnexion s'est produite entre les deux."""
    carnets = [_c(T - 20_000, epoque=0),
               _c(T + COPY_DELAY_MS + 1_000, epoque=1),
               _c(T + COPY_DELAY_MS + HORIZON_MINI + 1_000, epoque=1)]
    d = R.reconcilier_un_fill(_fill(), carnets)
    assert R.IDENTITES_DIFFERENTES in d["motifs"]


def test_l_identite_n_est_jugee_que_si_les_trois_carnets_existent():
    """Inutile de parler d'identité quand il manque deja un carnet : le motif serait trompeur."""
    d = R.reconcilier_un_fill(_fill(), [{"ts_ms": T - 10_000}])
    assert R.SANS_IDENTITE not in d["motifs"]
    assert R.SANS_ENTREE in d["motifs"]


# ------------------------------------------------------------------ la jauge agrégée

def test_la_jauge_ventile_par_coin_et_par_motif():
    fills = [_fill("ETH"), _fill("ETH"), _fill("BTC"), _fill("JAMAIS_SUIVI")]
    carnets = {"ETH": _trois_carnets(), "BTC": _trois_carnets()[:1]}
    j = R.reconcilier(fills, carnets)
    assert j["fills"] == 4 and j["complets"] == 2
    assert j["part_complete"] == 0.5
    assert j["par_coin"]["ETH"]["part_complete"] == 1.0
    assert j["par_coin"]["BTC"]["incomplets"] == 1
    assert j["coins_sans_aucun_carnet"] == ["JAMAIS_SUIVI"]
    assert R.SANS_SORTIE in j["par_motif"]
    assert set(j["explications"]) == set(j["par_motif"])            # chaque motif est explique


def test_les_coins_a_corriger_sont_classes_par_nombre_d_incomplets():
    fills = [_fill("PIRE")] * 5 + [_fill("MOINS_PIRE")] * 2 + [_fill("OK")]
    carnets = {"PIRE": [], "MOINS_PIRE": [], "OK": _trois_carnets()}
    classement = R.coins_a_corriger(R.reconcilier(fills, carnets))
    assert [ligne["coin"] for ligne in classement] == ["PIRE", "MOINS_PIRE"]
    assert classement[0]["incomplets"] == 5
    assert classement[0]["motif_dominant"] == R.AUCUN_CARNET_DU_COIN
    assert all(ligne["coin"] != "OK" for ligne in classement)       # un coin sain n'est pas a corriger


def test_le_resume_est_lisible_dans_les_trois_situations():
    assert "rien a reconcilier" in R.resume_lisible(R.reconcilier([], {}))
    tous = R.reconcilier([_fill()], {"ETH": _trois_carnets()})
    assert "TOUS auront leurs trois carnets" in R.resume_lisible(tous)
    partiel = R.reconcilier([_fill("ETH"), _fill("X")], {"ETH": _trois_carnets()})
    assert "%" in R.resume_lisible(partiel) and "manques" in R.resume_lisible(partiel)


# ------------------------------------------------------------------ robustesse & honnêteté

def test_l_horizon_par_defaut_est_le_PLUS_COURT_donc_le_plus_indulgent():
    """Choix conservateur dans le BON sens : un echec a l'horizon le plus court est un echec partout,
    donc la jauge ne surestime jamais la qualite de la collecte."""
    j = R.reconcilier([_fill()], {"ETH": _trois_carnets()})
    assert j["horizon_ms"] == HORIZON_MINI
    # avec l'horizon le plus LONG, les memes carnets ne suffisent plus
    long = R.reconcilier([_fill()], {"ETH": _trois_carnets()}, horizon_ms=max(HORIZONS_MS))
    assert long["complets"] == 0 and R.SANS_SORTIE in long["par_motif"]


def test_les_entrees_abimees_ne_font_rien_planter():
    fills = [{"coin": "ETH", "ts_ms": "pas-un-nombre"}, {"ts_ms": T}, {"coin": "ETH"}]
    j = R.reconcilier(fills, {"ETH": _trois_carnets()})
    assert j["fills"] == 2                                          # celui sans coin est ignore
    assert j["complets"] == 0
    carnets_abimes = [{"ts_ms": None}, {"ts_ms": "x"}, *_trois_carnets()]
    assert R.reconcilier_un_fill(_fill(), carnets_abimes)["complet"] is True


def test_la_portee_est_declaree_explicitement():
    """On ne doit jamais lire un PnL dans cette jauge : elle teste des conditions NECESSAIRES."""
    j = R.reconcilier([_fill()], {"ETH": _trois_carnets()})
    assert "CONDITIONS_NECESSAIRES" in j["portee"]


def test_CANARI_les_seuils_viennent_du_MOTEUR_et_ne_sont_pas_recopies():
    """Une jauge avec ses propres seuils divergerait silencieusement du moteur le jour ou il change —
    et donnerait alors une fausse assurance sur la qualite de la collecte."""
    src = SOURCE.read_text(encoding="utf-8")
    assert "from hl_observer.backtesting.copy_vault_executable import" in src
    for nom in ("COPY_DELAY_MS", "HORIZONS_MS", "MAX_TARGET_LAG_MS"):
        assert nom in src
    # aucun seuil recopie en dur dans le code (les docstrings peuvent citer des mesures)
    code = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith(("#", "*", '"""', "'''")))
    for littéral in ("30_000", "60_000", "30000", "60000"):
        assert littéral not in code, f"seuil {littéral} recopie : il doit venir du moteur"


# ------------------------------------------------------------------ l'OUTIL : deux pieges evites

def _outil():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "reconciliation_executabilite_test", RACINE / "tools" / "reconciliation_executabilite.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_l_outil_retient_la_RECEPTION_comme_horodatage_canonique():
    """Le chargeur du labo retient `received_at_ms` (ts_ms=received). Si l'outil prenait
    `exchange_ts_ms`, la jauge et le labo ne parleraient pas de la meme chose."""
    outil = _outil()
    groupes = outil.carnets_par_coin([
        {"coin": "ETH", "received_at_ms": 2_000, "exchange_ts_ms": 1_000,
         "connection_id": "cx", "l2_gap_epoch": 0},
    ])
    assert groupes["ETH"][0]["ts_ms"] == 2_000            # reception, pas bourse


def test_l_outil_trie_les_carnets_et_ignore_les_lignes_inutilisables():
    outil = _outil()
    groupes = outil.carnets_par_coin([
        {"coin": "ETH", "received_at_ms": 3_000}, {"coin": "ETH", "received_at_ms": 1_000},
        {"coin": "ETH", "received_at_ms": "x"}, {"received_at_ms": 5_000}, {"coin": "ETH"},
    ])
    assert [c["ts_ms"] for c in groupes["ETH"]] == [1_000, 3_000]


def test_la_fenetre_observable_evite_de_FAUX_manques():
    """Piege majeur : on ne lit que la QUEUE des rubans. Les fills anterieurs au premier carnet lu
    paraitraient tous « sans reference » — un artefact de lecture, pas un defaut de collecte."""
    outil = _outil()
    groupes = {"ETH": [{"ts_ms": 100_000}, {"ts_ms": 900_000}]}
    fenetre = outil.fenetre_observable(groupes, delai_ms=60_000, horizon_ms=30_000, lag_max_ms=30_000)
    assert fenetre == (130_000, 810_000)                 # decale des deux cotes, exactement
    # trop peu de carnets pour juger quoi que ce soit : on refuse de conclure
    etroit = {"ETH": [{"ts_ms": 100_000}, {"ts_ms": 150_000}]}
    assert outil.fenetre_observable(etroit, delai_ms=60_000, horizon_ms=30_000,
                                    lag_max_ms=30_000) is None
    assert outil.fenetre_observable({}, delai_ms=1, horizon_ms=1, lag_max_ms=1) is None


def test_la_queue_jsonl_est_bornee_et_jette_la_ligne_coupee(tmp_path):
    outil = _outil()
    chemin = tmp_path / "ruban.jsonl"
    import json as _json
    chemin.write_text("\n".join(_json.dumps({"i": i, "bourrage": "x" * 80}) for i in range(200)) + "\n",
                      encoding="utf-8")
    objets = outil.queue_jsonl(chemin, 500)
    assert objets and all(isinstance(o, dict) and "i" in o for o in objets)
    assert len(objets) < 200                             # borne respectee
