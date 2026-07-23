"""Tests de la persistance disque de l'ETAPE 2 : positions ouvertes + ledger PnL realise."""
from __future__ import annotations

import json

from hl_observer.funding.carry_positions_store import (
    charger_gestionnaire, tick_sur_disque, resume_depuis_ledger,
    _append_ledger, POSITIONS_RELPATH, LEDGER_RELPATH,
)

H = 3_600_000


def test_le_ledger_carry_est_ETIQUETE_a_la_source(tmp_path):
    """🔴 23/07 (casseur de confiance n°1) — 60 % des closes du ledger sortaient en `?` : le store
    carry écrivait sans `strategie` -> attribution du PnL PAR MOTEUR fausse. Désormais tagué à la
    source, sans jamais écraser une étiquette explicite (pas de mélange carry/arb/cross-venue)."""
    _append_ledger(tmp_path, {"kind": "CLOSE", "coin": "BTC", "realized_net_pnl_usdc": -0.05})
    _append_ledger(tmp_path, {"kind": "OPEN", "coin": "ETH", "strategie": "cross_venue_carry"})
    lignes = [json.loads(l) for l in (tmp_path / LEDGER_RELPATH).read_text(encoding="utf-8").splitlines()]
    assert lignes[0]["strategie"] == "carry"                 # tagué à la source
    assert lignes[1]["strategie"] == "cross_venue_carry"     # étiquette explicite JAMAIS écrasée


# 🔴 21/07 — funding d'ENTREE releve du plancher (0.125) a 0.45 : la porte du cout
# d'opportunite (carry_benchmark_gate) refuse desormais d'ouvrir au plancher (APR net 2,65 %
# contre 15-30 % pour HLP). Ces tests portent sur le STORE (persistance, dedup, PnL, slots),
# pas sur la rentabilite du plancher : il leur faut une position que le systeme ouvrirait
# vraiment. Le refus au plancher a son propre test dans test_carry_benchmark_gate.py.
# Le funding COURANT d'accrual reste a 0.125 : il n'est pas gate, seule l'OUVERTURE l'est.
_FUNDING_OUVRABLE = 0.45


def _decision(viable=True, **kw):
    d = {"coin": "HYPE", "funding_bps_h": _FUNDING_OUVRABLE, "base_bps": -0.68, "liquidite_spot_usd": 200_000.0,
         "cout_entree_bps": 9.0, "viable": viable, "motif": "CARRY_NEUTRE_VIABLE"}
    d.update(kw)
    return d


def _inputs(**kw):
    d = {"ts_ms": 1, "coin": "HYPE", "funding_bps_h": _FUNDING_OUVRABLE, "base_bps": -0.68,
         "liquidite_spot_usd": 200_000.0, "maker": True, "levier_max": 10.0,
         "marge_ratio": 0.5, "pire_hausse_observee": 0.29, "levier_utilise": 2.0}
    d.update(kw)
    return d


def test_ouverture_persiste_puis_recharge(tmp_path):
    e = tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=0, funding_bps_h_courant=0.125)
    assert e["ouvert"] is True
    assert (tmp_path / POSITIONS_RELPATH).exists()
    # un NOUVEAU processus recharge la meme position
    g = charger_gestionnaire(tmp_path)
    assert "HYPE" in g.ouvertes
    assert g.ouvertes["HYPE"]["notional_usdt"] == 100.0


def test_cycle_complet_ouvre_accrue_ferme_et_ledger(tmp_path):
    tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=0, funding_bps_h_courant=0.125)
    # accrue 200h (dans la fenetre d'age 336h, mais au-dela du break-even ~160h), puis funding->0
    tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=200 * H, funding_bps_h_courant=0.125)
    e = tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=201 * H, funding_bps_h_courant=-1.0)  # hemorragie -> CLOSE immediat (A6)
    assert e["ferme"] == "FUNDING_NON_RENTABLE"
    assert e["pnl_realise_usdt"] > 0.0                     # 200h de funding > frais
    # plus aucune position ouverte, et le ledger contient OPEN + CLOSE
    assert charger_gestionnaire(tmp_path).ouvertes == {}
    r = resume_depuis_ledger(tmp_path)
    assert r["opens"] == 1 and r["closes"] == 1
    assert r["realized_net_pnl_usdc"] == e["pnl_realise_usdt"]


def test_ledger_est_append_only(tmp_path):
    tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=0, funding_bps_h_courant=0.125)
    tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=5001 * H, funding_bps_h_courant=-1.0)
    lignes = (tmp_path / LEDGER_RELPATH).read_text(encoding="utf-8").strip().splitlines()
    kinds = [json.loads(l)["kind"] for l in lignes]
    assert kinds == ["OPEN", "CLOSE"]


