"""Chaîne « historique de portefeuille des vaults » : collecte → certification → coffre → étude de persistance.

Les réponses ``vaultDetails`` sont des fixtures à la forme documentée de l'API Hyperliquid
(``portfolio = [[fenêtre, {accountValueHistory, pnlHistory, vlm}], ...]``) : ces tests valident le
code hors ligne, ils ne prétendent pas valider un flux réel.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

import sceller_coffre_local as scl  # noqa: E402

from hl_observer.backtesting import copy_vault_persistence as P  # noqa: E402
from hl_observer.collection import vault_portfolio_history as H  # noqa: E402
from hl_observer.datasets import coffre_certifie as C  # noqa: E402

DAY = 86_400_000
T0 = 1_780_000_000_000 // DAY * DAY          # minuit UTC
NOW = T0 + 500 * DAY
VAULT = "0xca230e816bdb34a46960c2f978a30a563d1ae9e0"


def _outil(nom: str):
    spec = importlib.util.spec_from_file_location(nom, RACINE / "tools" / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _details(points, *, fenetre="allTime", vlm="1000.0"):
    return {"leader": "0xABC", "portfolio": [
        ["day", {}],
        [fenetre, {"accountValueHistory": [[t, str(v)] for t, v, _ in points],
                   "pnlHistory": [[t, str(p)] for t, _, p in points if p is not None], "vlm": vlm}],
        ["perpAllTime", {"accountValueHistory": [[1, "1"]], "pnlHistory": [[1, "0"]]}],   # fenêtre ignorée
    ]}


# ------------------------------------------------------------------ collecteur (module pur)

def test_premiere_passe_rattrape_la_courbe_puis_seuls_les_points_nouveaux_sont_emis():
    points = [(T0 + k * DAY, 1000.0 + k, float(k)) for k in range(5)]
    lignes, eau = H.construire_lignes(VAULT.upper(), _details(points), observed_at_ms=T0 + 5 * DAY)
    assert len(lignes) == 1 and lignes[0]["fenetre"] == "allTime" and lignes[0]["n_points"] == 5
    assert lignes[0]["vault"] == VAULT and lignes[0]["causal_forward_eligible"] is False
    assert lignes[0]["vlm_fenetre_usd"] == 1000.0 and eau == {"allTime": T0 + 4 * DAY}

    # même réponse relue : rien de nouveau, aucune ligne
    assert H.construire_lignes(VAULT, _details(points), observed_at_ms=T0 + 6 * DAY, etat_vault=eau)[0] == []

    plus = points + [(T0 + 5 * DAY, 1010.0, 9.0), (T0 + 5 * DAY + 60_000, 1011.0, 9.5), (T0 + 6 * DAY, 1020.0, 12.0)]
    lignes2, eau2 = H.construire_lignes(VAULT, _details(plus), observed_at_ms=T0 + 6 * DAY, etat_vault=eau)
    # le point à +1 min est plus dense que l'espacement de la fenêtre : écarté, pas déplacé
    assert [p[0] for p in lignes2[0]["points"]] == [T0 + 5 * DAY, T0 + 6 * DAY]
    assert eau == {"allTime": T0 + 4 * DAY} and eau2["allTime"] == T0 + 6 * DAY      # état d'entrée intact


def test_une_grandeur_absente_reste_inconnue_et_un_point_du_futur_est_ecarte():
    points = [(T0, 1000.0, None), (T0 + DAY, 1001.0, 3.0), (T0 + 9 * DAY, 2000.0, 50.0)]
    lignes, _ = H.construire_lignes(VAULT, _details(points), observed_at_ms=T0 + 2 * DAY)
    assert lignes[0]["points"] == [[T0, 1000.0, None], [T0 + DAY, 1001.0, 3.0]]       # jamais de 0 inventé
    assert H.construire_lignes(VAULT, {"portfolio": "illisible"}, observed_at_ms=T0)[0] == []
    assert H.construire_lignes("", _details(points), observed_at_ms=T0 + DAY)[0] == []


def test_fusion_des_fenetres_sans_interpolation():
    fine = {"vault": VAULT, "fenetre": "week", "pnl_base": H.PNL_BASE_CUMUL,
            "points": [[T0 + 2 * DAY, 1002.0, 2.0], [T0 + 3 * DAY, None, 3.0]]}
    grossiere = {"vault": VAULT, "fenetre": "allTime", "points": [[T0, 1000.0, 0.0], [T0 + 3 * DAY, 1003.0, None]]}
    courbe = H.fusionner_points([fine, grossiere])[VAULT]
    assert courbe == [(T0, 1000.0, 0.0), (T0 + 2 * DAY, 1002.0, 2.0), (T0 + 3 * DAY, 1003.0, 3.0)]
    # une fenêtre glissante dont le PnL n'est PAS déclaré cumulé (ancien schéma) : sa valeur de
    # compte est gardée, son PnL relatif n'est jamais mélangé à la courbe cumulée
    ancienne = {"vault": VAULT, "fenetre": "month", "points": [[T0 + DAY, 1001.0, -500.0]]}
    assert H.fusionner_points([ancienne, grossiere])[VAULT][1] == (T0 + DAY, 1001.0, None)


def test_reponse_reelle_le_pnl_de_chaque_fenetre_est_recale_sur_la_base_cumulee():
    """Fixture = réponse vaultDetails RÉELLE du 2026-11-11 (suiveurs retirés). Le PnL des fenêtres
    jour / semaine / mois y repart de 0 au début de la fenêtre : sans recalage, la fusion mélangeait
    des bases différentes et produisait des rendements journaliers absurdes (+1 000 bps/jour)."""
    reel = json.loads((RACINE / "tests" / "fixtures" / "vault_details_reel_20261111.json").read_text(encoding="utf-8"))
    brut = {nom: bloc for nom, bloc in reel["portfolio"]}
    assert all(float(brut[nom]["pnlHistory"][0][1]) == 0.0 for nom in ("day", "week", "month"))
    fenetres = H.extraire_fenetres(reel)
    assert set(fenetres) == {"day", "week", "month", "allTime"}                  # fenêtres « perp… » ignorées
    cumul_final = fenetres["allTime"]["points"][-1][2]
    for nom in ("day", "week", "month"):
        bloc = fenetres[nom]
        assert bloc["pnl_base"] == H.PNL_BASE_CUMUL
        assert bloc["points"][-1][2] == cumul_final                               # même instant, même cumul
        relatif_final = float(brut[nom]["pnlHistory"][-1][1])
        assert abs(bloc["points"][0][2] - (cumul_final - relatif_final)) < 1e-6   # début de fenêtre recalé
        # le recalage ne touche ni aux horodatages ni aux valeurs de compte
        assert [p[0] for p in bloc["points"]] == [p[0] for p in brut[nom]["accountValueHistory"]]
        assert [p[1] for p in bloc["points"]] == [float(p[1]) for p in brut[nom]["accountValueHistory"]]
    lignes, _ = H.construire_lignes(reel["vaultAddress"], reel, observed_at_ms=fenetres["allTime"]["points"][-1][0])
    assert {ligne["fenetre"] for ligne in lignes} == {"day", "week", "month", "allTime"}
    assert all(ligne["is_closed"] is False and ligne["leader_commission"] == 0.1 for ligne in lignes)
    courbe = H.fusionner_points(lignes)[reel["vaultAddress"]]
    pnls = [p for _, _, p in courbe if p is not None]
    # courbe fusionnée cohérente : plus aucun saut de la taille du PnL cumulé entre deux points voisins
    sauts = [abs(b - a) for a, b in zip(pnls, pnls[1:], strict=False)]
    assert max(sauts[-100:]) < 0.5 * abs(cumul_final)


def test_sans_courbe_cumulee_le_pnl_d_une_fenetre_glissante_reste_inconnu():
    mois_seul = {"portfolio": [["month", {"accountValueHistory": [[T0, "1000"], [T0 + DAY, "1010"]],
                                          "pnlHistory": [[T0, "0.0"], [T0 + DAY, "10.0"]], "vlm": "5"}]]}
    bloc = H.extraire_fenetres(mois_seul)["month"]
    assert bloc["pnl_base"] is None and [p[2] for p in bloc["points"]] == [None, None]
    assert [p[1] for p in bloc["points"]] == [1000.0, 1010.0]


def test_le_collecteur_ecrit_l_historique_sans_changer_le_snapshot(tmp_path, monkeypatch):
    m = _outil("collecter_vaults")
    reponses = {"n": 5}

    def faux_post(charge, **_):
        if charge["type"] == "clearinghouseState":
            return {"marginSummary": {"accountValue": "1000"}, "assetPositions": []}
        return _details([(T0 + k * DAY, 1000.0 + k, float(k)) for k in range(reponses["n"])])

    monkeypatch.setattr(m, "_post_info", faux_post)
    m.une_passe(tmp_path, [VAULT], now=(T0 + 10 * DAY) / 1000)
    reponses["n"] = 7
    m.une_passe(tmp_path, [VAULT], now=(T0 + 11 * DAY) / 1000)

    lignes = [json.loads(brut) for brut in (tmp_path / m.SORTIE_HISTORIQUE).read_text(encoding="utf-8").splitlines()]
    assert [ligne["n_points"] for ligne in lignes] == [5, 2] and lignes[1]["observed_at_ms"] == T0 + 11 * DAY
    assert json.loads((tmp_path / m.ETAT_HISTORIQUE).read_text(encoding="utf-8"))[VAULT]["allTime"] == T0 + 6 * DAY
    # tout fichier .jsonl de collecte doit être connu du certificateur (sinon signalé INCONNU)
    assert C.detecter_famille(m.SORTIE_HISTORIQUE.name) == (C.FAMILLE_VAULT_PORTFOLIO, "VAULT_DETAILS_PORTFOLIO")


def _ligne_publique(adresse, *, ferme, tvl="0", cumul=("0.0",), relation="normal"):
    return {"apr": 0.0, "pnls": [["day", ["0.0"]], ["allTime", list(cumul)]],
            "summary": {"name": "x", "vaultAddress": adresse, "leader": "0xl", "tvl": tvl, "isClosed": ferme,
                        "relationship": {"type": relation}, "createTimeMillis": 1}}


def _adr(n: int) -> str:
    return f"0x{n:040x}"


def test_univers_elargi_garde_les_vaults_fermes_qui_ont_compte_gagnants_ou_ruines():
    m = _outil("collecter_vaults")
    liste = [
        _ligne_publique(_adr(1), ferme=False, tvl="1500.0"),                         # ouvert, non négligeable
        _ligne_publique(_adr(2), ferme=False, tvl="999.0"),                          # ouvert, trop petit
        _ligne_publique(_adr(3), ferme=True, cumul=("0.0", "5000.0", "200.0")),      # fermé, a gagné
        _ligne_publique(_adr(4), ferme=True, cumul=("0.0", "-80000.0", "-79000.0")), # fermé, RUINÉ : gardé
        _ligne_publique(_adr(5), ferme=True, cumul=("0.0", "12.0")),                 # fermé, n'a jamais compté
        _ligne_publique(_adr(6), ferme=False, tvl="9e9", relation="child"),          # composant de vault protocole
        _ligne_publique(next(iter(m.VAULTS_EXCLUS)), ferme=False, tvl="9e9"),        # vault de market-making exclu
        {"summary": "illisible"},
    ]
    assert m.univers_historique(liste) == [_adr(1), _adr(3), _adr(4)]
    assert m.univers_historique("illisible") == []


def test_balayage_reprend_au_curseur_sans_rafale_et_survit_aux_pannes(tmp_path, monkeypatch):
    m = _outil("collecter_vaults")
    liste = [_ligne_publique(_adr(n), ferme=True, cumul=("0.0", "5000.0")) for n in range(1, 6)]
    appels = {"liste": 0, "details": []}

    def fausse_liste(**_):
        appels["liste"] += 1
        return liste

    def faux_post(charge, **_):
        appels["details"].append(charge["vaultAddress"])
        if charge["vaultAddress"] == _adr(2):
            raise OSError("réseau coupé")
        return _details([(T0 + k * DAY, 1000.0 + k, float(k)) for k in range(3)])

    monkeypatch.setattr(m, "_get_vaults_public", fausse_liste)
    monkeypatch.setattr(m, "_post_info", faux_post)
    t = (T0 + 10 * DAY) / 1000

    un = m.balayer_historique(tmp_path, max_vaults=2, now=t)
    assert un == {"univers": 5, "lus": 1, "lignes": 1, "echecs": 1, "tour": 0, "curseur": 2}
    deux = m.balayer_historique(tmp_path, max_vaults=2, now=t + 300)
    assert appels["details"] == [_adr(1), _adr(2), _adr(3), _adr(4)] and deux["curseur"] == 4
    trois = m.balayer_historique(tmp_path, max_vaults=2, now=t + 600)          # fin de tour, puis reprise au début
    assert trois["tour"] == 1 and trois["curseur"] == 1 and appels["details"][-2:] == [_adr(5), _adr(1)]
    # le vault 1 est relu au second tour : rien de nouveau, aucune ligne en double
    assert trois["lignes"] == 1 and appels["liste"] == 1                       # liste relue une fois par jour seulement
    lignes = (tmp_path / m.SORTIE_HISTORIQUE).read_text(encoding="utf-8").splitlines()
    assert sorted(json.loads(brut)["vault"] for brut in lignes) == [_adr(1), _adr(3), _adr(4), _adr(5)]
    m.balayer_historique(tmp_path, max_vaults=1, now=t + 25 * 3600)
    assert appels["liste"] == 2

    # liste publique injoignable : l'ancienne est conservée, le balayage continue
    monkeypatch.setattr(m, "_get_vaults_public", lambda **_: (_ for _ in ()).throw(OSError("panne")))
    assert m.balayer_historique(tmp_path, max_vaults=1, now=t + 60 * 3600)["univers"] == 5


# ------------------------------------------------------------------ certificateur

def _ligne(points, **champs):
    base = {"vault": VAULT, "fenetre": "allTime", "observed_at_ms": T0 + 100 * DAY, "points": points,
            "first_ts_ms": points[0][0] if points else None, "ts_ms": points[-1][0] if points else None,
            "n_points": len(points), "vlm_fenetre_usd": 5.0, "source": "VAULT_DETAILS_PORTFOLIO"}
    return {**base, **champs}


def test_certification_accepte_une_tranche_valide_et_rejette_toute_courbe_douteuse():
    bons = [[T0, 1000.0, 0.0], [T0 + DAY, 1001.0, None]]
    kw = {"famille": C.FAMILLE_VAULT_PORTFOLIO, "source": "VAULT_DETAILS_PORTFOLIO", "now_ms": NOW}
    norm, decision, _ = C.certifier_record(_ligne(bons), **kw)
    assert decision == C.PASS and norm["causal_forward_eligible"] is False and norm["ts_ms"] == T0 + DAY

    recale = _ligne(bons, fenetre="month", pnl_base="CUMUL_DEPUIS_CREATION")
    assert C.certifier_record(recale, **kw)[1] == C.PASS
    rejets = {
        # PnL d'une fenêtre glissante non déclaré cumulé (ancien schéma) : jamais admis
        "pnl_base_non_cumulee": _ligne([[T0, 1000.0, 0.0]], fenetre="month"),
        "points_desordonnes": _ligne([[T0 + DAY, 1.0, 1.0], [T0, 1.0, 1.0]]),
        "point_posterieur_a_l_observation": _ligne([[T0 + 200 * DAY, 1.0, 1.0]]),
        "point_sans_grandeur": _ligne([[T0, None, None]]),
        "point_grandeur_invalide": _ligne([[T0, "nan", 1.0]]),
        "point_invalide": _ligne([[T0, 1.0]]),
        "points_absents": _ligne([]),
        "fenetre_inconnue": _ligne(bons, fenetre="perpDay"),
        "vault_absent_ou_invalide": _ligne(bons, vault="abc"),
        "observation_absente": _ligne(bons, observed_at_ms=None),
        "timestamp_futur": _ligne(bons, observed_at_ms=NOW + 60_000),
        "volume_invalide": _ligne(bons, vlm_fenetre_usd=-1.0),
    }
    for raison, ligne in rejets.items():
        assert C.certifier_record(ligne, **kw) == (None, C.QUARANTAINE, raison), raison


def test_une_tranche_reemise_apres_coupure_n_entre_qu_une_fois_au_coffre():
    ligne = json.dumps(_ligne([[T0, 1000.0, 0.0], [T0 + DAY, 1001.0, 1.0]]))
    decisions = [d for _, d, _ in C.certifier_lignes(
        [ligne, ligne], famille=C.FAMILLE_VAULT_PORTFOLIO, source="VAULT_DETAILS_PORTFOLIO", now_ms=NOW)]
    assert decisions == [C.PASS, "DOUBLON"]


# ------------------------------------------------------------------ mesure de persistance

def _courbes(n_vaults=60, jours=420, *, competence_bps=20.0, seed=7, depot=None):
    """Courbes journalières : chaque vault a un rendement moyen propre (sa « compétence ») + du bruit."""
    rng = np.random.default_rng(seed)
    mu = rng.normal(0.0, competence_bps / 1e4, n_vaults)
    courbes = {}
    for i in range(n_vaults):
        valeur, pnl, points = 100_000.0, 0.0, []
        for j in range(jours + 1):
            points.append((T0 + j * DAY, valeur, pnl))
            gain = valeur * (mu[i] + rng.normal(0.0, 0.01))
            valeur, pnl = valeur + gain, pnl + gain
            if depot and i == depot[0] and j == depot[1]:
                valeur += depot[2]
        courbes[f"0x{i:040x}"] = points
    return courbes, mu


def _rapide(**champs):
    return P.PersistenceConfig(bootstrap_samples=300, permutation_samples=300, period_days=(7,),
                               formation_periods=(8,), scores=("moyenne_bayes",), **champs)


def test_une_competence_persistante_est_detectee_et_le_bruit_pur_ne_l_est_pas():
    courbes, _ = _courbes(competence_bps=20.0)
    lents = {vault: 0.01 for vault in courbes}
    etude = P.run_persistence_study(courbes, turnover_per_day=lents, config=_rapide())
    primaire = etude["primary"]
    assert primaire["dates"] >= 40 and primaire["ic_intervalle"][0] > 0
    assert primaire["exces_tete_intervalle_bps_jour"][0] > 0 and primaire["p_placebo_exces_tete"] < 0.05
    assert etude["verdicts"][0]["status"] == "PROMISING" and etude["economically_proven"] is False

    bruit, _ = _courbes(competence_bps=0.0, seed=11)
    verdict = P.run_persistence_study(bruit, turnover_per_day=lents, config=_rapide())["verdicts"][0]
    assert verdict["status"] in {"REJECTED", "MORE_DATA"}        # jamais un faux « prometteur »


def test_le_cout_de_replication_peut_absorber_une_persistance_reelle():
    courbes, _ = _courbes(competence_bps=20.0)
    # rotation de 5 fois le capital par jour : 5 × 6 bps = 30 bps/jour de coût, plus que l'excès
    etude = P.run_persistence_study(courbes, turnover_per_day={v: 5.0 for v in courbes}, config=_rapide())
    assert etude["primary"]["ic_intervalle"][0] > 0
    assert etude["primary"]["tete_nette_bps_jour"] < etude["primary"]["tete_bps_jour"] - 25
    assert etude["verdicts"][0]["status"] == "MORE_DATA"
    # rotation inconnue : le net est inconnu, jamais calculé avec un coût nul
    sans = P.run_persistence_study(courbes, turnover_per_day={}, config=_rapide())
    assert sans["primary"]["tete_nette_bps_jour"] is None and sans["verdicts"][0]["status"] == "MORE_DATA"


def test_la_note_n_utilise_que_le_passe():
    """Métamorphique : modifier les rendements POSTÉRIEURS à une date ne change aucune note de cette date."""
    courbes, _ = _courbes(n_vaults=20, jours=150)
    config = _rapide()
    _, matrice, _ = P.return_matrix(courbes, period_days=7, config=config)
    avant = P.walk_forward(matrice, formation=8, score="moyenne_bayes", config=config)
    cible = avant[2]["t"]
    truquee = matrice.copy()
    truquee[:, cible:] = np.random.default_rng(1).normal(0.5, 0.5, truquee[:, cible:].shape)
    apres = P.walk_forward(truquee, formation=8, score="moyenne_bayes", config=config)
    ligne = next(candidate for candidate in apres if candidate["t"] == cible)
    np.testing.assert_array_equal(ligne["_notes"], avant[2]["_notes"])
    assert ligne["tete"] != avant[2]["tete"]                     # seul le rendement réalisé a changé


def test_un_depot_n_est_pas_un_gain_et_un_point_trop_ancien_reste_inconnu():
    semaine = 7 * DAY
    w0 = (T0 // semaine + 1) * semaine                                   # borne de la grille hebdomadaire UTC
    courbe = [(w0, 100_000.0, 0.0), (w0 + semaine, 151_000.0, 1_000.0)]      # +50 000 de dépôt, +1 000 de gain
    rendements = P.period_returns(courbe, period_days=7)
    (cellule,) = rendements.values()
    assert abs(cellule["ret"] - 1_000.0 / 125_000.0) < 1e-12              # capital moyen = 100k + 25k
    # dernier point connu 3 jours avant la borne : trop ancien pour une période de 7 jours (25 %)
    ancien = [(w0, 100_000.0, 0.0), (w0 + semaine - 3 * DAY, 101_000.0, 1_000.0), (w0 + semaine + 1, 101_000.0, 1_000.0)]
    assert P.period_returns(ancien, period_days=7) == {}
    assert P.period_returns([], period_days=7) == {}


def test_rotation_inconnue_n_est_jamais_nulle():
    courbe = {VAULT: [(T0 + k * DAY, 100_000.0, 0.0) for k in range(31)]}
    obs = T0 + 30 * DAY
    lignes = [{"vault": VAULT, "fenetre": "month", "observed_at_ms": obs, "vlm_fenetre_usd": 3_000_000.0},
              {"vault": VAULT, "fenetre": "day", "observed_at_ms": obs + 1, "vlm_fenetre_usd": 9e9}]
    assert abs(P.turnover_per_day(lignes, courbe)[VAULT] - 1.0) < 1e-9      # la fenêtre « mois » est préférée
    assert P.turnover_per_day([], courbe)[VAULT] is None
    assert P.turnover_per_day([{**lignes[0], "vlm_fenetre_usd": None}], courbe)[VAULT] is None


# ------------------------------------------------------------------ bout en bout

def test_bout_en_bout_collecte_simulee_certification_coffre_etude(tmp_path):
    etude = _outil("etude_copiabilite")
    courbes, _ = _courbes(n_vaults=24, jours=200)
    lignes = []
    for vault, points in courbes.items():
        details = _details(points, vlm="100000.0")
        details["portfolio"].append(["month", {
            "accountValueHistory": [[t, str(v)] for t, v, _ in points[-30:]],
            "pnlHistory": [[t, str(p)] for t, _, p in points[-30:]], "vlm": "60000.0"}])
        lignes += H.construire_lignes(vault, details, observed_at_ms=T0 + 200 * DAY)[0]
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "vault_portfolio_history.jsonl").write_text(
        "".join(json.dumps(ligne) + "\n" for ligne in lignes), encoding="utf-8")
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0          # certification + coffre

    resultat = etude.run_persistance(tmp_path, write=True)

    rapport = resultat["report"]
    assert rapport["inputs"]["vaults_avec_courbe"] == 24 and rapport["inputs"]["vaults_rotation_connue"] == 24
    assert resultat["donnees_consommees"]["vault_portfolio"]["shards"] >= 1
    assert rapport["economically_proven"] is False and rapport["verdicts"][0]["hypothesis"] == P.H_PERSISTENCE
    dossier = tmp_path / etude.REPORT_DIR / resultat["run_id"]
    assert "Persistance de la compétence" in (dossier / "RAPPORT.md").read_text(encoding="utf-8")
    assert etude.verify_ledger(tmp_path / etude.REPORT_DIR / "EXPERIENCES.ndjson")["status"] == "VERIFIED"
    # même corpus, même code, même configuration : même identité d'expérience et mêmes chiffres
    encore = etude.run_persistance(tmp_path, write=False)
    assert encore["identity"]["experiment_id"] == resultat["identity"]["experiment_id"]
    assert encore["report"]["primary"] == rapport["primary"]


def test_sans_courbe_au_coffre_l_etude_dit_non_mesurable_sans_rien_inventer(tmp_path):
    etude = _outil("etude_copiabilite")
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "hl_allmids_tape.jsonl").write_text(json.dumps({"ts_ms": NOW - 5, "mids": {"BTC": 1.0}}) + "\n",
                                                encoding="utf-8")
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    resultat = etude.run_persistance(tmp_path, write=True)
    assert resultat["status"] == "UNMEASURABLE" and "report" not in resultat
    assert not (tmp_path / etude.REPORT_DIR / "EXPERIENCES.ndjson").exists()     # coffre encore vide...


def test_la_limite_d_univers_dit_ce_que_les_donnees_contiennent():
    """Une limite périmée trompe autant qu'un chiffre faux : « survivants » ne s'affiche que si c'est vrai."""
    from hl_observer.backtesting import copy_vault_persistence as P

    assert "survivants" in P._limite_univers(69, None) and "survivants" in P._limite_univers(69, 0)
    texte = P._limite_univers(2333, 1859)
    assert "2333" in texte and "1859 fermés" in texte and "survivants" not in texte


