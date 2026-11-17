"""ATTRIBUTION DES EMPLACEMENTS `userFills` : l'indice du poll, l'ordre du labo, la stabilité.

Défaut mesuré le 17/11/2026 (voir `hl_observer.collection.slots_userfills`) : « actif » voulait dire
« vu en direct », donc un leader sans emplacement ne pouvait pas le devenir. 30 reprises d'activité
sur 49 n'ont jamais été vues en direct ; 61,0 % des fills de ces rafales manquaient.

Ces tests verrouillent : la lecture bornée du ruban du poll (et ses motifs quand elle ne sait pas
lire), l'exclusion des leaders `ARCHIVE`, l'ordre des classes, le maintien des titulaires, le repli
EXACT sur la rotation historique quand l'indice manque, et le journal des pages.
"""
from __future__ import annotations

import importlib.util
import inspect
import json
from pathlib import Path

import pytest

from hl_observer.collection import slots_userfills as S

_ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "collecter_userfills_vaults_pour_slots", _ROOT / "tools" / "collecter_userfills_vaults.py")
U = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(U)

MAINTENANT = 1_800_000_000_000
A = "0x" + "a" * 40
B = "0x" + "b" * 40
C = "0x" + "c" * 40


def _ligne(vault: str, *, il_y_a_min: float, recu_il_y_a_min: float | None = None, **extra) -> str:
    temps = int(MAINTENANT - il_y_a_min * 60_000)
    recu = int(MAINTENANT - (il_y_a_min if recu_il_y_a_min is None else recu_il_y_a_min) * 60_000)
    return json.dumps({"coin": "BTC", "time": temps, "dir": "Open Long", "vault": vault,
                       "source": "LIVE_POLL", "received_at_ms": recu, **extra})


def _ruban(root: Path, lignes: list[str]) -> Path:
    chemin = root / S.RUBAN_POLL
    chemin.parent.mkdir(parents=True, exist_ok=True)
    with open(chemin, "w", encoding="utf-8", newline="") as flux:
        flux.write("\n".join(lignes) + "\n")
    return chemin


# ───────────────────────── lecture du ruban du poll ─────────────────────────

def test_compte_les_fills_recents_par_leader(tmp_path):
    _ruban(tmp_path, [_ligne(A, il_y_a_min=1), _ligne(A, il_y_a_min=5), _ligne(B, il_y_a_min=44),
                      _ligne(C, il_y_a_min=46, recu_il_y_a_min=1)])
    comptes, diag = S.activite_poll_par_vault(tmp_path, maintenant_ms=MAINTENANT)
    assert comptes == {A: 2, B: 1}, "C a tradé il y a 46 min : hors fenêtre, même reçu à l'instant"
    assert diag["motif"] == S.MOTIF_OK and diag["frais"] is True
    assert diag["lignes"] == 4 and diag["lignes_dans_la_fenetre"] == 3


def test_les_adresses_sont_ramenees_en_minuscules(tmp_path):
    _ruban(tmp_path, [_ligne(A.upper().replace("0X", "0x"), il_y_a_min=1)])
    comptes, _ = S.activite_poll_par_vault(tmp_path, maintenant_ms=MAINTENANT)
    assert comptes == {A: 1}


def test_l_ordre_des_cles_dans_la_ligne_ne_compte_pas(tmp_path):
    ligne = json.dumps({"vault": A, "received_at_ms": MAINTENANT - 1000, "time": MAINTENANT - 2000})
    _ruban(tmp_path, [ligne])
    comptes, _ = S.activite_poll_par_vault(tmp_path, maintenant_ms=MAINTENANT)
    assert comptes == {A: 1}


def test_les_lignes_illisibles_sont_ignorees_sans_tout_perdre(tmp_path):
    _ruban(tmp_path, ["pas du json", json.dumps({"vault": A}), json.dumps({"time": MAINTENANT}),
                      _ligne(B, il_y_a_min=1)])
    comptes, diag = S.activite_poll_par_vault(tmp_path, maintenant_ms=MAINTENANT)
    assert comptes == {B: 1} and diag["lignes"] == 1


