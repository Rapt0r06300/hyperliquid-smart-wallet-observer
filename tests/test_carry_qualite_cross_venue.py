"""FILTRE QUALITÉ CROSS-VENUE pour le carry HL (23/07).

Flo : « gagner de l'argent avec le cross-venue ». L'arb cross-venue pur n'est pas capturable (pas
d'exécution Binance) ; MAIS le funding Binance sert de signal de QUALITÉ capturable pour le carry HL.
Ces tests prouvent que le tilt est BORNÉ, anti-artefact, et n'affaiblit JAMAIS la barre du net.
"""
from __future__ import annotations

import json
from pathlib import Path

from hl_observer.funding.carry_allocation_nette import poids_par_rendement, allouer_marges
from hl_observer.funding.carry_qualite_cross_venue import (
    FACTEUR_MAX, FACTEUR_MIN, charger_dispersion_recente, facteur_qualite,
    facteurs_qualite_carry, rapport_qualite)


# ---------------------------------------------------------------- le facteur, PUR

def test_premium_HL_persistant_donne_un_bonus_borne():
    """HL persistamment AU-DESSUS de Binance = funding HL structurellement le plus haut = robuste.
    hl CONSTANT au plancher (0.125) est NORMAL ; c'est bin qui varie (funding Binance live)."""
    serie = [(0.125, 0.05 + (i % 5) * 0.001) for i in range(40)]   # hl - bin ≈ +0.073 > seuil, 100 %
    f, label = facteur_qualite(serie)
    assert f == FACTEUR_MAX and label == "PREMIUM_HL_PERSISTANT"


def test_inverse_HL_sous_binance_donne_un_malus_borne():
    serie = [(0.02, 0.125 + (i % 5) * 0.001) for i in range(40)]   # hl < bin persistant
    f, label = facteur_qualite(serie)
    assert f == FACTEUR_MIN and label == "INVERSE"


def test_prime_de_marche_egale_est_NEUTRE():
    serie = [(0.080, 0.079), (0.079, 0.080)] * 20       # ≈ égal, pas de côté franc -> 1.0
    f, label = facteur_qualite(serie)
    assert f == 1.0 and label == "PRIME_MARCHE"


def test_jambe_binance_FIGEE_est_un_artefact_pas_un_signal():
    """VINE : bin_bps_h à une seule valeur (coin absent de Binance). Ne JAMAIS incliner dessus."""
    serie = [(1.0 + i * 0.01, 0.0) for i in range(40)]  # bin figé à 0 -> artefact
    f, label = facteur_qualite(serie)
    assert f == 1.0 and label == "JAMBE_FIGEE"


def test_serie_trop_courte_est_NEUTRE_pas_du_bruit():
    assert facteur_qualite([(0.125, 0.0)] * 5) == (1.0, "INSUFFISANT")


# ---------------------------------------------------------------- la lecture BORNÉE

def _ecrire_dispersion(root: Path, rows: list[dict]) -> None:
    p = root / "runtime" / "data" / "dispersion_venues.jsonl"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_charge_par_coin_et_survit_a_l_absence(tmp_path):
    _ecrire_dispersion(tmp_path, [{"coin": "BTC", "hl_bps_h": 0.125, "bin_bps_h": 0.05},
                                  {"coin": "BTC", "hl_bps_h": 0.125, "bin_bps_h": 0.06},
                                  {"coin": "GAS", "hl_bps_h": 0.9, "bin_bps_h": 0.05}])
    d = charger_dispersion_recente(tmp_path)
    assert d["BTC"] == [(0.125, 0.05), (0.125, 0.06)] and len(d["GAS"]) == 1
    assert charger_dispersion_recente(tmp_path / "vide") == {}          # fichier absent -> {}


def test_facteurs_ne_retourne_QUE_les_non_neutres(tmp_path):
    rows = [{"coin": "DASH", "hl_bps_h": 0.30, "bin_bps_h": 0.05 + (i % 4) * 0.002} for i in range(30)]
    rows += [{"coin": "SOL", "hl_bps_h": 0.079 + (i % 3) * 0.001, "bin_bps_h": 0.080}
             for i in range(30)]                                        # ≈ égal -> neutre
    _ecrire_dispersion(tmp_path, rows)
    f = facteurs_qualite_carry(tmp_path)
    assert f.get("DASH") == FACTEUR_MAX and "SOL" not in f               # neutres omis


def test_rapport_qualite_est_trie_et_lisible(tmp_path):
    rows = [{"coin": "DASH", "hl_bps_h": 0.30, "bin_bps_h": 0.05 + (i % 4) * 0.002} for i in range(30)]
    _ecrire_dispersion(tmp_path, rows)
    r = rapport_qualite(tmp_path)
    assert r and r[0]["coin"] == "DASH" and r[0]["label"] == "PREMIUM_HL_PERSISTANT"
    assert r[0]["premium_bps_h"] > 0.0 and r[0]["n"] == 30


# ---------------------------------------------------------------- le tilt dans l'ALLOCATION

def test_sans_qualite_le_comportement_est_IDENTIQUE():
    """Rétro-compatibilité : `qualite_par_coin=None` -> exactement l'allocation existante."""
    nets = {"BTC": 2.0, "ETH": 1.0}
    assert poids_par_rendement(nets) == poids_par_rendement(nets, qualite_par_coin=None)


def test_le_tilt_incline_le_capital_vers_la_meilleure_qualite():
    nets = {"BTC": 1.0, "ETH": 1.0}                     # net ÉGAL -> sans tilt, poids égaux
    sans = poids_par_rendement(nets)
    avec = poids_par_rendement(nets, qualite_par_coin={"BTC": FACTEUR_MAX, "ETH": FACTEUR_MIN})
    assert abs(sans["BTC"] - sans["ETH"]) < 1e-9                         # égaux sans tilt
    assert avec["BTC"] > avec["ETH"]                                     # BTC (meilleure qualité) favorisé


def test_le_tilt_ne_baisse_JAMAIS_la_barre_un_net_negatif_reste_a_zero():
    nets = {"BTC": 2.0, "PERDANT": -1.0}
    avec = poids_par_rendement(nets, qualite_par_coin={"PERDANT": 5.0})  # facteur énorme
    assert "PERDANT" not in avec                                         # un perdant reste EXCLU


def test_un_facteur_aberrant_est_CLAMPE_par_securite():
    """Même si un appelant passe 5.0, l'allocation le ramène à [0.90, 1.10] : un tilt ne peut pas
    renverser l'ordre du net³ ni fabriquer un gagnant."""
    nets = {"A": 1.0, "B": 1.0}
    borne = poids_par_rendement(nets, qualite_par_coin={"A": FACTEUR_MAX})
    aberrant = poids_par_rendement(nets, qualite_par_coin={"A": 999.0})
    assert borne == aberrant                                            # 999 clampé à FACTEUR_MAX


def test_allouer_marges_accepte_le_tilt_et_garde_ses_garde_fous():
    # 3 coins pour que le plafond de concentration ne force pas l'égalité ; on compare AVEC vs SANS
    # tilt sur le MÊME coin (robuste au plafond) : le tilt donne strictement plus à BTC.
    nets = {"BTC": 1.0, "ETH": 1.0, "SOL": 1.0}
    sans = allouer_marges(nets, capital_usd=1000.0)
    avec = allouer_marges(nets, capital_usd=1000.0, qualite_par_coin={"BTC": FACTEUR_MAX})
    assert avec["BTC"] > sans["BTC"] and avec["ETH"] > 0                 # BTC renforcé, ETH toujours financé