def test_un_coin_une_position_pas_de_doublon(tmp_path):
    tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=0, funding_bps_h_courant=0.125)
    tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=H, funding_bps_h_courant=0.125)
    tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=2 * H, funding_bps_h_courant=0.125)
    assert len(charger_gestionnaire(tmp_path).ouvertes) == 1
    assert resume_depuis_ledger(tmp_path)["opens"] == 1     # une seule ouverture

def test_mode_different_repart_vide_jamais_de_melange(tmp_path):
    # on ouvre en LIVE...
    tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=0, funding_bps_h_courant=0.125, mode="LIVE")
    # ...un chargement TEST_FIXTURE ne doit PAS voir la position LIVE
    g = charger_gestionnaire(tmp_path, mode="TEST_FIXTURE")
    assert g.ouvertes == {}
    # et le resume par mode ne melange pas
    assert resume_depuis_ledger(tmp_path, mode="TEST_FIXTURE")["opens"] == 0
    assert resume_depuis_ledger(tmp_path, mode="LIVE")["opens"] == 1


# ---------- etat_carry (visibilite dashboard) ----------

def test_etat_carry_expose_pnl_et_positions(tmp_path):
    tick_sur_disque(tmp_path, _decision(), _inputs(), now_ms=0, funding_bps_h_courant=0.125)
    e = __import__("hl_observer.funding.carry_positions_store", fromlist=["etat_carry"]).etat_carry(tmp_path)
    assert e["positions_ouvertes"] == 1
    assert e["coins_ouverts"] == ["HYPE"]
    assert e["opens"] == 1 and e["closes"] == 0
    assert e["realized_net_pnl_usdc"] == 0.0            # rien de ferme encore


# ---------- tick_multi_sur_disque (shortlist multi-coins) ----------

def _mesure(coin, funding=_FUNDING_OUVRABLE, levier=2.0):
    dec = _decision(coin=coin, funding_bps_h=funding)
    inp = _inputs(coin=coin, funding_bps_h=funding, levier_utilise=levier)
    return {"decision": dec, "inputs": inp, "funding": funding}


def test_multi_ouvre_plusieurs_coins_en_parallele(tmp_path):
    from hl_observer.funding.carry_positions_store import tick_multi_sur_disque, charger_gestionnaire
    mesures = {"HYPE": _mesure("HYPE"), "PURR": _mesure("PURR"), "AZTEC": _mesure("AZTEC")}
    evts = tick_multi_sur_disque(tmp_path, mesures, now_ms=0)
    assert sum(1 for e in evts if e.get("ouvert")) == 3
    assert set(charger_gestionnaire(tmp_path).ouvertes) == {"HYPE", "PURR", "AZTEC"}


def test_multi_ferme_un_coin_qui_sort_DURABLEMENT_de_la_shortlist(tmp_path):
    """🔴 DOCTRINE CORRIGÉE LE 2026-07-19, PAR LA MESURE.

    Ce test exigeait autrefois une fermeture DÈS LA PREMIÈRE passe sans le coin, au nom du
    deny-by-default. Le run réel a montré le prix de cette règle :

        opens = 32   closes = 31   sur 22,3 h   toujours HYPE
        motif : COIN_PLUS_DANS_SHORTLIST × 29        realized = -4,998 $

    Le feeder tourne toutes les 10 min ; une passe qui ne listait pas le coin suffisait à
    fermer (11 bps) puis rouvrir (12,5 bps). À 0,125 bps/h sur 75 $, un aller-retour détruit
    ~188 HEURES de funding. Les 31 allers-retours SONT le PnL négatif, en entier.

    La règle était une MAUVAISE application du deny-by-default : celui-ci dit « ne pas OUVRIR
    sans donnée », pas « FERMER quand la donnée cligne ». Fermer est une ACTION qui coûte ;
    l'abstention est le défaut.

    On exige donc désormais une absence PROLONGÉE (plusieurs passes ET plusieurs minutes).
    Le coin finit bien par être fermé — on ne tient pas une position aveugle indéfiniment.
    """
    from hl_observer.funding.carry_anti_churn import SORTIE_ABSENCE_PROLONGEE
    from hl_observer.funding.carry_positions_store import tick_multi_sur_disque, charger_gestionnaire
    H = 3_600_000
    # poll 1 : HYPE + PURR ouverts
    tick_multi_sur_disque(tmp_path, {"HYPE": _mesure("HYPE"), "PURR": _mesure("PURR")}, now_ms=0)

    # poll 2 : PURR manque UNE passe -> on GARDE (c'est exactement ce qui coûtait 17,6 centimes)
    evts = tick_multi_sur_disque(tmp_path, {"HYPE": _mesure("HYPE")}, now_ms=1 * H)
    assert not [e for e in evts if e.get("ferme")], "une absence d'une passe ne doit RIEN fermer"
    assert set(charger_gestionnaire(tmp_path).ouvertes) == {"HYPE", "PURR"}

    # polls 3 et 4 : PURR toujours absent -> absence PROLONGÉE, là on ferme
    tick_multi_sur_disque(tmp_path, {"HYPE": _mesure("HYPE")}, now_ms=2 * H)
    evts = tick_multi_sur_disque(tmp_path, {"HYPE": _mesure("HYPE")}, now_ms=3 * H)
    fermes = {e["coin"]: e["ferme"] for e in evts if e.get("ferme")}
    assert fermes.get("PURR") == SORTIE_ABSENCE_PROLONGEE
    assert set(charger_gestionnaire(tmp_path).ouvertes) == {"HYPE"}   # HYPE reste