def test_ruban_absent_un_zero_qui_dit_pourquoi(tmp_path):
    comptes, diag = S.activite_poll_par_vault(tmp_path, maintenant_ms=MAINTENANT)
    assert comptes == {} and diag["motif"] == S.MOTIF_ABSENT and diag["frais"] is False


def test_ruban_sans_ligne_exploitable(tmp_path):
    _ruban(tmp_path, ["{}", "rien"])
    comptes, diag = S.activite_poll_par_vault(tmp_path, maintenant_ms=MAINTENANT)
    assert comptes == {} and diag["motif"] == S.MOTIF_VIDE


def test_un_poll_ARRETE_ne_prouve_l_inactivite_de_personne(tmp_path):
    """Dernière ligne reçue il y a 11 min : le poll ne voit plus rien. Son compte est jeté."""
    _ruban(tmp_path, [_ligne(A, il_y_a_min=12), _ligne(A, il_y_a_min=11)])
    comptes, diag = S.activite_poll_par_vault(tmp_path, maintenant_ms=MAINTENANT)
    assert comptes == {}, "un compte tiré d'un poll arrêté serait pris pour une vérité"
    assert diag["motif"] == S.MOTIF_PERIME and diag["frais"] is False


def test_la_limite_de_fraicheur_est_incluse(tmp_path):
    _ruban(tmp_path, [_ligne(A, il_y_a_min=S.FRAICHEUR_POLL_MS / 60_000)])
    comptes, diag = S.activite_poll_par_vault(tmp_path, maintenant_ms=MAINTENANT)
    assert comptes == {A: 1} and diag["frais"] is True


def test_la_lecture_est_BORNEE_et_le_dit_quand_la_fenetre_n_est_pas_couverte(tmp_path):
    lignes = [_ligne(A, il_y_a_min=40 - i * 0.13) for i in range(300)]    # la dernière : il y a ~1 min
    chemin = _ruban(tmp_path, lignes)
    budget = chemin.stat().st_size // 10
    comptes, diag = S.activite_poll_par_vault(tmp_path, maintenant_ms=MAINTENANT, budget_octets=budget)
    assert diag["octets_lus"] <= budget
    assert 0 < comptes[A] < 300, "seule la queue est lue"
    assert diag["motif"] == S.MOTIF_PARTIEL, "le compte est un minorant : il faut le dire"


def test_une_queue_qui_couvre_toute_la_fenetre_n_est_pas_dite_partielle(tmp_path):
    lignes = [_ligne(B, il_y_a_min=120 - i * 0.01) for i in range(2000)] + [_ligne(A, il_y_a_min=1)]
    chemin = _ruban(tmp_path, lignes)
    comptes, diag = S.activite_poll_par_vault(
        tmp_path, maintenant_ms=MAINTENANT, budget_octets=chemin.stat().st_size // 2)
    assert comptes == {A: 1} and diag["motif"] == S.MOTIF_OK


def test_la_premiere_ligne_coupee_par_la_borne_est_laissee(tmp_path):
    chemin = _ruban(tmp_path, [_ligne(A, il_y_a_min=2), _ligne(B, il_y_a_min=1)])
    seconde = len((_ligne(B, il_y_a_min=1) + "\n").encode())
    comptes, _ = S.activite_poll_par_vault(tmp_path, maintenant_ms=MAINTENANT, budget_octets=seconde + 20)
    assert comptes == {B: 1}, "une ligne tronquée ne doit ni compter ni faire échouer"
    assert chemin.stat().st_size > seconde + 20


# ───────────────────────── plan du labo, leaders du poll, indice ─────────────────────────

def _plan(root: Path, classes: dict[str, str]) -> None:
    chemin = root / S.BESOINS_COLLECTE
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps({"leaders": [
        {"unit": adresse, "cadence": classe, "addresses": [adresse]} for adresse, classe in classes.items()
    ]}), encoding="utf-8")


def test_plan_absent_ou_illisible_rend_un_plan_vide(tmp_path):
    assert S.charger_plan(tmp_path) == {}
    (tmp_path / S.BESOINS_COLLECTE).parent.mkdir(parents=True)
    (tmp_path / S.BESOINS_COLLECTE).write_text("{pas du json", encoding="utf-8")
    assert S.charger_plan(tmp_path) == {}