# ------------------------------------------------------------------ note robuste, égalités, ordre du tableau

def _fenetre(moyennes, ecarts, colonnes=8):
    """Fenêtre de formation dont chaque ligne a EXACTEMENT la moyenne et l'écart-type demandés."""
    z = np.linspace(-1.0, 1.0, colonnes)
    z = (z - z.mean()) / z.std(ddof=1)
    return np.asarray(moyennes)[:, None] + np.asarray(ecarts)[:, None] * z[None, :]


def test_la_note_bayesienne_ne_degenere_plus_quand_quelques_vaults_tres_volatils_dominent_le_bruit():
    """Défaut réel du 2026-11-11 : variance entre vaults < bruit moyen -> toutes les notes égales
    (57 dates sur 86), donc un « meilleur quantile » choisi par l'ordre des adresses."""
    rng = np.random.default_rng(3)
    moyennes = rng.normal(0.002, 0.004, 40)
    ecarts = np.full(40, 0.01)
    ecarts[:3] = 5.0                                              # trois vaults au bruit énorme
    fenetre = _fenetre(moyennes, ecarts)
    bruit = ecarts ** 2 / 8
    assert np.var(moyennes, ddof=1) < bruit.mean()               # l'ancien estimateur valait 0 ici
    notes = P.score_formation(fenetre, "moyenne_bayes")
    assert not np.isnan(notes).any() and np.unique(notes).size == 40      # un vrai classement
    # les vaults précis gardent leur ordre ; les trois vaults bruités sont ramenés vers le centre
    precis = np.arange(3, 40)
    assert (np.argsort(notes[precis]) == np.argsort(moyennes[precis])).all()
    assert np.abs(notes[:3] - np.median(notes)).max() < np.abs(moyennes[precis] - np.median(notes)).max()


