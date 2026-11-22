"""L'auto-amélioration du moteur : ce qu'elle a le DROIT de faire, et ce qu'elle refuse.

Un système qui « apprend tout seul » se trompe de quatre façons classiques : il s'arrête de
mesurer dès que le résultat l'arrange, il réessaie ce qui a déjà perdu, il prend un coup de
chance pour une découverte, il promeut trop vite. Chaque test tient l'une de ces portes fermée —
plus l'isolation : régler une cohorte ne doit jamais en déplacer une autre, et un test ne doit
jamais pouvoir écrire dans le vrai runtime.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from hl_observer.experimental import auto_amelioration as A
from hl_observer.experimental import cohortes as CO
from hl_observer.experimental import raw_shadow_variantes as RS

PERDANT = [-0.05, -0.03, -0.06, -0.04] * 5          # 20 cycles, tous perdants
GAGNANT = [0.05, 0.03, 0.06, 0.04] * 5
BRUIT = [0.30, -0.30] * 10                          # moyenne nulle : rien à conclure


def _cycles(root: Path, pnls: list[float], cohorte: CO.Cohorte = CO.RAW_PROBE) -> None:
    """Ajoute des cycles clôturés à une cohorte, sous SA configuration en vigueur."""
    chemin = CO._p(cohorte, root, "ledger.jsonl")
    chemin.parent.mkdir(parents=True, exist_ok=True)
    label = CO._params_trigger(root, cohorte)["variante"]
    empreinte = CO.config_hash_courant(cohorte, root)
    with chemin.open("a", encoding="utf-8") as f:
        for i, pnl in enumerate(pnls):
            f.write(json.dumps({"evt": "CLOSE", "realized_usd": pnl, "notional_usd": 10.0, "ts_ms": i,
                                "trigger_version": label, "config_hash": empreinte}) + "\n")


def _auto(root: Path, cohorte: CO.Cohorte = CO.RAW_PROBE) -> dict | None:
    chemin = CO._p(cohorte, root, "auto.json")
    return json.loads(chemin.read_text(encoding="utf-8")) if chemin.is_file() else None


def _journal(root: Path) -> list[dict]:
    return A.lire_journal(root)


# ---------------------------------------------------------------- le moteur : un réglage par cohorte
def test_regler_le_bac_a_sable_ne_deplace_ni_ALPHA_ni_PROBE(tmp_path) -> None:
    avant = {c.nom: (CO._params_trigger(tmp_path, c), CO.config_hash_courant(c, tmp_path)) for c in CO.COHORTES.values()}
    CO._p(CO.RAW_PROBE, tmp_path, "auto.json").parent.mkdir(parents=True, exist_ok=True)
    CO._p(CO.RAW_PROBE, tmp_path, "auto.json").write_text(json.dumps(
        {"variante": "auto-x", "frac_tvl": 0.008, "stop_bps": 80.0, "horizon_ms": 900_000.0}), encoding="utf-8")
    assert CO._params_trigger(tmp_path, CO.RAW_PROBE)["frac_tvl"] == 0.008
    assert CO._cfg_defaut(CO.RAW_PROBE, tmp_path)["stop_bps"] == 80.0
    assert CO._cfg_defaut(CO.RAW_PROBE, tmp_path)["horizon_ms"] == 900_000.0
    assert CO.config_hash_courant(CO.RAW_PROBE, tmp_path) != avant["RAW_PROBE"][1]      # nouvel échantillon pour LUI
    for cohorte in (CO.ALPHA, CO.PROBE):
        assert (CO._params_trigger(tmp_path, cohorte), CO.config_hash_courant(cohorte, tmp_path)) == avant[cohorte.nom]


def test_sans_fichier_auto_rien_ne_change_pour_personne(tmp_path) -> None:
    for cohorte in CO.COHORTES.values():
        assert CO._params_trigger(tmp_path, cohorte) == CO._params_trigger(tmp_path)
        assert CO._cfg_defaut(cohorte, tmp_path) == CO._cfg_defaut(cohorte)


def test_le_stop_et_l_horizon_auto_ne_touchent_jamais_ALPHA_ni_PROBE(tmp_path) -> None:
    for cohorte in (CO.ALPHA, CO.PROBE):
        CO._p(cohorte, tmp_path, "auto.json").parent.mkdir(parents=True, exist_ok=True)
        CO._p(cohorte, tmp_path, "auto.json").write_text(json.dumps({"stop_bps": 999.0, "horizon_ms": 1.0}), encoding="utf-8")
        assert CO._cfg_defaut(cohorte, tmp_path) == CO._cfg_defaut(cohorte)       # leurs stops viennent des tables par coin


# ---------------------------------------------------------------- ne pas regarder en cours de route
def test_sans_aucun_cycle_on_continue_et_rien_n_est_ecrit(tmp_path) -> None:
    etat = A.une_passe(tmp_path, appliquer=True)
    assert etat["decision"]["action"] == "CONTINUER" and etat["cycles_de_la_config_en_vigueur"] == 0
    assert _auto(tmp_path) is None and _journal(tmp_path) == []


def test_on_ne_change_jamais_de_variante_au_milieu_d_un_echantillon(tmp_path) -> None:
    _cycles(tmp_path, PERDANT[:19])                 # 19 cycles perdants : tentant d'arrêter là
    etat = A.une_passe(tmp_path, appliquer=True)
    assert etat["decision"]["action"] == "CONTINUER" and "19/20" in etat["decision"]["motif"]
    assert _auto(tmp_path) is None


# ---------------------------------------------------------------- apprendre de ses erreurs
def _verdicts_perdants(variantes) -> dict:
    cycles = [{"evt": "CLOSE", "realized_usd": pnl, "trigger_version": A.etiquette(v, 1)}
              for v in variantes for pnl in PERDANT]
    return A.juger(A.bilan_par_variante(cycles))


def test_un_echantillon_perdant_fait_choisir_une_voisine_qui_ne_differe_que_d_un_parametre() -> None:
    """La logique séquentielle reste calculée et publiée : la voisine ne change qu'UN paramètre."""
    d = A.decider(n_cycles_courants=A.ECHANTILLON, verdicts=_verdicts_perdants([A.BASE]), fantome={})
    assert d["action"] == "ESSAYER"
    v = tuple(d["variante"])
    assert sum(1 for a, b in zip(v, A.BASE) if a != b) == 1 and v[0] != A.BASE[0]        # le seuil d'abord