def test_plan_lu_en_minuscules(tmp_path):
    _plan(tmp_path, {A: "PRIORITAIRE", B: "ARCHIVE"})
    assert S.charger_plan(tmp_path) == {A: "PRIORITAIRE", B: "ARCHIVE"}


def test_leaders_du_poll_absents_illisibles_ou_mal_formes(tmp_path):
    assert S.leaders_suivis_par_le_poll(tmp_path) == set()
    chemin = tmp_path / S.LEADERS_DU_POLL
    chemin.parent.mkdir(parents=True)
    chemin.write_text("[1, 2]", encoding="utf-8")
    assert S.leaders_suivis_par_le_poll(tmp_path) == set()
    chemin.write_text(json.dumps({A.upper().replace("0X", "0x"): {}, "meta": 1}), encoding="utf-8")
    assert S.leaders_suivis_par_le_poll(tmp_path) == {A}


def test_indice_complet(tmp_path):
    _ruban(tmp_path, [_ligne(A, il_y_a_min=1)])
    _plan(tmp_path, {A: "PRIORITAIRE"})
    (tmp_path / S.LEADERS_DU_POLL).write_text(json.dumps({A: {}, B: {}}), encoding="utf-8")
    indice = S.indice_d_attribution(tmp_path, maintenant_ms=MAINTENANT)
    assert indice["activite_poll"] == {A: 1} and indice["plan"] == {A: "PRIORITAIRE"}
    assert indice["leaders_du_poll"] == {A, B} and indice["diagnostic"]["frais"] is True


def test_poll_perime_ne_COUVRE_plus_personne(tmp_path):
    """Sinon les silencieux « couverts » ne tourneraient plus, et personne ne les surveillerait."""
    _ruban(tmp_path, [_ligne(A, il_y_a_min=30)])
    (tmp_path / S.LEADERS_DU_POLL).write_text(json.dumps({A: {}, B: {}}), encoding="utf-8")
    indice = S.indice_d_attribution(tmp_path, maintenant_ms=MAINTENANT)
    assert indice["activite_poll"] == {} and indice["leaders_du_poll"] == set()
    assert indice["diagnostic"]["motif"] == S.MOTIF_PERIME


def test_l_indice_ne_LEVE_JAMAIS(tmp_path, monkeypatch):
    def casse(*_a, **_k):
        raise RuntimeError("disque en feu")

    monkeypatch.setattr(S, "activite_poll_par_vault", casse)
    indice = S.indice_d_attribution(tmp_path)
    assert indice["activite_poll"] == {} and indice["leaders_du_poll"] == set()
    assert indice["diagnostic"]["frais"] is False


# ───────────────────────── activité effective et ordre ─────────────────────────

def test_l_activite_est_le_MAXIMUM_du_direct_et_du_poll():
    indice = {"activite_poll": {"0xcand1": 9, "0xcand2": 2}, "plan": {}}
    effet = S.activite_effective(["0xCAND1", "0xCAND2", "0xCAND3"], {"0xCAND1": 3, "0xCAND2": 5}, indice)
    assert effet == {"0xCAND1": 9, "0xCAND2": 5}, "pas de somme : les deux voient les mêmes fills"


def test_un_leader_ARCHIVE_n_est_jamais_promu_par_le_poll():
    indice = {"activite_poll": {"0xbot": 4000, "0xlent": 1}, "plan": {"0xbot": "ARCHIVE", "0xlent": "PRIORITAIRE"}}
    assert S.activite_effective(["0xBOT", "0xLENT"], {}, indice) == {"0xLENT": 1}


def test_ce_qu_on_voit_en_direct_d_un_ARCHIVE_n_est_pas_retire():
    indice = {"activite_poll": {"0xbot": 4000}, "plan": {"0xbot": "ARCHIVE"}}
    assert S.activite_effective(["0xBOT"], {"0xBOT": 7}, indice) == {"0xBOT": 7}


def test_sans_indice_l_activite_est_celle_du_direct():
    assert S.activite_effective(["0xA"], {"0xA": 2, "0xB": 0}, None) == {"0xA": 2}