def test_sans_dispersion_detectable_la_note_est_la_limite_de_la_formule_pas_une_egalite_generale():
    moyennes = np.array([0.0010, 0.0011, 0.0009, 0.0012, 0.0008, 0.0010, 0.00105, 0.00095, 0.00115, 0.0009])
    ecarts = np.array([0.02, 0.05, 0.03, 0.08, 0.02, 0.04, 0.06, 0.03, 0.05, 0.07])
    notes = P.score_formation(_fenetre(moyennes, ecarts), "moyenne_bayes")
    bruit = ecarts ** 2 / 8
    centre = float((moyennes / bruit).sum() / (1.0 / bruit).sum())
    attendu = (moyennes - centre) / bruit                        # écart au centre pondéré par la précision
    assert np.unique(notes).size == notes.size
    assert (np.argsort(notes) == np.argsort(attendu)).all()


def test_un_vault_inactif_n_est_pas_note_quelle_que_soit_la_note():
    fenetre = _fenetre([0.001, 0.0, 0.002, -0.001], [0.01, 0.0, 0.02, 0.015])
    for score in P.SCORES:
        notes = P.score_formation(fenetre, score)
        assert np.isnan(notes[1]) and not np.isnan(notes[[0, 2, 3]]).any(), score
    with pytest.raises(ValueError):
        P.score_formation(fenetre, "inconnue")