def test_aucune_variante_n_est_choisie_deux_fois_et_tout_perdre_mene_a_l_abstention() -> None:
    essayees = [A.BASE]
    for _ in range(A.VARIANTES_MAX + 5):
        d = A.decider(n_cycles_courants=A.ECHANTILLON, verdicts=_verdicts_perdants(essayees), fantome={})
        if d["action"] != "ESSAYER":
            break
        v = tuple(d["variante"])
        assert v not in essayees
        essayees.append(v)
    assert d["action"] == "S_ABSTENIR" and len(essayees) <= A.VARIANTES_MAX
    assert {v[1] for v in essayees} > {A.BASE[1]} and {v[2] for v in essayees} > {A.BASE[2]}


def test_la_boucle_sequentielle_n_ecrit_plus_le_reglage_du_bac_a_sable(tmp_path) -> None:
    """Depuis le 22/11, seul l'apprentissage PARALLÈLE arme le bac à sable."""
    _cycles(tmp_path, PERDANT)
    etat = A.une_passe(tmp_path, appliquer=True)
    assert etat["decision"]["action"] == "ESSAYER"          # calculée et publiée...
    assert _auto(tmp_path) is None                           # ... mais pas appliquée


def test_le_journal_est_chaine(tmp_path) -> None:
    A._journaliser(tmp_path, {"decision": {"action": "X"}})
    A._journaliser(tmp_path, {"decision": {"action": "Y"}})
    lignes = _journal(tmp_path)
    assert len(lignes) == 2 and lignes[0]["precedente"] == "0" * 64
    assert lignes[1]["precedente"] == lignes[0]["empreinte"]


# ---------------------------------------------------------------- ne pas prendre la chance pour une découverte
def test_un_resultat_bruite_reste_indecis_puis_est_abandonne_apres_trois_echantillons() -> None:
    assert A.juger({A.BASE: {"pnls": BRUIT, "generations": {1}}})[A.BASE]["statut"] == "INDECISE"
    assert A.juger({A.BASE: {"pnls": BRUIT * 3, "generations": {1, 2, 3}}})[A.BASE]["statut"] == "ABANDONNEE"