def test_ordre_des_classes_puis_titulaires_puis_ordre_recu():
    plan = {"0xp1": "PRIORITAIRE", "0xp2": "PRIORITAIRE", "0xs1": "STANDARD", "0xd1": "DECOUVERTE"}
    recus = [{"vault": v} for v in ("0xS1", "0xINCONNU", "0xP1", "0xD1", "0xP2")]
    ordre = [c["vault"] for c in S.ordonner_les_actifs(recus, plan=plan, en_place=["0xp2"])]
    assert ordre == ["0xP2", "0xP1", "0xS1", "0xINCONNU", "0xD1"]


def test_un_titulaire_STANDARD_cede_a_un_nouveau_PRIORITAIRE():
    plan = {"0xp": "PRIORITAIRE", "0xs": "STANDARD"}
    ordre = [c["vault"] for c in S.ordonner_les_actifs([{"vault": "0xS"}, {"vault": "0xP"}],
                                                       plan=plan, en_place=["0xS"])]
    assert ordre == ["0xP", "0xS"], "le budget suit le plan du labo avant l'ancienneté"


def test_ordre_stable_titulaires_a_leur_rang_puis_nouveaux():
    selection = [{"vault": v} for v in ("0xN1", "0xC", "0xA", "0xN2", "0xB")]
    ordre = [c["vault"] for c in S.ordre_stable(selection, ["0xa", "0xb", "0xc", "0xparti"])]
    assert ordre == ["0xA", "0xB", "0xC", "0xN1", "0xN2"]


def test_meme_ensemble_meme_page_quel_que_soit_l_ordre_recu():
    page = ["0xa", "0xb", "0xc"]
    for recu in (["0xc", "0xa", "0xb"], ["0xb", "0xc", "0xa"]):
        assert [c["vault"] for c in S.ordre_stable([{"vault": v} for v in recu], page)] == page


# ───────────────────────── emplacements libres ─────────────────────────

def _rotation_historique(silencieux, libres, rotation_index):
    depart = (max(0, int(rotation_index)) * libres) % len(silencieux)
    return [silencieux[(depart + k) % len(silencieux)] for k in range(min(libres, len(silencieux)))]


@pytest.mark.parametrize("n,libres", [(1, 3), (3, 3), (7, 3), (12, 5), (40, 7)])
def test_sans_liste_du_poll_c_est_EXACTEMENT_la_rotation_historique(n, libres):
    silencieux = [{"vault": f"0xsil{i:02d}"} for i in range(n)]
    for index in range(0, 30):
        attendu = _rotation_historique(silencieux, libres, index)
        for indice in (None, {}, {"leaders_du_poll": set()}):
            assert S.choisir_les_libres(silencieux, libres=libres, rotation_index=index,
                                        indice=indice) == attendu


def test_les_non_couverts_tournent_les_couverts_restent():
    silencieux = [{"vault": f"0xsil{i}"} for i in range(8)]
    indice = {"leaders_du_poll": {f"0xsil{i}" for i in range(8) if i not in (2, 5)}}
    pages = [tuple(c["vault"] for c in S.choisir_les_libres(silencieux, libres=3, rotation_index=k,
                                                            indice=indice)) for k in range(6)]
    assert all(page == pages[0] for page in pages), "page identique d'un cycle à l'autre"
    assert pages[0][:2] == ("0xsil2", "0xsil5"), "les deux non couverts gardent le direct"
    assert pages[0][2] == "0xsil0"


def test_plus_de_non_couverts_que_de_places_ils_tournent_entre_eux_PAR_PALIERS():
    silencieux = [{"vault": f"0xsil{i}"} for i in range(9)]
    indice = {"leaders_du_poll": {"0xsil0", "0xsil1"}}
    vus, changements, precedent = set(), 0, None
    for k in range(12 * S.PALIER_ROTATION_HORS_POLL):
        choisis = [c["vault"] for c in S.choisir_les_libres(silencieux, libres=2, rotation_index=k, indice=indice)]
        assert len(choisis) == 2 and not {"0xsil0", "0xsil1"} & set(choisis)
        vus.update(choisis)
        changements += precedent is not None and choisis != precedent
        precedent = choisis
    assert vus == {f"0xsil{i}" for i in range(2, 9)}, "aucun non-couvert n'est oublié par la rotation"
    assert changements == 11, "un changement par palier, pas un par cycle"


