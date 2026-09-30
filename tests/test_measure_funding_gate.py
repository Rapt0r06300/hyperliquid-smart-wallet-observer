"""Le seuil d'entrée du Grinder est-il atteignable ? (2026-07-11)

Le funding-arb est la SEULE stratégie « grinder » réellement câblée, et elle n'a jamais tradé.
Son verrou d'entrée exige 2,5 bps de funding **par heure**. Ces tests verrouillent la mesure —
pas la conclusion : c'est la donnée réelle qui tranchera, pas moi.

Ce qui est testé ici, c'est que l'outil de mesure ne MENT pas :
  * il convertit correctement le taux décimal de l'API en bps ;
  * il détecte un VERROU MORT (aucun marché ne passe) au lieu de le masquer ;
  * il ne fabrique aucun chiffre quand la donnée manque.

Lecture seule. Aucun ordre réel.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

from measure_funding_gate import gate_report  # noqa: E402


def test_the_decimal_rate_is_converted_to_bps():
    """L'API renvoie 0,000125 (= 0,0125 %/h). En bps : 1,25. Une erreur d'échelle ici
    fausserait TOUT le diagnostic du Grinder."""
    rep = gate_report([("BTC", 0.000125)], seuil_bps_h=2.5)
    assert rep["mediane_bps_par_heure"] == 1.25


def test_a_dead_gate_is_named_as_such():
    """LE CŒUR : si aucun marché ne franchit le seuil, l'outil doit le DIRE, pas l'enterrer.

    Reproduction du soupçon : funding typique ~0,125 bps/h contre un seuil à 2,5 bps/h.
    """
    rows = [(f"C{i}", 0.0000125) for i in range(50)]        # 0,125 bps/h partout
    rep = gate_report(rows, seuil_bps_h=2.5)
    assert rep["marches_au_dessus_du_seuil"] == 0
    assert rep["part_au_dessus_du_seuil"] == 0.0
    assert rep["verdict"].startswith("VERROU_MORT")


def test_the_sign_does_not_matter_only_the_magnitude():
    """Le delta-neutre prend la jambe qui REÇOIT : un funding négatif est tout aussi exploitable."""
    positif = gate_report([("A", 0.0005)], seuil_bps_h=2.5)
    negatif = gate_report([("A", -0.0005)], seuil_bps_h=2.5)
    assert positif["mediane_bps_par_heure"] == negatif["mediane_bps_par_heure"] == 5.0
    assert negatif["marches_au_dessus_du_seuil"] == 1


def test_a_passing_gate_is_not_flagged_as_dead():
    """Symétrie de l'honnêteté : ne pas crier au verrou mort quand le seuil passe."""
    rows = [(f"C{i}", 0.0005) for i in range(20)]           # 5 bps/h : au-dessus du seuil
    rep = gate_report(rows, seuil_bps_h=2.5)
    assert rep["part_au_dessus_du_seuil"] == 1.0
    assert rep["verdict"].startswith("PASSANT")


def test_a_selective_gate_is_described_honestly():
    rows = [("HOT", 0.0005)] + [(f"C{i}", 0.0000125) for i in range(19)]   # 1 sur 20
    rep = gate_report(rows, seuil_bps_h=2.5)
    assert rep["marches_au_dessus_du_seuil"] == 1
    assert rep["exemples_au_dessus"] == ["HOT"]
    assert "SELECTIF" in rep["verdict"] or "QUASI-MORT" in rep["verdict"]


def test_no_data_invents_nothing():
    """VÉRITÉ DES DONNÉES : pas de donnée -> pas de chiffre inventé."""
    rep = gate_report([], seuil_bps_h=2.5)
    assert rep["verdict"] == "AUCUNE_DONNEE"
    assert "mediane_bps_par_heure" not in rep


def test_garbage_never_crashes_the_report():
    rep = gate_report([("A", 0.0)], seuil_bps_h=2.5)
    assert rep["marches"] == 1
    assert rep["mediane_bps_par_heure"] == 0.0