def test_l_intervalle_s_elargit_avec_le_nombre_de_variantes_comparees() -> None:
    valeurs = [0.10, -0.02, 0.06, 0.01, 0.09, -0.04, 0.07, 0.03, 0.05, -0.01] * 2
    seul, parmi_cinq = A.intervalle(valeurs, comparaisons=1), A.intervalle(valeurs, comparaisons=5)
    assert parmi_cinq["bas"] < seul["bas"] and parmi_cinq["haut"] > seul["haut"]
    assert A.intervalle([0.1, 0.2])["bas"] is None            # moins de 5 cycles : aucun intervalle, aucun verdict


def test_on_explore_autour_de_la_meilleure_variante_connue() -> None:
    meilleure = (0.004, A.BASE[1], A.BASE[2])
    verdicts = A.juger({A.BASE: {"pnls": PERDANT, "generations": {0}}, meilleure: {"pnls": GAGNANT, "generations": {1}}})
    d = A.decider(n_cycles_courants=A.ECHANTILLON, verdicts=verdicts, fantome={})
    v = tuple(d["variante"])
    assert d["action"] == "ESSAYER" and sum(1 for a, b in zip(v, meilleure) if a != b) == 1     # voisine de la GAGNANTE


def test_quand_tout_est_explore_une_gagnante_est_exploitee() -> None:
    gagnante = (0.004, 40.0, 3_600_000.0)
    donnees = {v: {"pnls": PERDANT, "generations": {1}} for v in [A.BASE] + A.voisines(A.BASE, {}) + A.voisines(gagnante, {})}
    donnees[gagnante] = {"pnls": GAGNANT, "generations": {1}}
    d = A.decider(n_cycles_courants=A.ECHANTILLON, verdicts=A.juger(donnees), fantome={})
    assert d["action"] == "EXPLOITER" and tuple(d["variante"]) == gagnante and d["generation"] == 2


# ---------------------------------------------------------------- la mesure fantôme ordonne, sans prouver
def test_la_mesure_fantome_ordonne_les_essais_seulement_si_elle_est_assez_fournie(tmp_path) -> None:
    grille = [{"frac_tvl": 0.008, "bucket_age": "<1s", "n": 40, "net_bps_moyen": 12.0},
              {"frac_tvl": 0.0005, "bucket_age": "<1s", "n": 5, "net_bps_moyen": 500.0},      # trop peu : ignorée
              {"frac_tvl": 0.004, "bucket_age": ">30s", "n": 900, "net_bps_moyen": 90.0}]     # âge non exécutable
    (tmp_path / RS.SORTIE_RELPATH).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / RS.SORTIE_RELPATH).write_text(json.dumps({"grille": grille}), encoding="utf-8")
    fantome = A.mesure_fantome(tmp_path)
    assert set(fantome) == {0.008, 0.0005}
    assert A.voisines(A.BASE, fantome)[0] == (0.008, A.BASE[1], A.BASE[2])


# ---------------------------------------------------------------- échelle de promotion
def _echelle(verdicts=None, reglages=None, pnls=None, retro=None) -> list[dict]:
    return A.decider_echelle(verdicts_bac=verdicts or {}, reglages=reglages or {}, pnls_promus=pnls or {},
                             retrogradees=retro or {})


GAGNANTE_40 = A.juger({(0.004, 40.0, 3_600_000.0): {"pnls": GAGNANT * 2, "generations": {1, 2}}})
GAGNANTE_20 = A.juger({(0.004, 40.0, 3_600_000.0): {"pnls": GAGNANT, "generations": {1}}})
PROMU = {"variante": "promu-f0.004-n1", "frac_tvl": 0.004}


def test_une_gagnante_sur_un_seul_echantillon_n_est_pas_promue() -> None:
    assert _echelle(GAGNANTE_20) == []


def test_une_gagnante_confirmee_monte_d_UN_niveau_a_la_fois() -> None:
    actions = _echelle(GAGNANTE_40)
    assert actions == [{"action": "PROMOUVOIR", "cohorte": CO.PROBE.nom, "frac_tvl": 0.004, "motif": "seuil prouve au niveau inferieur"}]


def test_ALPHA_attend_que_PROBE_ait_fait_sa_propre_preuve() -> None:
    assert _echelle(GAGNANTE_40, {CO.PROBE.nom: PROMU}, {CO.PROBE.nom: GAGNANT[:19]}) == []          # 19 cycles : pas encore
    assert _echelle(GAGNANTE_40, {CO.PROBE.nom: PROMU}, {CO.PROBE.nom: BRUIT}) == []                 # 20 cycles indécis : non
    actions = _echelle(GAGNANTE_40, {CO.PROBE.nom: PROMU}, {CO.PROBE.nom: GAGNANT})
    assert [(a["action"], a["cohorte"]) for a in actions] == [("PROMOUVOIR", CO.ALPHA.nom)]