def test_PRODUCTION_19h21_deux_non_couverts_pour_UN_emplacement_n_alternent_plus_a_chaque_cycle():
    """Mesuré le 17/11 : `feab64` et `e67dbf` alternaient toutes les 150 s, et chaque alternance
    reconstruisait les dix connexions."""
    silencieux = [{"vault": "0xfeab64"}, {"vault": "0xe67dbf"}, {"vault": "0xcouvert"}]
    indice = {"leaders_du_poll": {"0xcouvert"}}
    choix = [S.choisir_les_libres(silencieux, libres=1, rotation_index=4_800 + k, indice=indice)[0]["vault"]
             for k in range(2 * S.PALIER_ROTATION_HORS_POLL)]
    assert set(choix) == {"0xfeab64", "0xe67dbf"}, "les deux gardent leur tour de découverte"
    assert sum(1 for a, b in zip(choix, choix[1:]) if a != b) == 1,         "un seul passage de relais en deux paliers (30 min chacun), au lieu d'un par cycle"


def test_parmi_les_couverts_le_titulaire_garde_sa_place():
    silencieux = [{"vault": v} for v in ("0xa", "0xb", "0xc")]
    indice = {"leaders_du_poll": {"0xa", "0xb", "0xc"}}
    choisis = [c["vault"] for c in S.choisir_les_libres(silencieux, libres=1, rotation_index=4,
                                                        indice=indice, en_place=["0xC"])]
    assert choisis == ["0xc"]


def test_aucune_place_libre_ou_aucun_silencieux():
    assert S.choisir_les_libres([{"vault": "0xa"}], libres=0, rotation_index=1, indice={}) == []
    assert S.choisir_les_libres([], libres=3, rotation_index=1, indice={}) == []


# ───────────────────────── journal des pages ─────────────────────────

def test_une_ligne_par_cycle_avec_qui_etait_abonne(tmp_path):
    indice = {"activite_poll": {"0xa": 4}, "plan": {"0xa": "PRIORITAIRE"},
              "diagnostic": {"motif": S.MOTIF_OK, "frais": True}}
    roles = [("0xA", "CORE", "retenu"), ("0xB", "CANDIDAT_OBSERVE", "observé")]
    assert S.journaliser_page(tmp_path, page=7, roles=roles, maintenue=False, indice=indice,
                              maintenant_ms=MAINTENANT) is True
    assert S.journaliser_page(tmp_path, page=8, roles=roles, maintenue=True, indice=indice,
                              maintenant_ms=MAINTENANT + 150_000) is True
    lignes = [json.loads(l) for l in (tmp_path / S.JOURNAL_PAGES).read_text(encoding="utf-8").splitlines()]
    assert [l["page"] for l in lignes] == [7, 8] and [l["maintenue"] for l in lignes] == [False, True]
    premiere = lignes[0]
    assert premiere["schema_version"] == S.SCHEMA_PAGES and premiere["ts_ms"] == MAINTENANT
    assert premiere["vaults"][0] == {"vault": "0xA", "role": "CORE", "classe_labo": "PRIORITAIRE",
                                     "fills_poll_fenetre": 4}
    assert premiere["vaults"][1]["classe_labo"] is None and premiere["vaults"][1]["fills_poll_fenetre"] == 0
    assert premiere["paper_read_only"] is True and premiere["real_execution"] is False
    assert premiere["indice_poll"] == S.MOTIF_OK and premiere["poll_frais"] is True


def test_le_journal_n_est_pas_un_flux_de_collecte():
    assert S.JOURNAL_PAGES.suffix == ".ndjson"


def test_une_ecriture_impossible_rend_False_sans_lever(tmp_path):
    (tmp_path / S.JOURNAL_PAGES).mkdir(parents=True)      # un dossier à la place du fichier
    assert S.journaliser_page(tmp_path, page=1, roles=[("0xA", "CORE", "")], maintenue=False) is False


# ───────────────────────── câblage dans le collecteur ─────────────────────────

def _ecrire_scores(root: Path, n_cands: int = 12) -> Path:
    d = root / "runtime" / "data"
    d.mkdir(parents=True, exist_ok=True)
    classement = [{"vault": "0xCORE1", "retenu": True, "facteurs": {}},
                  {"vault": "0xCORE2", "retenu": True, "facteurs": {}}]
    classement += [{"vault": "0xCAND%02d" % i, "retenu": False,
                    "facteurs": {"copyabilite": 0.9 - i * 0.01, "anciennete_j": 60, "drawdown_pct": 10}}
                   for i in range(n_cands)]
    (d / "vaults_scores.json").write_text(json.dumps({"classement": classement}), encoding="utf-8")
    return root


