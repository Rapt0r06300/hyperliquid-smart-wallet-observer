"""La phase 1 lit les carnets du COFFRE, filtre en flux, et ne mentit pas sur ce qu'elle écarte.

POURQUOI CE CHEMIN EXISTE. Mesure du 18/11/2026 : `load_observed_books` lit
`runtime/data/*.jsonl`, dont le ruban L2 ne commence qu'au **17/11 18:35**. Le coffre certifié
porte `bbo` et `book_l2` depuis le **26/10**. Branchée sur les rubans locaux, la phase 1 préparait
donc du vide pour toute tranche antérieure au 17/11, en rendant honnêtement « 0 carnet » — ce qui
se lit « pas de données » alors que la cause était « pas regardé au bon endroit ». Sur la tranche
t001 (13/11 00:00), le passage au coffre fait **0 → 23 046 carnets**.

Ce que ces tests protègent :

  * le coffre absent se DIT (`COFFRE_ABSENT`) au lieu de rendre un dictionnaire vide qu'on lirait
    comme « aucun carnet » ;
  * la fenêtre causale est élargie côté passé (`debut_ms - fenetre_ms`) : un carnet d'avant le
    début de tranche peut renseigner un signal du tout début, et l'oublier perdrait des signaux ;
  * le filtrage se fait EN FLUX : seuls les carnets retenus sont matérialisés, sinon l'économie de
    la phase 1 serait perdue d'avance ;
  * l'audit distingue ce qui a été LU de ce qui a été GARDÉ, par famille — c'est la seule façon de
    distinguer « rien à lire » de « je n'ai pas su lire ».
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from hl_observer.backtesting import coffre_tranches
from hl_observer.backtesting import copy_vault_coffre_vers_labo as deux_phases
from hl_observer.backtesting.copy_vault_signal_alignment import MAX_BOOK_AGE_MS


def _cotation() -> dict[str, Any]:
    """Les champs que le REPLAY exige d'un carnet : les deux cotes, la capacite, et l'IDENTITE.

    Sans les trois premiers, `carnets_du_coffre` refuse le carnet -- et c'est voulu : les cinq
    familles du coffre n'ont pas le meme schema, et le replay levait `KeyError: 'ask'` apres 60
    candidats.

    `connection_id` et `l2_gap_epoch` ont ete AJOUTES a cette fixture le 19/11/2026, parce qu'elle
    ne representait plus la donnee reelle : le replay exige que les trois carnets d'un episode
    portent la meme identite de connexion (`L2_CONNECTION_IDENTITY_INCOMPLETE` sinon), et un
    carnet qui n'en a pas est desormais refuse a la lecture. Une fixture plus pauvre que la realite
    fait passer des tests qui ne protegent plus rien -- c'est le piege du double de test fige.
    """
    return {"bid": 100.0, "ask": 100.1, "capacity_usd": 5_000.0,
            "connection_id": "l2-lane-fixture", "l2_gap_epoch": 0}


def _index(tmp_path: Path, shards: list[dict[str, Any]]) -> Path:
    chemin = tmp_path / "runtime/coffre_certifie/LOCAL_INDEX.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps({"shards": shards}), encoding="utf-8")
    return chemin


def test_un_coffre_absent_est_dit_et_non_confondu_avec_un_corpus_vide(tmp_path: Path) -> None:
    """« COFFRE_ABSENT » et « aucun carnet » doivent être deux réponses distinctes.

    Rendre un dictionnaire vide sans motif laisserait croire que le corpus ne contient rien, alors
    que l'index n'a simplement pas été trouvé — l'erreur la plus coûteuse de la journée.
    """
    carnets, audit = deux_phases.carnets_du_coffre(
        tmp_path, coins=["BTC"], debut_ms=0, fin_ms=1_000)
    assert carnets == {}
    assert audit["status"] == "COFFRE_ABSENT"
    assert "LOCAL_INDEX.json" in audit["chemin"]


def test_les_carnets_hors_portee_d_un_signal_ne_sont_pas_materialises(
    tmp_path: Path, monkeypatch
) -> None:
    """Le filtrage est EN FLUX : un carnet hors fenêtre est lu, compté, et jamais garde."""
    _index(tmp_path, [{"famille": "book_l2", "ts_min_ms": 0, "ts_max_ms": 10_000_000}])
    signal = 1_000_000
    lignes = [
        {"coin": "BTC", "ts_ms": signal - 10, **_cotation()},                      # garde
        {"coin": "BTC", "ts_ms": signal - MAX_BOOK_AGE_MS, **_cotation()},         # garde (borne)
        {"coin": "BTC", "ts_ms": signal - MAX_BOOK_AGE_MS - 1, **_cotation()},     # ecarte (trop vieux)
        {"coin": "BTC", "ts_ms": signal + 1, **_cotation()},                       # GARDE : l'entree
    ]                                                                            # vient apres le signal

    monkeypatch.setattr(coffre_tranches, "selectionner",
                        lambda *a, **k: {"shards": [{"id": "s1"}]})
    monkeypatch.setattr(coffre_tranches, "horloge_de", lambda famille: "ts_ms")
    monkeypatch.setattr(coffre_tranches, "flux",
                        lambda *a, **k: iter(lignes if k.get("famille") == "book_l2" else []))

    gardes, audit = deux_phases.carnets_du_coffre(
        tmp_path, coins=["BTC"], debut_ms=signal - 100_000, fin_ms=signal,
        familles=("book_l2",), instants_par_coin={"BTC": [signal]})

    assert audit["status"] == "LU_DEPUIS_LE_COFFRE"
    assert audit["lignes_lues"] == 4, "les 4 lignes ont bien ete traversees"
    # DEUX gardes, UN DE CHAQUE COTE de l'ancre de reference, et chacun LE PLUS PROCHE.
    #
    # L'ancre de reference vaut le signal EXACTEMENT -- elle n'est pas quantifiee, parce qu'une
    # ancre arrondie vers le bas laissait la reference deriver jusqu'a 45 s en arriere et faisait
    # refuser 418 candidats de VALIDATION sur 418 (`STALE_OR_MISSING_REFERENCE_BOOK`). Son cote
    # passe retient donc le carnet le plus proche AU PLUS TARD au signal : celui a 10 ms, et non
    # celui a 30 s, qui ne dirait plus l'etat du marche au moment de la decision.
    #
    # Le carnet a `signal + 1` reste pour une autre raison : il est le plus proche de l'autre cote.
    # Il ne servira ni de reference (trop tard) ni d'entree -- celle-ci se cherche une MINUTE plus
    # tard, et cette fixture n'en contient aucune. Il borne la memoire sans rien promettre.
    assert audit["carnets_gardes"] == 2
    assert signal - MAX_BOOK_AGE_MS - 1 not in [c["ts_ms"] for c in gardes["BTC"]]
    assert [c["ts_ms"] for c in gardes["BTC"]] == [signal - 10, signal + 1]
    assert audit["familles"]["book_l2"] == {"shards": 1, "lus": 4, "gardes": 2,
                                           "abandonnee_sans_champs_de_carnet": False}


def test_l_audit_distingue_les_lignes_lues_des_carnets_gardes(tmp_path: Path, monkeypatch) -> None:
    """Sans ce couple, « 0 garde » ne se distingue pas de « 0 lu » — le piège du zéro muet."""
    _index(tmp_path, [{"famille": "book_l2", "ts_min_ms": 0, "ts_max_ms": 10_000_000}])
    monkeypatch.setattr(coffre_tranches, "selectionner",
                        lambda *a, **k: {"shards": [{"id": "s1"}]})
    monkeypatch.setattr(coffre_tranches, "horloge_de", lambda famille: "ts_ms")
    # Des lignes lues, AUCUNE a portee : lues > 0 et gardes == 0.
    monkeypatch.setattr(coffre_tranches, "flux", lambda *a, **k: iter(
        [{"coin": "BTC", "ts_ms": 10}, {"coin": "BTC", "ts_ms": 20}]))

    gardes, audit = deux_phases.carnets_du_coffre(
        tmp_path, coins=["BTC"], debut_ms=5_000_000, fin_ms=6_000_000,
        familles=("book_l2",), instants_par_coin={"BTC": [5_500_000]})

    assert gardes == {}
    assert audit["lignes_lues"] == 2, "on a bien LU : ce n'est pas « rien a lire »"
    assert audit["carnets_gardes"] == 0


def test_la_fenetre_est_elargie_vers_le_passe_a_la_selection(tmp_path: Path, monkeypatch) -> None:
    """Un carnet d'AVANT le debut de tranche peut renseigner un signal du tout debut.

    Si la selection demandait `debut_ms` tout court, ce carnet ne serait jamais lu et le premier
    signal de chaque tranche perdrait son contexte -- un signal perdu par tranche, 33 fois.
    """
    _index(tmp_path, [{"famille": "book_l2", "ts_min_ms": 0, "ts_max_ms": 10_000_000}])
    vus: dict[str, Any] = {}

    def selectionner(_shards, **kw):
        vus.update(kw)
        return {"shards": [{"id": "s1"}]}

    monkeypatch.setattr(coffre_tranches, "selectionner", selectionner)
    monkeypatch.setattr(coffre_tranches, "horloge_de", lambda famille: "ts_ms")
    monkeypatch.setattr(coffre_tranches, "flux", lambda *a, **k: iter([]))

    debut = 1_000_000
    deux_phases.carnets_du_coffre(
        tmp_path, coins=["BTC"], debut_ms=debut, fin_ms=debut + 1_000,
        familles=("book_l2",))

    assert vus["debut_ms"] == debut - MAX_BOOK_AGE_MS, (
        "la selection doit remonter d'une fenetre causale avant le debut de tranche")


def test_les_familles_de_carnets_couvrent_le_coffre_reel() -> None:
    """Les familles visées sont celles que le coffre porte vraiment (mesure du 18/11/2026).

    `bbo` (111,9 M lignes) et `book_l2` (9,6 M) remontent au 26/10 ; `micro_bbo`, `micro_l2` et
    `venue_book` complètent. En oublier une rendrait des tranches artificiellement pauvres.
    """
    assert set(deux_phases.FAMILLES_DE_CARNETS) == {
        "book_l2", "micro_l2", "venue_book", "bbo", "micro_bbo",
    }


def test_un_carnet_sans_les_deux_cotes_est_refuse_et_compte(tmp_path: Path, monkeypatch) -> None:
    """DONNEE INCOMPLETE = REFUS TRACABLE, jamais une mesure qui tombe.

    Les cinq familles de carnets du coffre n'ont pas le meme schema. Un carnet sans `ask` faisait
    lever `KeyError: 'ask'` au replay, apres 60 candidats explores -- donc apres plusieurs minutes
    de calcul perdues, et sans dire ce qui manquait. On le refuse et on le COMPTE.
    """
    _index(tmp_path, [{"famille": "book_l2", "ts_min_ms": 0, "ts_max_ms": 10_000_000}])
    signal = 1_000_000
    lignes = [
        {"coin": "BTC", "ts_ms": signal - 10, **_cotation()},            # complet
        {"coin": "BTC", "ts_ms": signal - 11, "bid": 100.0},             # pas d'ask
        {"coin": "BTC", "ts_ms": signal - 12, "ask": 100.1},             # pas de bid
        {"coin": "BTC", "ts_ms": signal - 13, "bid": 1.0, "ask": 2.0},   # pas de capacite
    ]
    monkeypatch.setattr(coffre_tranches, "selectionner",
                        lambda *a, **k: {"retenus": [{"id": "s1"}]})
    monkeypatch.setattr(coffre_tranches, "horloge_de", lambda famille: "ts_ms")
    monkeypatch.setattr(coffre_tranches, "flux", lambda *a, **k: iter(lignes))

    gardes, audit = deux_phases.carnets_du_coffre(
        tmp_path, coins=["BTC"], debut_ms=signal - 100_000, fin_ms=signal,
        familles=("book_l2",), instants_par_coin={"BTC": [signal]})

    assert audit["carnets_gardes"] == 1, "seul le carnet complet est retenu"
    assert audit["ecartes_champs_manquants"] == 3
    assert len(gardes["BTC"]) == 1


def test_le_carnet_de_sortie_d_un_horizon_long_est_garde(tmp_path: Path, monkeypatch) -> None:
    """DEFAUT MESURE LE 19/11/2026 : le plafond gardait un PREFIXE, donc jamais la sortie.

    L'ancienne regle -- « les 240 premiers carnets de la fenetre » -- etait justifiee dans son
    propre commentaire par « ce sont les plus proches des instants cibles ». C'etait faux : les
    premiers d'une fenetre sont les plus proches de son DEBUT. Sur la tranche t001, SOL, TIA, XMR,
    ZEC et XRP portaient exactement 240 carnets couvrant 40,9 minutes d'une fenetre de 240, sur une
    connexion unique et sans la moindre coupure : le carnet de sortie d'un episode d'une heure
    n'avait jamais ete lu. Le replay rendait `STALE_OR_MISSING_EXIT_BOOK`, et le defaut accusait
    les donnees.
    """
    _index(tmp_path, [{"famille": "book_l2", "ts_min_ms": 0, "ts_max_ms": 100_000_000}])
    signal = 10_000_000
    sortie = signal + 60_000 + 3_600_000        # entree (+ delai) puis horizon le plus long
    # Un carnet toutes les secondes entre le signal et son entree : de quoi epuiser n'importe
    # quel plafond pose en prefixe, AVANT que la sortie n'arrive.
    lignes = [{"coin": "BTC", "ts_ms": signal + 1000 * k, **_cotation()} for k in range(400)]
    lignes.append({"coin": "BTC", "ts_ms": sortie, **_cotation()})

    monkeypatch.setattr(coffre_tranches, "selectionner",
                        lambda *a, **k: {"shards": [{"id": "s1"}]})
    monkeypatch.setattr(coffre_tranches, "horloge_de", lambda famille: "ts_ms")
    monkeypatch.setattr(coffre_tranches, "flux",
                        lambda *a, **k: iter(lignes if k.get("famille") == "book_l2" else []))

    gardes, audit = deux_phases.carnets_du_coffre(
        tmp_path, coins=["BTC"], debut_ms=signal - 1000, fin_ms=signal + 1000,
        familles=("book_l2",), instants_par_coin={"BTC": [signal]})

    horodatages = [c["ts_ms"] for c in gardes["BTC"]]
    assert sortie in horodatages, (
        "le carnet de sortie doit survivre au plafond : sans lui, aucun episode d'une heure "
        "n'est mesurable et le refus accuse les donnees"
    )
    assert audit["ecartes_trop_denses"] > 0, "le plafond travaille toujours"
    assert len(horodatages) < len(lignes), "il borne bien la memoire"


def test_les_connexions_concurrentes_ne_sont_pas_melangees() -> None:
    """DEFAUT MESURE LE 19/11/2026 : 95 % des refus venaient d'un melange d'observateurs.

    Le replay refuse un episode dont la reference, l'entree et la sortie ne portent pas la meme
    `connection_id` (`L2_CONNECTION_GAP_CROSSED`) -- et il a raison : trois carnets venus de trois
    flux ne prouvent pas une observation continue. Mais plusieurs lanes observent le MEME coin en
    meme temps : sur t001, BTC portait une connexion de 151 minutes d'affilee plus neuf
    reconnexions se relayant toutes les dix a vingt-cinq minutes. Resultat : 250 des 262 candidats
    de TRAIN refuses pour un trou qui n'existait pas.
    """
    longue = [{"ts_ms": 1000 * k, "connection_id": "longue"} for k in range(0, 200)]
    relais = [{"ts_ms": 1000 * k + 500, "connection_id": f"relais-{k // 20}"} for k in range(0, 200)]
    gardes, audit = deux_phases.une_seule_connexion_par_coin({"BTC": longue + relais})

    identites = {c["connection_id"] for c in gardes["BTC"]}
    assert identites == {"longue"}, "seule la connexion la plus etendue reste"
    assert audit["ecartes_connexion_minoritaire"] == len(relais)
    assert audit["coins_a_connexion_unique"] == 0

    # Un coin qui n'a qu'une connexion passe intact : le filtre ne doit rien couter la ou il n'y
    # a rien a demeler.
    gardes, audit = deux_phases.une_seule_connexion_par_coin({"ETH": longue})
    assert len(gardes["ETH"]) == len(longue)
    assert audit["ecartes_connexion_minoritaire"] == 0
    assert audit["coins_a_connexion_unique"] == 1


def test_les_ancres_couvrent_les_trois_instants_du_replay() -> None:
    """Reference, entree, et UNE sortie par horizon explore : rien de plus, rien de moins."""
    from hl_observer.backtesting.copy_vault_local_lab import _PARAMETER_DOMAINS

    horizons = tuple(dict(_PARAMETER_DOMAINS)["horizon_ms"])
    signal, delai, pas = 5_000_000, 60_000, 15_000
    ancres = deux_phases.ancres_utiles(
        [signal], delai_ms=delai, horizons_ms=horizons, pas_ms=pas)

    for cible, nom in [(signal, "reference"), (signal + delai, "entree")] + [
        (signal + delai + h, f"sortie a {h} ms") for h in horizons
    ]:
        assert any(0 <= cible - a <= pas for a in ancres), f"aucune ancre pour la {nom}"
    # DEUX REGIMES, ET C'EST VOULU. La reference et l'entree sont EXACTES : ce sont elles qui
    # decident de l'episode, et une ancre arrondie vers le bas les laissait deriver d'un pas --
    # assez pour faire refuser 418 candidats sur 418 en VALIDATION. Les sorties, elles, se
    # quantifient : leur cible depend de l'horizon cherche ET de l'instant d'entree reel, donc
    # elle est deja approximative. C'est ce qui empeche le budget de croitre avec le nombre de
    # signaux voisins.
    seul = deux_phases.ancres_utiles([signal], delai_ms=delai, horizons_ms=horizons, pas_ms=pas)
    paire = deux_phases.ancres_utiles(
        [signal, signal + 1], delai_ms=delai, horizons_ms=horizons, pas_ms=pas)
    assert len(paire) == len(seul) + 2, (
        "deux signaux a 1 ms d'ecart ajoutent leurs deux ancres exactes, mais partagent "
        "les crans de sortie -- sinon le budget grossirait avec la densite des signaux"
    )
    sorties_seul = [a for a in seul if a > signal + delai]
    sorties_paire = [a for a in paire if a > signal + delai + 1]
    assert sorties_paire == sorties_seul, "les ancres de sortie, elles, fusionnent bien"


def test_le_filtre_d_action_suit_la_politique_gelee() -> None:
    """La phase 1 ne prepare que les metaordres copiables. Ce test le prouve CONTRE LE MOTEUR.

    `ACTIONS_COPIEES_PAR_LA_POLITIQUE` duplique une regle qui vit dans le moteur gele, qu'on ne
    reecrit pas. Une copie muette derive : si la politique apprenait un jour a copier les
    ouvertures, la phase 1 continuerait a les jeter et personne ne le saurait -- le labo rendrait
    « aucun candidat » en accusant les donnees. On fait donc juger un OPEN, un CLOSE et un ADD par
    le moteur lui-meme, et on verifie que son verdict et notre filtre disent la meme chose.
    """
    from hl_observer.backtesting import copy_vault_v21_frozen as gel

    def _metaordre(action: str) -> dict:
        return {"coin": "BTC", "signal_ts_ms": 1_000_000, "direction": 1, "vault": "v",
                "member_events": [{"action": action, "taille_usd": 50_000.0}]}

    for action in ("OPEN", "CLOSE", "ADD", "", "add"):
        metaordre = _metaordre(action)
        juge_par_le_moteur = gel._first_action(metaordre) == "ADD"
        assert deux_phases.copiable_par_la_politique(metaordre) is juge_par_le_moteur, (
            f"le filtre et la politique divergent sur {action!r} : l'un des deux a change seul"
        )

    # Et la constante dit bien ce que le moteur accepte, pas une liste plus large par confort.
    assert deux_phases.ACTIONS_COPIEES_PAR_LA_POLITIQUE == ("ADD",)
    assert deux_phases.premiere_action(_metaordre("add")) == "ADD", "la casse ne doit pas decider"
    # Un metaordre sans membres retombe sur son action propre : le groupement peut etre vide.
    assert deux_phases.premiere_action({"action": "ADD"}) == "ADD"


def test_les_connexions_se_succedent_au_lieu_d_etre_reduites_a_une_seule() -> None:
    """DEFAUT MESURE LE 19/11/2026 : choisir UNE connexion pour six journees en perd cinq.

    Premiere version de ce filtre : garder la connexion la plus etendue, pour tout le corpus.
    Une lane L2 vit quelques heures, pas six jours -- resultat, **un seul coin couvert le 13/11
    et treize le 14**, alors que TRAIN est le 13-15 ; 365 819 carnets tombaient a 64 024 et
    418 candidats de VALIDATION sur 418 etaient refuses faute du moindre carnet.

    Ce que le replay exige n'est pas une connexion unique, mais qu'un EPISODE n'en traverse pas
    deux. Des connexions qui SE SUCCEDENT sont donc toutes gardees ; seules celles qui se
    recouvrent sont arbitrees.
    """
    # Trois lanes qui se relaient proprement, sans se chevaucher.
    matin = [{"ts_ms": 1000 * k, "connection_id": "matin"} for k in range(0, 100)]
    midi = [{"ts_ms": 1000 * k, "connection_id": "midi"} for k in range(200, 300)]
    soir = [{"ts_ms": 1000 * k, "connection_id": "soir"} for k in range(400, 500)]
    gardes, audit = deux_phases.une_seule_connexion_par_coin({"BTC": matin + midi + soir})

    assert {c["connection_id"] for c in gardes["BTC"]} == {"matin", "midi", "soir"}, (
        "des connexions qui se succedent couvrent chacune sa periode : aucune n'est de trop"
    )
    assert audit["ecartes_connexion_minoritaire"] == 0
    assert [c["ts_ms"] for c in gardes["BTC"]] == sorted(c["ts_ms"] for c in gardes["BTC"])

    # En revanche, deux observateurs SIMULTANES se melangeraient dans un meme episode : on garde
    # le plus long et on ecarte l'autre.
    longue = [{"ts_ms": 1000 * k, "connection_id": "longue"} for k in range(0, 100)]
    doublon = [{"ts_ms": 1000 * k + 500, "connection_id": "doublon"} for k in range(10, 60)]
    gardes, audit = deux_phases.une_seule_connexion_par_coin({"ETH": longue + doublon})
    assert {c["connection_id"] for c in gardes["ETH"]} == {"longue"}
    assert audit["ecartes_connexion_minoritaire"] == len(doublon)


def test_le_checkpoint_id_du_coffre_ne_se_fait_pas_passer_pour_un_point_de_controle(
    tmp_path: Path, monkeypatch
) -> None:
    """UN HOMONYME QUI DECIDAIT DE LA MESURE (mesure du 19/11/2026).

    Pour le replay, `checkpoint_id` designe un point de controle lie cryptographiquement a un
    metaordre : il attend `{metaorder_id}:REFERENCE`, `:ENTRY`, `:EXIT:{horizon}`. Pour le
    collecteur de `book_l2`, c'est l'identifiant d'un snapshot -- un hash, sans rapport. Et
    `index_des_carnets(...).continus()` EXCLUT tout carnet qui en porte un.

    Le champ est apparu dans le coffre a partir de la tranche t021, soit le 16/11 : exactement
    VALIDATION et OOS. 46 % des carnets du corpus en portaient un, et 425 candidats de VALIDATION
    sur 425 etaient refuses faute de reference -- alors que 1 322 signaux sur 1 969 avaient un
    carnet a moins de 30 s. Une evolution de la collecte avait casse le replay en silence.
    """
    _index(tmp_path, [{"famille": "book_l2", "ts_min_ms": 0, "ts_max_ms": 10_000_000}])
    signal = 1_000_000
    monkeypatch.setattr(coffre_tranches, "selectionner",
                        lambda *a, **k: {"shards": [{"id": "s1"}]})
    monkeypatch.setattr(coffre_tranches, "horloge_de", lambda famille: "ts_ms")
    monkeypatch.setattr(coffre_tranches, "flux", lambda *a, **k: iter([
        {"coin": "BTC", "ts_ms": signal - 10, "checkpoint_id": "0xfe5abe53303f", **_cotation()},
    ]))

    gardes, audit = deux_phases.carnets_du_coffre(
        tmp_path, coins=["BTC"], debut_ms=signal - 100_000, fin_ms=signal,
        familles=("book_l2",), instants_par_coin={"BTC": [signal]})

    carnet = gardes["BTC"][0]
    assert "checkpoint_id" not in carnet, (
        "un identifiant de snapshot ne doit pas se faire passer pour un point de controle de "
        "metaordre : le replay exclut de sa suite continue tout carnet qui en porte un"
    )
    assert carnet["checkpoint_id_coffre"] == "0xfe5abe53303f", "la provenance reste lisible"
    assert audit["checkpoint_id_renommes"] == 1, "et le renommage se COMPTE"

    # Et le carnet redevient ce qu'il est : une observation continue ordinaire.
    from hl_observer.backtesting.copy_vault_book_index import index_des_carnets
    continus, refus = index_des_carnets(list(gardes["BTC"])).continus()
    assert len(continus) == 1 and refus is None


def test_un_carnet_sans_identite_de_connexion_est_refuse_et_compte(
    tmp_path: Path, monkeypatch
) -> None:
    """DEFAUT MESURE LE 19/11/2026, et c'etait la suite de la correction de l'homonyme.

    Le replay prouve la continuite d'une observation par l'identite de connexion : les trois
    carnets d'un episode doivent porter la meme `connection_id` et le meme `l2_gap_epoch`, sinon
    `L2_CONNECTION_IDENTITY_INCOMPLETE`. Or 34,8 % des carnets des tranches t021 et suivantes sont
    des snapshots ponctuels de source `HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT` -- une
    interrogation REST posee au moment d'un fill, pas un flux persistant, donc sans identite.

    Les laisser passer faisait refuser 344 candidats de VALIDATION sur 425 et 473 sur 628 en OOS,
    et pire : ils CONSOMMAIENT le budget d'une ancre au detriment d'un carnet utilisable. Un
    carnet qui fera echouer l'episode a coup sur se refuse a la lecture, et se compte.
    """
    _index(tmp_path, [{"famille": "book_l2", "ts_min_ms": 0, "ts_max_ms": 10_000_000}])
    signal = 1_000_000
    monkeypatch.setattr(coffre_tranches, "selectionner",
                        lambda *a, **k: {"shards": [{"id": "s1"}]})
    monkeypatch.setattr(coffre_tranches, "horloge_de", lambda famille: "ts_ms")
    sans_identite = {k: v for k, v in _cotation().items()
                     if k not in ("connection_id", "l2_gap_epoch")}
    monkeypatch.setattr(coffre_tranches, "flux", lambda *a, **k: iter([
        # Le snapshot REST : causal, pose pile au signal, mais sans identite de connexion.
        {"coin": "BTC", "ts_ms": signal - 5, "causal_observation": True,
         "source": "HYPERLIQUID_INFO_L2BOOK_CAUSAL_CHECKPOINT", **sans_identite},
        {"coin": "BTC", "ts_ms": signal - 6, "connection_id": "", "l2_gap_epoch": 0,
         **sans_identite},
        {"coin": "BTC", "ts_ms": signal - 7, "connection_id": "l2-lane-x",
         "l2_gap_epoch": -1, **sans_identite},
        # Et celui qui PEUT servir.
        {"coin": "BTC", "ts_ms": signal - 8, **_cotation()},
    ]))

    gardes, audit = deux_phases.carnets_du_coffre(
        tmp_path, coins=["BTC"], debut_ms=signal - 100_000, fin_ms=signal,
        familles=("book_l2",), instants_par_coin={"BTC": [signal]})

    assert audit["ecartes_sans_identite_de_connexion"] == 3, (
        "identite absente, vide ou epoque negative : trois refus, chacun compte"
    )
    assert [c["ts_ms"] for c in gardes["BTC"]] == [signal - 8]
    assert audit["carnets_gardes"] == 1
