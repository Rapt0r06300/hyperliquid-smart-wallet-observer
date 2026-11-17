"""LA PROFONDEUR DU FUNDING ETAIT GELEE A 211 JOURS, ET AUCUN TEST NE LE VOYAIT.

LE DEFAUT, MESURE LE 15/11/2026
-------------------------------
`passe_funding` ne connaissait qu'UN front : l'horodatage le plus RECENT par coin, et elle ne
savait qu'avancer (`a = max(now - PROFONDEUR, dernier + 1)`). Pour un coin deja tenu a jour sous
l'ancien plafond de 208 jours, `dernier` vaut ~maintenant, donc `a` vaut ~maintenant, donc le coin
etait declare « a jour »... a 211 jours de profondeur. **Il ne pouvait plus JAMAIS etre
approfondi.** Etat reel du coffre ce jour-la : 118 coins avec du funding, profondeur mediane
**211 jours**, et **3 coins seulement a 1 100 jours** — exactement les trois partis de zero.
Porter `PROFONDEUR_FUNDING_JOURS` de 208 a 1 100 n'avait donc servi qu'aux coins neufs.

CE QUE CES TESTS VERROUILLENT
-----------------------------
1. un coin A JOUR mais PEU PROFOND est creuse (le defaut exact, qui echoue sur le code d'avant) ;
2. le creusage se fait EN RONDES — une page par coin par ronde — parce que la fenetre mesurable
   d'un livre est l'INTERSECTION des historiques : trois coins parfaits et 258 coins pauvres
   laissent la fenetre INCHANGEE ;
3. une fenetre vide declenche une SONDE depuis le plancher avant de conclure « plus rien avant » ;
4. un coin au bout de son histoire n'est plus jamais redemande (pas de requetes dans le vide) ;
5. un trou est SIGNALE, jamais comble en silence ;
6. le budget de debit compte les requetes REELLEMENT faites, sonde comprise.

Aucun reseau : le serveur de funding est un double, l'horloge est injectee.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("bcv_prof", RACINE / "tools" / "backfill_candles_vaults.py")
BC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BC)

HEURE = 3_600_000
NOW = 1_790_000_000_000 // HEURE * HEURE


def _racine(tmp_path: Path, coins: list[str]) -> Path:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "copy_vault_coins.json").write_text(json.dumps({"coins": coins}),
                                                               encoding="utf-8")
    return tmp_path


def _lignes(chemin: Path) -> list[dict]:
    return [json.loads(x) for x in chemin.read_text(encoding="utf-8").splitlines() if x.strip()]


def _serveur(appels: list, *, origine_ms: int):
    """Faux `fundingHistory` : un point par heure depuis `origine_ms`, 500 par reponse au plus.

    Reproduit la semantique reelle de l'endpoint : les points partent de `startTime` et avancent.
    """
    def poster(coin, a, b):
        appels.append((coin, int(a), int(b)))
        depart = max(int(a), origine_ms)
        return [{"coin": coin, "fundingRate": "0.00001", "premium": "0.0002", "time": t}
                for t in range(depart, int(b) + 1, HEURE)][:BC.PAGE_FUNDING]
    return poster


def _etat_initial(root: Path, *, recent: dict, ancien: dict) -> None:
    """Ecrit un etat de depart : des coins deja « a jour » mais PEU PROFONDS."""
    (root / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (root / BC.ETAT).write_text(json.dumps({
        "_schema": BC.SCHEMA_ETAT,
        "intervalles": {BC.SERIE_FUNDING: recent, BC.SERIE_FUNDING_ANCIEN: ancien}}),
        encoding="utf-8")


# ─────────────── 1. LE DEFAUT EXACT : un coin a jour mais peu profond ───────────────
def test_un_coin_a_jour_mais_peu_profond_est_CREUSE(tmp_path):
    root = _racine(tmp_path, ["BTC"])
    # BTC est a jour (dernier point = il y a une heure) mais ne remonte qu'a 200 jours : c'est
    # exactement l'etat des 115 coins bloques du 15/11.
    _etat_initial(root, recent={"BTC": NOW - HEURE}, ancien={"BTC": NOW - 200 * 24 * HEURE})
    appels: list = []
    bilan = BC.passe_funding(root, now_ms=NOW, poster=_serveur(appels, origine_ms=NOW - 900 * 24 * HEURE),
                             dormir=lambda s: None, univers=None, profondeur_ms=1100 * 24 * HEURE)

    assert bilan["creuses"] >= 1, (
        "le front arriere doit avoir creuse : sans lui, ce coin reste a 200 jours POUR TOUJOURS")
    etat = json.loads((root / BC.ETAT).read_text(encoding="utf-8"))["intervalles"]
    profondeur_j = (NOW - int(etat[BC.SERIE_FUNDING_ANCIEN]["BTC"])) / (24 * HEURE)
    assert profondeur_j > 200.0, f"profondeur restee a {profondeur_j:.0f} j"
    # les points ecrits sont bien ANTERIEURS a l'ancien plus-ancien : c'est du passe, pas du futur
    ecrits = [x["ts_ms"] for x in _lignes(root / BC.SORTIE_FUNDING)]
    assert ecrits and min(ecrits) < NOW - 200 * 24 * HEURE


def test_le_creusage_s_arrete_au_plancher_demande(tmp_path):
    root = _racine(tmp_path, ["BTC"])
    _etat_initial(root, recent={"BTC": NOW - HEURE}, ancien={"BTC": NOW - 100 * 24 * HEURE})
    profondeur = 150 * 24 * HEURE                      # on ne veut QUE 150 jours
    BC.passe_funding(root, now_ms=NOW, poster=_serveur([], origine_ms=NOW - 900 * 24 * HEURE),
                     dormir=lambda s: None, univers=None, profondeur_ms=profondeur)
    ecrits = [x["ts_ms"] for x in _lignes(root / BC.SORTIE_FUNDING)]
    assert min(ecrits) >= NOW - profondeur, (
        "aucun point sous le plancher : la profondeur demandee est une BORNE, pas une suggestion")


# ─────────────── 2. EN RONDES : la profondeur monte pour TOUT le livre ───────────────
def test_le_creusage_tourne_coin_par_coin_et_non_coin_apres_coin(tmp_path):
    """L'ORDRE des requetes est la preuve : A, B, C, A, B, C — jamais A, A, A, puis B.

    C'est le point entier du decoupage en rondes. La fenetre qu'une strategie transversale peut
    mesurer est l'INTERSECTION des historiques de son livre : elle est donc fixee par le coin le
    MOINS profond. Vider un coin avant de passer au suivant n'avance donc cette fenetre qu'au
    dernier coin servi — mesure du 15/11 : 41 minutes de rattrapage, 2 coins sur 261, fenetre
    mesurable inchangee. Une page par coin et par ronde la fait monter des la premiere ronde.
    """
    root = _racine(tmp_path, ["AAA", "BBB", "CCC"])
    depart = {c: NOW - 60 * 24 * HEURE for c in ("AAA", "BBB", "CCC")}
    _etat_initial(root, recent={c: NOW - HEURE for c in depart}, ancien=dict(depart))
    arriere: list[str] = []

    def poster(coin, a, b):
        if int(b) < NOW - 59 * 24 * HEURE:            # une requete du front ARRIERE
            arriere.append(coin)
        depart_pts = max(int(a), NOW - 120 * 24 * HEURE)
        return [{"coin": coin, "fundingRate": "0.00001", "premium": "0.0", "time": t}
                for t in range(depart_pts, int(b) + 1, HEURE)][:BC.PAGE_FUNDING]

    bilan = BC.passe_funding(root, now_ms=NOW, poster=poster, dormir=lambda s: None, univers=None,
                             profondeur_ms=200 * 24 * HEURE)
    assert bilan["rondes"] >= 3, "60 -> 120 jours = 3 pages de 20,8 j par coin"
    # Les trois premieres requetes arriere doivent toucher TROIS coins differents.
    assert len(set(arriere[:3])) == 3, (
        f"ordre observe {arriere[:6]} : un coin a ete creuse plusieurs fois avant que les autres "
        "aient eu leur premiere page — c'est exactement le defaut que les rondes corrigent")
    assert arriere[:3] == arriere[3:6], "la ronde suivante repasse dans le meme ordre"

    etat = json.loads((root / BC.ETAT).read_text(encoding="utf-8"))["intervalles"]
    profondeurs = [(NOW - int(v)) / (24 * HEURE) for v in etat[BC.SERIE_FUNDING_ANCIEN].values()]
    assert max(profondeurs) - min(profondeurs) <= 21.0, (
        "les profondeurs restent comparables entre coins : une page (20,8 j) d'ecart au plus, "
        "donc l'intersection du livre monte avec elles")


def test_une_ronde_par_page_jusqu_a_l_origine(tmp_path):
    root = _racine(tmp_path, ["AAA", "BBB"])
    _etat_initial(root, recent={c: NOW - HEURE for c in ("AAA", "BBB")},
                  ancien={c: NOW - 60 * 24 * HEURE for c in ("AAA", "BBB")})
    bilan = BC.passe_funding(root, now_ms=NOW, poster=_serveur([], origine_ms=NOW - 100 * 24 * HEURE),
                             dormir=lambda s: None, univers=None, profondeur_ms=200 * 24 * HEURE)
    # 60 -> 100 jours = 40 jours a prendre = 2 pages de 20,8 j par coin, donc au moins 2 rondes.
    assert bilan["rondes"] >= 2 and bilan["creuses"] >= 2
    assert bilan["origines"] == 2, "les deux coins atteignent le debut de leur histoire"
    etat = json.loads((root / BC.ETAT).read_text(encoding="utf-8"))["intervalles"]
    assert all(int(v) <= NOW - 100 * 24 * HEURE for v in etat[BC.SERIE_FUNDING_ANCIEN].values())


# ─────────────── 3-4. LA SONDE, ET LE COIN QU'ON NE REDEMANDE PLUS ───────────────
def test_fenetre_vide_declenche_une_sonde_avant_de_conclure(tmp_path):
    # Le coin n'a RIEN entre -500 h et son plus ancien point, mais il a de l'histoire bien avant :
    # conclure « plus rien » sur la seule fenetre vide perdrait cette histoire.
    vieux = NOW - 400 * 24 * HEURE
    plancher = NOW - 900 * 24 * HEURE
    appels: list = []

    def poster(coin, a, b):
        appels.append((int(a), int(b)))
        if int(a) <= plancher:                         # la SONDE : elle part du plancher
            return [{"coin": coin, "fundingRate": "0.00002", "premium": "0.0",
                     "time": vieux - 5 * HEURE}]
        return []                                      # la page immediatement anterieure est vide

    lignes, erreur, origine, requetes = BC.page_arriere_funding(
        "BTC", ancien=vieux, plancher=plancher, poster=poster)
    assert requetes == 2, "la page PUIS la sonde : deux requetes, et le budget doit les compter"
    assert erreur is None and origine is False
    assert [x["ts_ms"] for x in lignes] == [vieux - 5 * HEURE], (
        "la sonde a retrouve l'histoire que la fenetre vide cachait")


def test_sonde_vide_marque_l_origine_et_le_coin_n_est_plus_jamais_redemande(tmp_path):
    root = _racine(tmp_path, ["NEUF"])
    _etat_initial(root, recent={"NEUF": NOW - HEURE}, ancien={"NEUF": NOW - 30 * 24 * HEURE})
    appels: list = []
    # Le coin est cote depuis 30 jours : rien avant, ni en page ni en sonde.
    bilan = BC.passe_funding(root, now_ms=NOW, poster=_serveur(appels, origine_ms=NOW - 30 * 24 * HEURE),
                             dormir=lambda s: None, univers=None, profondeur_ms=900 * 24 * HEURE)
    assert bilan["origines"] == 1 and bilan["creuses"] == 0
    arriere = len([x for x in appels if x[2] < NOW - 29 * 24 * HEURE])
    assert arriere == 2, "une page + une sonde, puis on s'arrete"

    appels.clear()
    suite = BC.passe_funding(root, now_ms=NOW + HEURE,
                             poster=_serveur(appels, origine_ms=NOW - 30 * 24 * HEURE),
                             dormir=lambda s: None, univers=None, profondeur_ms=900 * 24 * HEURE)
    assert suite["origines"] == 0 and suite["creuses"] == 0, (
        "un coin au bout de son histoire ne doit plus coûter une seule requete : sinon chaque "
        "passage brûlerait du débit dans le vide pour les coins jeunes, qui sont les plus nombreux")


# ─────────────── 5. UN TROU SE SIGNALE, IL NE SE COMBLE PAS EN SILENCE ───────────────
def test_un_trou_est_signale_au_bilan(tmp_path):
    root = _racine(tmp_path, ["TROU"])
    ancien = NOW - 400 * 24 * HEURE
    loin = ancien - 600 * HEURE                        # au-dela d'une page (500 h) : il y a un trou
    _etat_initial(root, recent={"TROU": NOW - HEURE}, ancien={"TROU": ancien})

    def poster(coin, a, b):
        if int(b) < loin + HEURE and int(a) <= loin:
            return [{"coin": coin, "fundingRate": "0.00001", "premium": "0.0", "time": loin}]
        if int(a) <= loin <= int(b):
            return [{"coin": coin, "fundingRate": "0.00001", "premium": "0.0", "time": loin}]
        return []

    bilan = BC.passe_funding(root, now_ms=NOW, poster=poster, dormir=lambda s: None, univers=None,
                             profondeur_ms=900 * 24 * HEURE)
    assert bilan["trous"], (
        "un saut par-dessus un intervalle vide doit etre ECRIT au bilan : combler un trou en "
        "silence serait inventer une continuite, et le labo compterait des heures qui n'existent pas")
    assert bilan["trous"][0]["coin"] == "TROU"


# ─────────────── 6. LE FRONT ARRIERE SE RECONSTRUIT DU RUBAN ───────────────
def test_le_front_arriere_se_relit_du_ruban_quand_l_etat_ne_l_a_pas(tmp_path):
    root = _racine(tmp_path, ["BTC"])
    (root / "runtime" / "history").mkdir(parents=True, exist_ok=True)
    (root / BC.SORTIE_FUNDING).write_text("\n".join(
        json.dumps({"coin": "BTC", "ts_ms": NOW - j * 24 * HEURE, "funding": 1e-5, "interval": "1h"})
        for j in (10, 50, 300)), encoding="utf-8")
    etat = BC.charger_etat(root, (BC.SERIE_FUNDING, BC.SERIE_FUNDING_ANCIEN))
    assert etat[BC.SERIE_FUNDING]["BTC"] == NOW - 10 * 24 * HEURE, "front avant = le plus RECENT"
    assert etat[BC.SERIE_FUNDING_ANCIEN]["BTC"] == NOW - 300 * 24 * HEURE, (
        "front arriere = le plus ANCIEN. Sans cette relecture, creuser repartirait de zero et "
        "redemanderait a la venue des centaines de milliers de points deja detenus")


def test_etat_depuis_ruban_dans_les_deux_sens(tmp_path):
    chemin = tmp_path / "ruban.jsonl"
    chemin.write_text("\n".join(json.dumps({"coin": "X", "ts_ms": t}) for t in (50, 10, 30)),
                      encoding="utf-8")
    assert BC._etat_depuis_ruban(chemin, "ts_ms", sens="max") == {"X": 50}
    assert BC._etat_depuis_ruban(chemin, "ts_ms", sens="min") == {"X": 10}
    assert BC._etat_depuis_ruban(tmp_path / "absent.jsonl", "ts_ms", sens="min") == {}