def _indice(actifs: dict[str, int] | None = None, plan: dict[str, str] | None = None,
            suivis: set[str] | None = None, frais: bool = True) -> dict:
    return {"activite_poll": actifs or {}, "plan": plan or {}, "leaders_du_poll": suivis or set(),
            "diagnostic": {"motif": S.MOTIF_OK if frais else S.MOTIF_PERIME, "frais": frais}}


def _page(root, **kw):
    return [v for v, _r, _w in U.vaults_et_roles(root, **kw)]


def test_sans_indice_le_collecteur_est_INCHANGE(tmp_path):
    """Les autres appelants (`vaults_suivis`, outils) n'ont pas d'indice : rien ne doit bouger."""
    _ecrire_scores(tmp_path)
    for index in range(6):
        page = _page(tmp_path, rotation_index=index)
        assert page[:2] == ["0xCORE1", "0xCORE2"] and len(page) == U.MAX_SLOTS
        attendu = _rotation_historique(["0xCAND%02d" % i for i in range(12)], 8, index)
        assert page[2:] == attendu


def test_un_leader_vu_SEULEMENT_par_le_poll_obtient_un_emplacement(tmp_path):
    """LE défaut du 17/11 : sans emplacement il ne pouvait pas être vu, donc jamais promu."""
    _ecrire_scores(tmp_path, n_cands=40)
    cible = "0xCAND37"
    assert all(cible not in _page(tmp_path, rotation_index=k) for k in range(3)), \
        "hypothèse du test : la rotation seule ne tombe pas dessus tout de suite"
    tous = {"0xcand%02d" % i for i in range(40)}
    indice = _indice({"0xcand37": 12}, suivis=tous)
    for index in range(3):
        assert cible in _page(tmp_path, rotation_index=index, indice=indice)


def test_un_ARCHIVE_actif_au_poll_ne_prend_pas_d_emplacement_par_ce_biais(tmp_path):
    _ecrire_scores(tmp_path, n_cands=40)
    tous = {"0xcand%02d" % i for i in range(40)}
    indice = _indice({"0xcand37": 5000}, plan={"0xcand37": "ARCHIVE"}, suivis=tous)
    assert "0xCAND37" not in _page(tmp_path, rotation_index=0, indice=indice)


def test_les_PRIORITAIRES_passent_avant_les_plus_bruyants(tmp_path):
    _ecrire_scores(tmp_path, n_cands=40)
    tous = {"0xcand%02d" % i for i in range(40)}
    actifs = {"0xcand%02d" % i: 1000 + i for i in range(10, 20)}          # dix STANDARD très actifs
    actifs.update({"0xcand30": 1, "0xcand31": 1})                          # deux PRIORITAIRES discrets
    plan = {"0xcand%02d" % i: "STANDARD" for i in range(10, 20)}
    plan.update({"0xcand30": "PRIORITAIRE", "0xcand31": "PRIORITAIRE"})
    page = _page(tmp_path, rotation_index=0, indice=_indice(actifs, plan, tous))
    assert {"0xCAND30", "0xCAND31"} <= set(page) and len(page) == U.MAX_SLOTS
    assert page[2:4] == ["0xCAND30", "0xCAND31"], "juste après les deux retenus"


def test_la_page_est_IDENTIQUE_d_un_cycle_a_l_autre_quand_rien_ne_change(tmp_path):
    """Même page → le collecteur garde ses connexions : plus de trou toutes les 150 s."""
    _ecrire_scores(tmp_path, n_cands=40)
    tous = {"0xcand%02d" % i for i in range(40)}
    indice = _indice({"0xcand05": 3, "0xcand22": 9}, suivis=tous)
    page = tuple(_page(tmp_path, rotation_index=0, indice=indice))
    for index in range(1, 8):
        suivante = tuple(_page(tmp_path, rotation_index=index, indice=indice, en_place=page))
        assert suivante == page
        page = suivante