def test_une_cohorte_promue_qui_perd_est_retrogradee_et_ce_seuil_n_y_remonte_plus() -> None:
    actions = _echelle(GAGNANTE_40, {CO.PROBE.nom: PROMU}, {CO.PROBE.nom: PERDANT[:10]})
    assert [(a["action"], a["cohorte"], a["frac_tvl"]) for a in actions] == [("RETROGRADER", CO.PROBE.nom, 0.004)]
    assert _echelle(GAGNANTE_40, {}, {}, {CO.PROBE.nom: {0.004}}) == []                              # jamais re-promu
    # ... et rien ne monte vers ALPHA depuis un niveau qui vient de perdre
    assert all(a["cohorte"] != CO.ALPHA.nom for a in actions)


def test_la_promotion_ecrit_le_reglage_de_PROBE_seulement_et_la_retrogradation_le_neutralise(tmp_path) -> None:
    _cycles(tmp_path, GAGNANT)                                       # v1 gagne sur 20 cycles
    assert all(a["action"] != "PROMOUVOIR" for a in A.une_passe(tmp_path, appliquer=True)["echelle"])
    # on force le second échantillon de la MÊME variante (génération 2)
    CO._p(CO.RAW_PROBE, tmp_path, "auto.json").write_text(json.dumps(
        {"variante": A.etiquette(A.BASE, 2), "frac_tvl": A.BASE[0], "stop_bps": A.BASE[1], "horizon_ms": A.BASE[2]}), encoding="utf-8")
    _cycles(tmp_path, GAGNANT)
    etat = A.une_passe(tmp_path, appliquer=True)
    assert [(a["action"], a["cohorte"]) for a in etat["echelle"]] == [("PROMOUVOIR", CO.PROBE.nom)]
    assert _auto(tmp_path, CO.PROBE)["frac_tvl"] == A.BASE[0] and _auto(tmp_path, CO.ALPHA) is None
    assert CO._params_trigger(tmp_path, CO.PROBE)["variante"].startswith("promu-")
    assert CO._params_trigger(tmp_path, CO.ALPHA)["variante"] == "v1"                                 # ALPHA intacte
    # PROBE perd 10 cycles sous ce réglage -> rétrogradée, fichier neutralisé (pas supprimé), jamais re-promue
    _cycles(tmp_path, PERDANT[:10], CO.PROBE)
    etat = A.une_passe(tmp_path, appliquer=True)
    assert [(a["action"], a["cohorte"]) for a in etat["echelle"]] == [("RETROGRADER", CO.PROBE.nom)]
    assert "frac_tvl" not in _auto(tmp_path, CO.PROBE) and CO._params_trigger(tmp_path, CO.PROBE)["variante"] == "v1"
    assert A.une_passe(tmp_path, appliquer=True)["echelle"] == []


# ---------------------------------------------------------------- honnêteté et isolation
def test_un_cycle_d_etiquette_inconnue_n_est_attribue_a_personne(tmp_path) -> None:
    chemin = CO._p(CO.RAW_PROBE, tmp_path, "ledger.jsonl")
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps({"evt": "CLOSE", "realized_usd": 9.0, "trigger_version": "bricolage"}) + "\n"
                      + json.dumps({"evt": "OPEN", "realized_usd": 9.0, "trigger_version": "v1"}) + "\n", encoding="utf-8")
    etat = A.une_passe(tmp_path)
    assert etat["cycles_non_attribues"] == 1 and etat["verdicts"] == {}


def test_sous_le_vrai_runtime_rien_n_est_ecrit_sans_l_autorisation_du_collecteur(tmp_path, monkeypatch) -> None:
    (tmp_path / CO.MARQUEUR_RUNTIME).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / CO.MARQUEUR_RUNTIME).write_text("x", encoding="utf-8")
    monkeypatch.setattr(CO, "_RUNTIME_AUTORISE", None)
    _cycles(tmp_path, PERDANT)
    etat = A.une_passe(tmp_path, appliquer=True)
    assert etat["decision"]["action"] == "ESSAYER" and etat["appliquee"] is False
    assert etat["refus"] == "ECRITURE_NON_AUTORISEE_HORS_COLLECTEUR"
    assert _auto(tmp_path) is None and not (tmp_path / A.DOSSIER).exists()