def test_des_notes_egales_ne_sont_jamais_departagees_par_l_ordre_du_tableau():
    config = P.PersistenceConfig(min_vaults_per_date=5, top_fraction=0.4)
    rendements = np.array([[0.05], [-0.01], [0.02], [0.00], [-0.03]])
    # notes toutes égales : le « meilleur quantile » vaut l'univers, la date est signalée dégénérée
    plates = P.evaluer_notes(rendements, {0: np.full(5, 1.0)}, config=config)[0]
    assert plates["note_degeneree"] and np.isnan(plates["ic"])
    assert plates["tete"] == pytest.approx(plates["univers"]) == pytest.approx(plates["queue"])
    resume = P.summarize([plates], period_days=7, niveau=0.95, config=config)
    assert resume["dates_note_degeneree"] == 1 and resume["dates_ic_indefini"] == 1
    assert resume["exces_tete_bps_jour"] == pytest.approx(0.0)
    # égalité au seuil : 2 places, 1 vault strictement devant, 3 ex æquo se partagent la place restante
    notes = np.array([3.0, 2.0, 2.0, 2.0, 1.0])
    partiel = P.evaluer_notes(rendements, {0: notes}, config=config)[0]
    assert partiel["tete"] == pytest.approx((0.05 + np.mean([-0.01, 0.02, 0.00])) / 2)
    assert partiel["queue"] == pytest.approx((-0.03 + np.mean([-0.01, 0.02, 0.00])) / 2)
    assert not partiel["note_degeneree"]
    # métamorphique : permuter les vaults ne change rien
    ordre = np.array([4, 2, 0, 3, 1])
    permute = P.evaluer_notes(rendements[ordre], {0: notes[ordre]}, config=config)[0]
    for cle in ("tete", "queue", "univers", "ic"):
        assert permute[cle] == pytest.approx(partiel[cle]), cle
    # coût : même pondération, et un coût inconnu chez un retenu rend le net inconnu
    couts = np.array([0.001, 0.002, 0.002, 0.002, 0.0])
    net = P.evaluer_notes(rendements, {0: notes}, config=config, cout_par_periode=couts)[0]
    assert net["tete_nette"] == pytest.approx(partiel["tete"] - (0.001 + 0.002) / 2)
    couts[2] = np.nan
    assert P.evaluer_notes(rendements, {0: notes}, config=config, cout_par_periode=couts)[0]["tete_nette"] is None