def test_un_titulaire_actif_n_est_pas_deloge_par_un_nouveau_de_meme_classe(tmp_path):
    _ecrire_scores(tmp_path, n_cands=40)
    tous = {"0xcand%02d" % i for i in range(40)}
    actifs = {"0xcand%02d" % i: 1 for i in range(20, 28)}                  # 8 titulaires discrets
    page = tuple(_page(tmp_path, rotation_index=0, indice=_indice(actifs, suivis=tous)))
    assert set(page[2:]) == {"0xCAND%02d" % i for i in range(20, 28)}
    actifs["0xcand01"] = 9999                                              # un nouveau, bien plus bruyant
    suivante = tuple(_page(tmp_path, rotation_index=1, indice=_indice(actifs, suivis=tous), en_place=page))
    assert suivante == page, "ne jamais lâcher un leader qui trade maintenant"


def test_poll_PERIME_le_collecteur_retombe_sur_la_rotation_historique(tmp_path):
    _ecrire_scores(tmp_path, n_cands=40)
    perime = _indice(frais=False)
    for index in range(8):
        assert _page(tmp_path, rotation_index=index, indice=perime) == _page(tmp_path, rotation_index=index)


def test_jamais_plus_de_dix_emplacements(tmp_path):
    _ecrire_scores(tmp_path, n_cands=60)
    tous = {"0xcand%02d" % i for i in range(60)}
    indice = _indice({"0xcand%02d" % i: 5 for i in range(60)}, suivis=tous)
    page = _page(tmp_path, rotation_index=3, indice=indice)
    assert len(page) == U.MAX_SLOTS and len(set(page)) == U.MAX_SLOTS


def test_le_superviseur_lit_l_indice_HORS_de_la_boucle_et_journalise_chaque_cycle():
    """L'indice lu dans la boucle retarderait l'horodatage des fills reçus pendant la lecture."""
    source = inspect.getsource(U._superviser_rotation_vaults)
    assert "await asyncio.to_thread(SLOTS.indice_d_attribution, root)" in source
    assert "vaults_et_roles(root, rotation_index=page, indice=indice, en_place=running_vaults)" in source
    assert "SLOTS.journaliser_page(root, page=page, roles=roles, maintenue=maintenue, indice=indice)" in source
    assert source.index("SLOTS.journaliser_page(") < source.index("if maintenue:"), \
        "la page reconduite doit être journalisée elle aussi"


# ───────────────────────── le VRAI superviseur, hors ligne ─────────────────────────
#
# Les tests ci-dessus prouvent les fonctions. Celui-ci fait tourner la coroutine de production
# `_superviser_rotation_vaults` : c'est elle qui a été retouchée, et elle n'avait jamais été
# exécutée ailleurs que dans le collecteur en service. Seuls le réseau et les sockets sont remplacés.

def _hex(i: int) -> str:
    return "0x" + f"{i:040x}"


def _racine_de_production(root: Path, *, n_cands: int, poll_frais: bool) -> list[str]:
    import time as _time

    d = root / "runtime" / "data"
    d.mkdir(parents=True, exist_ok=True)
    cands = [_hex(100 + i) for i in range(n_cands)]
    classement = [{"vault": _hex(1), "retenu": True, "facteurs": {}},
                  {"vault": _hex(2), "retenu": True, "facteurs": {}}]
    classement += [{"vault": v, "retenu": False,
                    "facteurs": {"copyabilite": 0.9 - i * 0.01, "anciennete_j": 60, "drawdown_pct": 10}}
                   for i, v in enumerate(cands)]
    (d / "vaults_scores.json").write_text(json.dumps({"classement": classement}), encoding="utf-8")
    if poll_frais:
        maintenant = int(_time.time() * 1000)
        lignes = [json.dumps({"coin": "BTC", "time": maintenant - 1000, "vault": cands[17],
                              "source": "LIVE_POLL", "received_at_ms": maintenant - 900})]
        with open(root / S.RUBAN_POLL, "w", encoding="utf-8", newline="") as flux:
            flux.write("\n".join(lignes) + "\n")
        (root / S.LEADERS_DU_POLL).write_text(json.dumps({v: {} for v in cands}), encoding="utf-8")
    return cands