def test_sans_appliquer_la_passe_est_en_lecture_seule(tmp_path) -> None:
    _cycles(tmp_path, PERDANT)
    etat = A.une_passe(tmp_path)
    assert etat["decision"]["action"] == "ESSAYER" and etat["appliquee"] is False
    assert _auto(tmp_path) is None and not (tmp_path / A.DOSSIER).exists()


# ---------------------------------------------------------------- branchement dans le moteur
def test_le_moteur_appelle_la_boucle_dans_sa_passe_periodique_et_une_panne_n_y_casse_rien(tmp_path, monkeypatch, capsys) -> None:
    import ast

    from tools import collecter_userfills_vaults as USERFILLS

    arbre = ast.parse(Path(USERFILLS.__file__).read_text(encoding="utf-8"))
    passe = next(n for n in arbre.body if isinstance(n, ast.FunctionDef) and n.name == "_promotion_une_passe")
    appels = [n.func.id for n in ast.walk(passe) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)]
    assert "_auto_amelioration_une_passe" in appels        # sinon le moteur n'apprend plus, sans le dire

    _cycles(tmp_path, PERDANT)
    USERFILLS._auto_amelioration_une_passe(tmp_path)        # elle tourne et publie son état...
    assert (tmp_path / A.DOSSIER / "etat.json").is_file()
    assert capsys.readouterr().out == ""                    # ... et se tait quand rien n'est armé

    def _panne(*_a, **_k):
        raise RuntimeError("boum")

    monkeypatch.setattr(A, "une_passe", _panne)             # ... et une panne ne remonte jamais jusqu'aux fills
    USERFILLS._auto_amelioration_une_passe(tmp_path)
    assert "[auto-amelioration] err boum" in capsys.readouterr().out


# ---------------------------------------------------------------- gardes ajoutées après preuve par injection
def test_changer_SEULEMENT_le_stop_ou_l_horizon_ouvre_un_nouvel_echantillon(tmp_path) -> None:
    """Sinon le moteur resterait figé sur l'ancien compte de cycles : la variante ne serait jamais mesurée."""
    origine = CO.config_hash_courant(CO.RAW_PROBE, tmp_path)
    chemin = CO._p(CO.RAW_PROBE, tmp_path, "auto.json")
    chemin.parent.mkdir(parents=True, exist_ok=True)
    empreintes = set()
    for reglage in ({"stop_bps": 80.0}, {"horizon_ms": 900_000.0}):
        chemin.write_text(json.dumps(reglage), encoding="utf-8")
        empreintes.add(CO.config_hash_courant(CO.RAW_PROBE, tmp_path))
    assert origine not in empreintes and len(empreintes) == 2


def test_la_recherche_est_bornee_meme_quand_rien_ne_tranche() -> None:
    """Des résultats toujours indécis offrent sans fin de nouvelles voisines : c'est le plafond qui arrête."""
    donnees: dict = {A.BASE: {"pnls": list(BRUIT), "generations": {0}}}
    actions = []
    for _ in range(200):
        d = A.decider(n_cycles_courants=A.ECHANTILLON, verdicts=A.juger(donnees), fantome={})
        actions.append(d["action"])
        if d["action"] != "ESSAYER":
            break
        b = donnees.setdefault(tuple(d["variante"]), {"pnls": [], "generations": set()})
        b["pnls"] += BRUIT
        b["generations"].add(d["generation"])
    assert actions[-1] == "S_ABSTENIR"                      # elle s'arrête d'elle-même
    assert len(donnees) == A.VARIANTES_MAX                  # exactement au plafond, pas les 45 combinaisons
    assert all(len(b["generations"]) <= A.GENERATIONS_MAX for b in donnees.values())


def test_le_depot_papier_HLP_est_marque_au_plus_une_fois_par_jour_et_sans_jamais_casser(tmp_path, monkeypatch, capsys) -> None:
    import subprocess
    import types

    from tools import collecter_userfills_vaults as USERFILLS

    appels = []

    def _faux(commande, **_k):
        appels.append(commande)
        return types.SimpleNamespace(returncode=0, stdout="  derniere marque : ok\n")

    monkeypatch.setattr(subprocess, "run", _faux)
    monkeypatch.setattr(USERFILLS, "_HLP_PAPIER_DERNIERE_S", None)
    assert USERFILLS._hlp_papier_une_passe(tmp_path, maintenant_s=0.0) is True
    assert USERFILLS._hlp_papier_une_passe(tmp_path, maintenant_s=300.0) is False            # 5 min plus tard : rien
    assert USERFILLS._hlp_papier_une_passe(tmp_path, maintenant_s=86_400.0) is True          # le lendemain : oui
    assert len(appels) == 2 and appels[0][-3:] == ["--lire", "--segment", "papier"]
    assert "[hlp-papier] rc=0" in capsys.readouterr().out

    def _panne(*_a, **_k):
        raise OSError("reseau coupe")

    monkeypatch.setattr(subprocess, "run", _panne)
    assert USERFILLS._hlp_papier_une_passe(tmp_path, maintenant_s=200_000.0) is True         # tentee, ratee, avalee
    assert "[hlp-papier] err reseau coupe" in capsys.readouterr().out
    assert USERFILLS._hlp_papier_une_passe(tmp_path, maintenant_s=200_300.0) is False        # pas de relance en boucle