def test_renommer_les_vaults_ne_change_aucun_resultat():
    """Métamorphique : l'ordre des adresses n'est pas une information. Avec la note v1, renommer les
    vaults changeait le « meilleur quantile » des dates dégénérées."""
    courbes, _ = _courbes(n_vaults=40, jours=300, competence_bps=5.0, seed=5)
    # quelques vaults au bruit énorme (cas réel) et un vault inactif
    rng = np.random.default_rng(9)
    for i, vault in enumerate(sorted(courbes)[:4]):
        valeur, pnl, points = 100_000.0, 0.0, []
        for j in range(301):
            points.append((T0 + j * DAY, valeur, pnl))
            gain = 0.0 if i == 3 else valeur * rng.normal(0.0, 0.25)
            valeur, pnl = max(20_000.0, valeur + gain), pnl + gain
        courbes[vault] = points
    renommees = {f"0x{(2 ** 80 - int(vault, 16)):040x}": points for vault, points in courbes.items()}
    assert sorted(renommees) != sorted(courbes)
    for score in P.SCORES:
        config = P.PersistenceConfig(bootstrap_samples=50, permutation_samples=50, period_days=(7,),
                                     formation_periods=(8,), scores=(score,))
        a = P.run_persistence_study(courbes, config=config)["primary"]
        b = P.run_persistence_study(renommees, config=config)["primary"]
        assert a["dates"] == b["dates"] > 20 and a["dates_note_degeneree"] == 0, score
        for cle in ("ic_moyen", "exces_tete_bps_jour", "tete_bps_jour", "univers_bps_jour", "ecart_tete_queue_bps_jour"):
            assert a[cle] == pytest.approx(b[cle], abs=1e-9), (score, cle)