def _faire_tourner_le_superviseur(root: Path, monkeypatch, *, duree_s: float = 0.6) -> list[tuple]:
    import asyncio

    sockets_ouvertes: list[tuple] = []

    async def _dort(*_a, **_k):
        await asyncio.sleep(3600)

    async def _fausse_socket(_root, groupe, _file, sid="A"):
        sockets_ouvertes.append((sid, tuple(groupe)))
        await asyncio.sleep(3600)

    monkeypatch.setattr(U, "ROLE_ROTATION_SECONDS", 0.05)
    monkeypatch.setattr(U.CV, "rafraichir_univers_public", lambda _root: {"vaults": []})
    monkeypatch.setattr(U, "_refresh_copy_vault_prewarm_once", lambda *_a, **_k: None)
    monkeypatch.setattr(U, "_refresh_copy_vault_prewarm_periodically", _dort)
    monkeypatch.setattr(U, "_garde_reconciliation_rest", _dort)
    monkeypatch.setattr(U, "_userfills_multiplex", _fausse_socket)
    monkeypatch.setattr(U, "_univers_observation", lambda _root: [])
    monkeypatch.setattr(U, "charger_sentinelles", lambda _root: [])

    async def _principal():
        try:
            await asyncio.wait_for(U._superviser_rotation_vaults(root, asyncio.Queue()), timeout=duree_s)
        except asyncio.TimeoutError:
            pass

    asyncio.run(_principal())
    return sockets_ouvertes


def _journal(root: Path) -> list[dict]:
    return [json.loads(l) for l in (root / S.JOURNAL_PAGES).read_text(encoding="utf-8").splitlines()]


def test_SUPERVISEUR_poll_frais_la_page_est_reconduite_et_les_sockets_ne_sont_ouvertes_qu_une_fois(
        tmp_path, monkeypatch):
    cands = _racine_de_production(tmp_path, n_cands=40, poll_frais=True)
    sockets = _faire_tourner_le_superviseur(tmp_path, monkeypatch)
    pages = _journal(tmp_path)
    assert len(pages) >= 4, "plusieurs cycles ont tourné"
    assert pages[0]["maintenue"] is False and all(p["maintenue"] is True for p in pages[1:]), \
        "même page → connexions gardées : plus de trou toutes les 150 s"
    assert len({tuple(v["vault"] for v in p["vaults"]) for p in pages}) == 1
    assert len(sockets) == 2, f"deux sockets de 5, ouvertes UNE fois ; vu {len(sockets)}"
    abonnes = [v["vault"] for v in pages[0]["vaults"]]
    assert len(abonnes) == U.MAX_SLOTS
    assert cands[17] in abonnes, "le leader vu SEULEMENT par le poll a son emplacement"
    assert pages[0]["indice_poll"] in (S.MOTIF_OK, S.MOTIF_PARTIEL) and pages[0]["poll_frais"] is True
    promu = next(v for v in pages[0]["vaults"] if v["vault"] == cands[17])
    assert promu["fills_poll_fenetre"] == 1


def test_SUPERVISEUR_sans_poll_la_rotation_historique_continue_et_le_journal_le_dit(tmp_path, monkeypatch):
    cands = _racine_de_production(tmp_path, n_cands=40, poll_frais=False)
    sockets = _faire_tourner_le_superviseur(tmp_path, monkeypatch)
    pages = _journal(tmp_path)
    assert len(pages) >= 3
    assert all(p["maintenue"] is False for p in pages), "sans indice, la page tourne comme avant"
    assert all(p["indice_poll"] == S.MOTIF_ABSENT and p["poll_frais"] is False for p in pages)
    vus = {v["vault"] for p in pages for v in p["vaults"]} - {_hex(1), _hex(2)}
    assert len(vus) > 8, "la découverte par rotation n'est pas gelée par un indice absent"
    assert vus <= set(cands)
    assert len(sockets) == 2 * len(pages), "chaque page reconstruite rouvre ses deux sockets"
    attendues = [tuple(v for v, _r, _w in U.vaults_et_roles(tmp_path, rotation_index=k))
                 for k in range(len(pages))]
    assert [tuple(v["vault"] for v in p["vaults"]) for p in pages] == attendues, \
        "page pour page, c'est la règle historique"