# ---------- A7 : rotation vers le meilleur net (plafond de slots) ----------

def test_a7_max_slots_ferme_les_plus_faibles_nets(tmp_path):
    from hl_observer.funding.carry_positions_store import (
        tick_multi_sur_disque, charger_gestionnaire, SORTIE_ROTATION)
    mesures = {
        "A": {"decision": _decision(coin="A", gain_net_24h_bps=10.0), "inputs": _inputs(coin="A"), "funding": 0.125},
        "B": {"decision": _decision(coin="B", gain_net_24h_bps=50.0), "inputs": _inputs(coin="B"), "funding": 0.125},
        "C": {"decision": _decision(coin="C", gain_net_24h_bps=5.0),  "inputs": _inputs(coin="C"), "funding": 0.125},
    }
    evts = tick_multi_sur_disque(tmp_path, mesures, now_ms=0, max_slots=2)
    assert set(charger_gestionnaire(tmp_path).ouvertes) == {"A", "B"}   # 2 meilleurs nets ; C(5) ferme
    fermes = {e["coin"]: e["ferme"] for e in evts if e.get("ferme")}
    assert fermes.get("C") == SORTIE_ROTATION


def test_a7_sans_max_slots_comportement_inchange(tmp_path):
    from hl_observer.funding.carry_positions_store import tick_multi_sur_disque, charger_gestionnaire
    mesures = {c: {"decision": _decision(coin=c, gain_net_24h_bps=g), "inputs": _inputs(coin=c),
                   "funding": 0.125} for c, g in [("A", 10.0), ("B", 50.0), ("C", 5.0)]}
    tick_multi_sur_disque(tmp_path, mesures, now_ms=0)                  # pas de max_slots
    assert set(charger_gestionnaire(tmp_path).ouvertes) == {"A", "B", "C"}   # les 3 restent


# ---------- fermeture propre + SHADOW du carry historique (decision Flo 23/07) ----------

def test_fermer_tout_et_desactiver_solde_aux_prix_executables_garde_historique_idempotent(tmp_path):
    from hl_observer.funding.carry_positions_store import (
        tick_multi_sur_disque, fermer_tout_et_desactiver, charger_gestionnaire,
        resume_depuis_ledger, SORTIE_MODULE_DESACTIVE, LEDGER_RELPATH)
    tick_multi_sur_disque(tmp_path, {"HYPE": _mesure("HYPE"), "PURR": _mesure("PURR")}, now_ms=0)
    assert len(charger_gestionnaire(tmp_path).ouvertes) == 2
    # base executable fournie pour HYPE, absente pour PURR -> repli conservateur sur la base d'entree
    r = fermer_tout_et_desactiver(tmp_path, bases_courantes={"HYPE": 2.0}, now_ms=100 * H)
    assert r["n_fermees"] == 2 and r["real_execution"] is False
    assert charger_gestionnaire(tmp_path).ouvertes == {}             # plus aucune position fantome
    assert resume_depuis_ledger(tmp_path)["closes"] == 2            # historique CONSERVE au ledger
    reasons = [json.loads(l).get("reason") for l in (tmp_path / LEDGER_RELPATH).read_text().splitlines()
               if '"CLOSE"' in l]
    assert reasons and all(x == SORTIE_MODULE_DESACTIVE for x in reasons)
    assert fermer_tout_et_desactiver(tmp_path, now_ms=101 * H)["n_fermees"] == 0   # idempotent
