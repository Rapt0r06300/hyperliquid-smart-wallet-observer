"""Ordres en attente des leaders : collecte (forme réelle), certification, coffre, étude du labo.

Les messages d'essai reprennent la forme RÉELLE observée le 2026-11-11 (``openOrders`` en WebSocket,
``frontendOpenOrders`` en REST) ; les valeurs sont synthétiques."""
from __future__ import annotations

import asyncio
import gzip
import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd
import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

import sceller_coffre_local as scl  # noqa: E402

from hl_observer.backtesting import copy_vault_order_intent as I  # noqa: E402
from hl_observer.collection import ordres_leader as O  # noqa: E402
from hl_observer.datasets import coffre_certifie as C  # noqa: E402
from hl_observer.datasets import couverture_donnees as R  # noqa: E402

JOUR = 86_400_000
T0 = 1_780_000_000_000 // JOUR * JOUR
NOW = T0 + 30 * JOUR
LEADER = "0x07fd993f0fa3a185f7207adccd29f7a87404689d"
AUTRE = "0x654016a8c9fcf0c4cb7ed6078aba21f7f399f7b7"


def _outil(nom: str):
    spec = importlib.util.spec_from_file_location(nom, RACINE / "tools" / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


def _ordre(oid, coin="WLD", side="A", px="0.7302", sz="5000.0", *, pose=T0, reduce_only=False, declenche=False,
           type_ordre="Limit", tif="Gtc", trigger_px="0.0"):
    """Un ordre tel que l'API le rend (champs observés le 2026-11-11)."""
    return {"coin": coin, "side": side, "limitPx": px, "sz": sz, "oid": oid, "timestamp": pose,
            "triggerCondition": "N/A", "isTrigger": declenche, "triggerPx": trigger_px, "children": [],
            "isPositionTpsl": False, "reduceOnly": reduce_only, "orderType": type_ordre, "origSz": sz,
            "tif": tif if not declenche else None, "cloid": None}


def _message(ordres, user=LEADER, dex=""):
    return {"dex": dex, "user": user, "orders": ordres}


# ------------------------------------------------------------------ collecte (module pur)

def test_un_ordre_reel_est_normalise_et_son_role_reconnu():
    entree = O.normaliser_ordre(_ordre(463750203814))
    assert entree == {"coin": "WLD", "side": "A", "px": 0.7302, "sz": 5000.0, "orig_sz": 5000.0,
                      "oid": 463750203814, "ts_ms": T0, "type": "Limit", "tif": "Gtc", "reduce_only": False,
                      "is_trigger": False, "trigger_px": None, "trigger_condition": "N/A",
                      "is_position_tpsl": False, "genre": O.ENTREE_LIMITE}
    assert O.normaliser_ordre(_ordre(2, reduce_only=True))["genre"] == O.SORTIE_LIMITE
    stop = O.normaliser_ordre(_ordre(3, declenche=True, type_ordre="Stop Market", trigger_px="0.65"))
    assert stop["genre"] == O.STOP and stop["trigger_px"] == 0.65 and stop["tif"] is None
    assert O.normaliser_ordre(_ordre(4, declenche=True, type_ordre="Take Profit Market", trigger_px="0.9"))["genre"] \
        == O.PRISE_DE_PROFIT_DECLENCHEE
    # identité native du marché : jamais de mise en majuscules
    assert O.normaliser_ordre(_ordre(5, coin="kPEPE"))["coin"] == "kPEPE"
    assert O.normaliser_ordre(_ordre(6, coin="xyz:XYZ100"))["coin"] == "xyz:XYZ100"
    # un ordre illisible n'est jamais deviné
    for casse in (_ordre(7, side="X"), _ordre(8, px="0"), _ordre(9, px="abc"), _ordre(10, sz="-1"),
                  {**_ordre(11), "oid": "11"}, {**_ordre(12), "coin": ""}, "pas un ordre"):
        assert O.normaliser_ordre(casse) is None


def test_instantane_formes_ws_et_rest_resume_des_teneurs_de_marche_et_signature():
    ordres = [_ordre(2, px="0.71"), _ordre(1, side="B", px="0.60"), _ordre(3, reduce_only=True), "casse"]
    ws = O.construire_instantane_ordres(_message(ordres, dex="xyz"), user=LEADER.upper(), recv_ms=NOW)
    assert ws["vault"] == LEADER and ws["dex"] == "xyz" and ws["ts_ms"] == NOW and ws["source"] == "OPEN_ORDERS_WS"
    assert ws["n_orders"] == 3 and ws["n_ignores"] == 1 and [o["oid"] for o in ws["orders"]] == [1, 2, 3]
    assert ws["par_genre"] == {O.ENTREE_LIMITE: 2, O.SORTIE_LIMITE: 1} and ws["tronque"] is False
    assert ws["notionnel_par_coin"]["WLD"] == {"B": 3000.0, "A": 7201.0}
    rest = O.construire_instantane_ordres(ordres[:3], user=LEADER, recv_ms=NOW, source="OPEN_ORDERS_REST")
    assert rest["orders"] == ws["orders"] and rest["dex"] == "" and rest["source"] == "OPEN_ORDERS_REST"
    # même carnet : même signature ; une taille restante qui change : signature différente
    assert O.signature_ordres(ws) == O.signature_ordres(rest)
    entame = O.construire_instantane_ordres([_ordre(2, px="0.71", sz="1200.0"), *ordres[1:3]], user=LEADER, recv_ms=NOW)
    assert O.signature_ordres(entame) != O.signature_ordres(ws)
    # teneur de marché : résumé seulement, et l'instantané le dit
    gros = O.construire_instantane_ordres([_ordre(i) for i in range(1, 302)], user=LEADER, recv_ms=NOW)
    assert gros["tronque"] is True and gros["orders"] == [] and gros["n_orders"] == 301
    assert gros["par_genre"] == {O.ENTREE_LIMITE: 301}
    assert O.construire_instantane_ordres({"orders": "x"}, user=LEADER, recv_ms=NOW) is None
    assert O.construire_instantane_ordres([], user="pas une adresse", recv_ms=NOW) is None


def test_la_lane_n_ecrit_un_carnet_que_s_il_change_ou_comme_battement(tmp_path):
    lane = _outil("collecter_contexte_lane")
    L = lane.LaneContexte(tmp_path / "pos.jsonl", tmp_path / "twap.jsonl", tmp_path / "snap.jsonl",
                          tmp_path / "ordres.jsonl")

    def pousser(ordres, t, user=LEADER):
        return asyncio.run(L.ecrire_ordres(O.construire_instantane_ordres(_message(ordres, user=user), user=user, recv_ms=t)))

    un = [_ordre(1)]
    assert pousser(un, T0) is True
    assert pousser(un, T0 + 5_000) is False                          # le serveur repousse la même liste
    assert pousser([_ordre(1), _ordre(2)], T0 + 10_000) is False     # rafale : au plus un carnet par 30 s
    assert pousser([_ordre(1), _ordre(2)], T0 + 31_000) is True      # changement, délai écoulé
    assert pousser([_ordre(1), _ordre(2)], T0 + 120_000) is False    # inchangé
    assert pousser([_ordre(1), _ordre(2)], T0 + 31_000 + lane.BATTEMENT_PORTEFEUILLE_MS) is True   # battement
    assert pousser([], T0 + 20 * 60_000) is True                     # tout annulé : c'est un changement
    # un compte sans ordre est écrit aussi : il prouve le suivi (sinon ses exécutions sembleraient non observées)
    assert pousser([], T0, user=AUTRE) is True
    assert asyncio.run(L.ecrire_ordres(None)) is False
    lignes = [json.loads(x) for x in (tmp_path / "ordres.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(x["vault"][:6], x["n_orders"]) for x in lignes] == [
        ("0x07fd", 1), ("0x07fd", 2), ("0x07fd", 2), ("0x07fd", 0), ("0x6540", 0)]
    assert L.ordres == 5
    assert all("cadence_ms" in x for x in lignes)
    # un compte qui cote en continu (carnet différent toutes les 31 s pendant 30 min) est échantillonné de
    # moins en moins souvent : 30 s, 1 min, 2 min, 4 min, puis au plus une fois par battement
    actif = "0x" + "c1" * 20
    ecrits = [t for k in range(58) if pousser([_ordre(1000 + k)], T0 + k * 31_000, user=actif) for t in [k * 31]]
    assert ecrits[:5] == [0, 31, 93, 217, 465] and len(ecrits) <= 10
    # dès qu'il se calme (carnet inchangé jusqu'au battement), la cadence fine revient
    calme = T0 + 58 * 31_000 + 2 * lane.BATTEMENT_PORTEFEUILLE_MS
    assert pousser([_ordre(1057)], calme, user=actif) is True
    assert pousser([_ordre(2000)], calme + 31_000, user=actif) is True


# ------------------------------------------------------------------ certification et couverture

def _carnet(ordres, t=T0, user=LEADER):
    return O.construire_instantane_ordres(_message(ordres, user=user), user=user, recv_ms=t)


def test_certification_un_instantane_est_un_tout():
    def juger(ligne):
        return C.certifier_record(ligne, famille=C.FAMILLE_LEADER_ORDERS, source="OPEN_ORDERS_WS", now_ms=NOW)

    assert C._FICHIERS_CONNUS["copy_vault_orders_lane.jsonl"] == (C.FAMILLE_LEADER_ORDERS, "OPEN_ORDERS_WS")
    bon = _carnet([_ordre(1), _ordre(2, reduce_only=True)])
    sortie, statut, motif = juger(bon)
    assert statut == C.PASS and motif == "" and sortie["n_orders"] == 2 and sortie["vault"] == LEADER
    assert juger(_carnet([]))[1] == C.PASS                                           # carnet vide : preuve de suivi
    assert juger(_carnet([_ordre(i) for i in range(1, 302)]))[1] == C.PASS           # carnet résumé déclaré

    def casse(**champs):
        return {**bon, **champs}

    refus = {
        "vault_absent_ou_invalide": casse(vault="x"),
        "timestamp_futur": casse(ts_ms=NOW + 3_600_000),
        "ordres_absents": casse(orders=None),
        "compte_d_ordres_incoherent": casse(n_orders=3),                              # un ordre manque : fausse annulation
        "carnet_resume_avec_detail": casse(tronque=True),
        "ordre_invalide": casse(orders=[{**bon["orders"][0], "side": "X"}, bon["orders"][1]]),
        "ordre_prix_ou_taille_invalide": casse(orders=[{**bon["orders"][0], "px": 0.0}, bon["orders"][1]]),
        "ordre_en_double": casse(orders=[bon["orders"][0], bon["orders"][0]]),
        "ordre_posterieur_a_l_observation": casse(orders=[{**bon["orders"][0], "ts_ms": T0 + 3_600_000}, bon["orders"][1]]),
    }
    for motif_attendu, ligne in refus.items():
        sortie, statut, motif = juger(ligne)
        assert sortie is None and statut == C.QUARANTAINE and motif == motif_attendu, motif_attendu
    # deux observations du même compte : deux identités ; la même observation rejouée : un doublon
    assert C.identite(_carnet([_ordre(1)], T0), C.FAMILLE_LEADER_ORDERS) \
        != C.identite(_carnet([_ordre(1)], T0 + 30_000), C.FAMILLE_LEADER_ORDERS)
    decisions = [d for _, d, _ in C.certifier_lignes([json.dumps(bon), json.dumps(bon)], famille=C.FAMILLE_LEADER_ORDERS,
                                                     source="OPEN_ORDERS_WS", now_ms=NOW)]
    assert decisions == [C.PASS, "DOUBLON"]


def test_le_flux_est_declare_de_bout_en_bout_dans_le_registre_de_couverture():
    flux = next(f for f in R.FLUX if f.fichier == "copy_vault_orders_lane.jsonl")
    assert flux.famille == "leader_orders" and flux.labo == R.CONSOMME and "--ordres" in flux.usage
    assert flux.producteur == "tools/collecter_contexte_lane.py" and (RACINE / flux.producteur).is_file()
    assert "leader_orders" in R.EQUIVALENT_SAFE
    assert "copy_vault_orders_lane.jsonl" in _outil("telecharger_lanes_certifiees_github").LANES["contexte"][1]
    assert "runtime/data/copy_vault_orders_lane.jsonl" in (
        RACINE / ".github" / "workflows" / "copy-vault-contexte-lanes.yml").read_text(encoding="utf-8")
    assert "--ordres" in (RACINE / "LANCER_LAB_QUANT_COPY_VAULT.cmd").read_text(encoding="utf-8")


# ------------------------------------------------------------------ étude du labo

def _fill(vault, oid, t, *, notionnel=10_000.0, passif=True, ouverture=True, coin="WLD", signe=-1):
    return {"vault": vault, "coin": coin, "time": int(t), "obs": int(t + 2_000), "oid": oid, "signe": signe,
            "crossed": 0.0 if passif else 1.0, "is_open": ouverture, "notional": notionnel, "px": 0.73}


def test_anticipabilite_seul_un_ordre_vu_assez_tot_et_revu_recemment_compte():
    minute = 60_000
    carnets = [_carnet([_ordre(1), _ordre(3)], T0), _carnet([_ordre(1), _ordre(3)], T0 + 5 * minute),
               _carnet([_ordre(1), _ordre(4)], T0 + 9 * minute + 50_000),          # l'ordre 4 n'apparaît que 10 s avant
               _carnet([], T0 + 60 * minute),
               # un teneur de marché : carnets résumés seulement
               _carnet([_ordre(i) for i in range(100, 401)], T0, user=AUTRE),
               _carnet([_ordre(i) for i in range(100, 401)], T0 + 60 * minute, user=AUTRE)]
    fills = pd.DataFrame([
        _fill(LEADER, 1, T0 + 10 * minute),                        # vu 10 min avant, revu 10 s avant : anticipable
        _fill(LEADER, 2, T0 + 10 * minute, passif=False),          # jamais vu (ordre au marché) : non
        _fill(LEADER, 4, T0 + 10 * minute),                        # vu seulement 10 s avant : vu, pas anticipable
        _fill(LEADER, 3, T0 + 40 * minute, notionnel=20_000.0),    # disparu du carnet depuis 30 min : vue interrompue
        _fill(LEADER, 1, T0 + 2 * 3_600_000),                      # après la fin du suivi : hors mesure
        _fill(AUTRE, 150, T0 + 10 * minute),                       # carnet résumé : leader écarté
    ])
    vies, suivi = I.order_lifetimes(carnets)
    assert suivi[AUTRE]["carnets_resumes"] == 2 and len(vies) == 3
    table = I.match_fills(fills, vies, suivi)
    assert list(table["oid"]) == [1, 2, 4, 3] and list(table["anticipable"]) == [True, False, False, False]
    assert table["avance_ms"].iloc[0] == 10 * minute and pd.isna(table["avance_ms"].iloc[1])
    etude = I.run_order_intent_study(carnets, fills)
    mesures = etude["anticipability"]
    assert etude["inputs"]["leaders_au_carnet_resume"] == 1 and etude["inputs"]["fills_pendant_le_suivi"] == 4
    assert mesures["part_notionnel_anticipable"] == pytest.approx(10_000 / 50_000)
    assert mesures["part_notionnel_ordre_vu"] == pytest.approx(40_000 / 50_000)
    assert mesures["part_notionnel_agressif_anticipable"] == 0.0
    assert etude["verdicts"][0]["status"] == "MORE_DATA" and etude["economically_proven"] is False


def test_verdicts_selon_la_part_visible_et_sans_donnee_rien_n_est_invente():
    vide = I.run_order_intent_study([], pd.DataFrame())
    assert vide["verdicts"][0]["status"] == "UNMEASURABLE" and vide["inputs"]["carnets"] == 0
    reglages = I.OrderIntentConfig(min_days=1, min_fills=4, min_leaders=1)
    minute = 60_000
    carnets = [_carnet([_ordre(i) for i in range(1, 9)], T0 + k * minute) for k in range(0, 60, 5)]
    annonces = pd.DataFrame([_fill(LEADER, i, T0 + 30 * minute) for i in range(1, 7)])       # tous annoncés
    assert I.run_order_intent_study(carnets, annonces, reglages)["verdicts"][0]["status"] == "PROMISING"
    surprises = pd.DataFrame([_fill(LEADER, 900 + i, T0 + 30 * minute, passif=False) for i in range(6)])
    rejet = I.run_order_intent_study(carnets, surprises, reglages)["verdicts"][0]
    assert rejet["status"] == "REJECTED" and "0 %" in rejet["reason"]


def test_bout_en_bout_lane_certificateur_coffre_labo(tmp_path):
    """NOUVELLE DONNÉE -> collecte -> certification -> coffre -> lecture par le labo -> rapport et registre."""
    etude = _outil("etude_copiabilite")
    minute = 60_000
    carnets = [_carnet([_ordre(1), _ordre(2, reduce_only=True)], T0 + k * minute) for k in range(0, 30, 5)]
    corrompu = {**carnets[0], "ts_ms": T0 + 7 * minute, "n_orders": 5}                # un ordre manquerait
    data = tmp_path / "runtime" / "data"
    data.mkdir(parents=True)
    (data / "copy_vault_orders_lane.jsonl").write_text(
        "".join(json.dumps(ligne) + "\n" for ligne in [*carnets, corrompu]) + "ligne tronquee{", encoding="utf-8")
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    index = json.loads((tmp_path / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
    shards = [e for e in index["shards"] if e["famille"] == "leader_orders"]
    assert len(shards) == 1 and shards[0]["deposes"] == 6                             # le carnet corrompu n'entre pas
    with gzip.open(tmp_path / shards[0]["shard"], "rt", encoding="utf-8") as lecture:
        assert all(json.loads(x)["n_orders"] == 2 for x in lecture)

    resultat = etude.run_ordres(tmp_path, workers=1, write=True)
    rapport = resultat["report"]
    assert rapport["inputs"]["carnets"] == 6 and rapport["inputs"]["leaders_suivis"] == 1
    assert resultat["donnees_consommees"]["leader_orders"]["shards"] == 1
    assert rapport["verdicts"][0]["status"] == "MORE_DATA" and rapport["economically_proven"] is False
    assert rapport["collection_need"]["collecteur"].startswith("tools/collecter_contexte_lane.py")
    dossier = tmp_path / etude.REPORT_DIR / resultat["run_id"]
    assert "Intentions des leaders" in (dossier / "RAPPORT.md").read_text(encoding="utf-8")
    assert etude.verify_ledger(tmp_path / etude.REPORT_DIR / "EXPERIENCES.ndjson")["status"] == "VERIFIED"
    # sans aucun carnet au coffre : non mesurable, avec le besoin de collecte écrit en clair
    (data / "copy_vault_orders_lane.jsonl").unlink()
    ailleurs = tmp_path / "vide"
    (ailleurs / "runtime" / "history").mkdir(parents=True)
    (ailleurs / "runtime" / "history" / "candles_1h.jsonl").write_text(json.dumps(
        {"coin": "WLD", "t_ms": T0, "o": 0.7, "h": 0.8, "l": 0.6, "c": 0.75, "v": 1.0, "interval": "1h",
         "source": "REST_BACKFILL_1H"}) + chr(10), encoding="utf-8")
    assert scl.main(["--root", str(ailleurs), "--now-ms", str(NOW)]) == 0
    sans = etude.run_ordres(ailleurs, workers=1, write=False)
    assert sans["report"]["verdicts"][0]["status"] == "UNMEASURABLE" and sans["report"]["collection_need"]["source"]


# ------------------------------------------------------------------ rejeu prudent d'un ordre jumeau

def _panel_jumeau(prix, *, coin="WLD", pas=60_000):
    import numpy as np

    from hl_observer.backtesting.copy_vault_copiability_entrees import PricePanel

    ts = T0 + np.arange(len(prix), dtype=np.int64) * pas
    return PricePanel(ts=ts, px=np.array(prix, dtype=float).reshape(-1, 1), coins=(coin,), provenance="test",
                      stale_ms=pas + 30_000)


def _vie(oid, px, *, side="B", debut_min=0, fin_min=30, genre=O.ENTREE_LIMITE, coin="WLD"):
    return {"vault": LEADER, "dex": "", "oid": oid, "coin": coin, "side": side, "px": px, "genre": genre,
            "premier_ms": T0 + debut_min * 60_000, "dernier_ms": T0 + fin_min * 60_000, "vues": 5}


def test_le_jumeau_n_est_execute_que_si_le_prix_traverse_et_les_non_executions_sont_comptees():
    reglages = I.OrderIntentConfig(horizons_h=(1,), bootstrap_samples=50)
    minutes = 200
    # le prix part de 1,00, plonge sous 0,95 à la 20e minute, puis remonte à 1,02 et y reste
    prix = [1.00] * 20 + [0.94] * 5 + [1.02] * (minutes - 25)
    panel = _panel_jumeau(prix)
    vies = pd.DataFrame([
        _vie(1, 0.95),                              # traversé à la 20e minute : exécuté à 0,95, revendu 1,02
        _vie(2, 0.90),                              # jamais atteint : non exécuté
        _vie(3, 0.94),                              # seulement TOUCHÉ (clôture = prix limite) : non exécuté
        _vie(4, 0.95, debut_min=0, fin_min=5),      # annulé (délai compris) avant la baisse : non exécuté
        _vie(5, 0.95, debut_min=22, fin_min=40),    # posé alors que le prix est déjà sous le niveau : servi aussitôt
        _vie(6, 1.05, side="A"),                    # vente au-dessus du marché, jamais traversée
        _vie(7, 0.95, genre=O.SORTIE_LIMITE),       # une sortie n'est pas une entrée : ignorée
        _vie(8, 0.95, coin="ABSENT"),               # coin sans prix : compté à part
    ])
    rejeu = I.twin_order_replay(vies, panel, {"WLD": 2.0}, reglages)
    assert rejeu["ordres_d_entree"] == 7 and rejeu["sans_prix"] == 1
    # exécutés : l'ordre 1 (traversé) et l'ordre 5 (servi aussitôt, compté au prix limite : hypothèse prudente)
    assert rejeu["jumeaux_executes"] == 2
    assert rejeu["taux_d_execution"] == pytest.approx(2 / 6)
    brut = (1.02 / 0.95 - 1.0) * 1e4
    assert rejeu["brut_1h"]["moyenne_bps"] == pytest.approx(brut, rel=1e-6)
    assert rejeu["net_1h"]["moyenne_bps"] == pytest.approx(brut - (I.MAKER_PERP_BPS + I.TAKER_PERP_BPS + 2.0), rel=1e-6)


def test_le_jumeau_subit_l_execution_a_contre_courant_et_l_etude_le_rapporte():
    reglages = I.OrderIntentConfig(horizons_h=(1,), bootstrap_samples=50)
    # le prix traverse le niveau et continue de chuter : le jumeau est servi au pire moment
    prix = [1.00] * 10 + [0.93] * 5 + [0.85] * 185
    rejeu = I.twin_order_replay(pd.DataFrame([_vie(1, 0.95)]), _panel_jumeau(prix), {"WLD": 2.0}, reglages)
    assert rejeu["jumeaux_executes"] == 1 and rejeu["net_1h"]["moyenne_bps"] < -1_000
    # délai de réaction : un ordre vu à la minute 9 et traversé à la minute 10 n'est pas rattrapé à temps
    court = I.twin_order_replay(pd.DataFrame([_vie(1, 0.95, debut_min=9, fin_min=9)]), _panel_jumeau(prix),
                                {"WLD": 2.0}, I.OrderIntentConfig(horizons_h=(1,), reaction_ms=120_000, cancel_delay_ms=0))
    assert court["jumeaux_executes"] == 0
    # l'étude complète porte le rejeu dès qu'un prix est fourni, et rien sans prix
    carnets = [_carnet([_ordre(1, side="B", px="0.95")], T0 + k * 60_000) for k in range(0, 30, 5)]
    avec = I.run_order_intent_study(carnets, pd.DataFrame(), reglages, panel=_panel_jumeau(prix), half_spread_bps={"WLD": 2.0})
    assert avec["twin_order_replay"]["jumeaux_executes"] == 1
    assert I.run_order_intent_study(carnets, pd.DataFrame(), reglages)["twin_order_replay"] == {}
    assert I.twin_order_replay(pd.DataFrame(), _panel_jumeau(prix), {})["ordres_d_entree"] == 0