def _classement(root: Path, n: int, retenus: int = 2) -> list[str]:
    vaults = [f"0x{i:040x}" for i in range(1, n + 1)]
    lignes = [{"vault": v, "retenu": i < retenus, "composite": 1.0 - i / 100,
               "facteurs": {"anciennete_j": 10, "drawdown_pct": 90, "copyabilite": 0.1}}
              for i, v in enumerate(vaults)]
    chemin = root / "runtime" / "data" / "vaults_scores.json"
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(json.dumps({"classement": lignes}), encoding="utf-8")
    return vaults


def test_le_bac_a_sable_suit_tout_vault_score_quel_que_soit_son_rang(tmp_path) -> None:
    """Défaut réel du 22/11 : seuls les 8 premiers étaient suivis, les comptes écoutés en direct
    étaient aux rangs 30 à 47 — 22 déclenchements, 22 refus, zéro cycle à juger."""
    vaults = _classement(tmp_path, 47)
    suivis = CO._vaults_cohorte(CO.RAW_PROBE, tmp_path)
    assert vaults[46] in suivis and vaults[30] in suivis and len(suivis) == 47
    assert "0x" + "f" * 40 not in suivis                                  # non scoré : observation-only


def test_elargir_le_bac_a_sable_n_elargit_ni_ALPHA_ni_PROBE(tmp_path) -> None:
    vaults = _classement(tmp_path, 47)
    assert CO._vaults_cohorte(CO.ALPHA, tmp_path) <= set(vaults[:2])     # au plus les retenus stricts
    assert vaults[46] not in CO._vaults_cohorte(CO.PROBE, tmp_path)      # drawdown 90 % : hors sécurité


def test_sans_classement_le_bac_a_sable_ne_suit_personne(tmp_path) -> None:
    assert CO.vaults_scores_tous(tmp_path) == set()
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / "runtime" / "data" / "vaults_scores.json").write_text("pas du json", encoding="utf-8")
    assert CO.vaults_scores_tous(tmp_path) == set() and CO._vaults_cohorte(CO.RAW_PROBE, tmp_path) == set()


def test_zero_cycle_s_explique_par_les_decisions_du_journal(tmp_path) -> None:
    import importlib.util
    spec = importlib.util.spec_from_file_location("outil_auto", Path(__file__).resolve().parents[1] / "tools" / "auto_amelioration.py")
    outil = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(outil)
    assert outil.decisions_sur_les_ouvertures(tmp_path) is None            # journal absent : pas de « aucun refus » inventé
    lignes = ([{"cohorte": "RAW_PROBE", "dir": "Open Long", "decision": "REFUS:VAULT_NON_SUIVI"}] * 3
              + [{"cohorte": "RAW_PROBE", "dir": "Open Short", "decision": "AUCUN"}] * 2
              + [{"cohorte": "RAW_PROBE", "dir": "Close Long", "decision": "AUCUN"}] * 5      # une clôture n'est pas une ouverture
              + [{"cohorte": "ALPHA", "dir": "Open Long", "decision": "REFUS:VAULT_NON_SUIVI"}] * 4)
    chemin = tmp_path / outil.JOURNAL_DES_FILLS
    chemin.parent.mkdir(parents=True)
    chemin.write_text("\n".join(json.dumps(x) for x in lignes) + "\npas du json\n", encoding="utf-8")
    vu = outil.decisions_sur_les_ouvertures(tmp_path)
    assert vu == {"cohorte": "RAW_PROBE", "ouvertures_vues": 5, "illisibles": 1,
                  "par_decision": {"REFUS:VAULT_NON_SUIVI": 3, "AUCUN": 2}}
