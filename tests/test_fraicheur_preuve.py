"""UN RAPPORT VERT DU 12 NE PROUVE PAS L'ÉTAT DU 16 — et rien ne le signalait.

D'OÙ VIENT CE MODULE (chantier 13 de l'audit du 15/11). Le dernier rapport du labo datait du
12 novembre alors que la collecte observée était celle du 16. Quatre jours d'écart, aucune alerte.
Ces tests verrouillent la règle et son fail-closed : une date absente n'est pas « récente par
défaut ».
"""
from __future__ import annotations

import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
if str(RACINE / "src") not in sys.path:
    sys.path.insert(0, str(RACINE / "src"))

from hl_observer.ops import fraicheur_preuve as F  # noqa: E402

JOUR = 86_400_000
COLLECTE = 1_794_844_000_000          # 16/11/2026


def test_une_chaine_a_jour_est_FRAICHE():
    r = F.evaluer(collecte_ms=COLLECTE, elements={
        "dernier_lot_certifie": COLLECTE - 600_000,
        "dernier_rapport_labo": COLLECTE - 1_200_000,
    })
    assert r["statut"] == F.FRAIS and r["en_retard"] == []
    assert "couvre la collecte" in F.message(r)


def test_le_cas_REEL_du_16_novembre_est_PERIME():
    """Rapport du labo du 12/11 contre une collecte du 16/11 : quatre jours de retard."""
    r = F.evaluer(collecte_ms=COLLECTE, elements={
        "dernier_lot_certifie": COLLECTE - 600_000,
        "dernier_rapport_labo": COLLECTE - 4 * JOUR,
    })
    assert r["statut"] == F.PERIME
    assert r["en_retard"] == ["dernier_rapport_labo"]
    assert any(raison.startswith("dernier_rapport_labo:RETARD_9") for raison in r["raisons"]), (
        f"raisons : {r['raisons']}")
    assert "ne couvre PAS" in F.message(r)


def test_un_horodatage_ABSENT_ferme_la_porte_au_lieu_d_etre_recent_par_defaut():
    for absent in (None, 0, -1, "hier", 1.5, True):
        r = F.evaluer(collecte_ms=COLLECTE, elements={"dernier_safe_restaure": absent})
        assert r["statut"] == F.INCONNU, f"{absent!r} ne doit pas passer pour frais"
        assert r["en_retard"] == ["dernier_safe_restaure"]
        assert "dernier_safe_restaure:HORODATAGE_ABSENT" in r["raisons"]


def test_une_collecte_sans_horodatage_rend_TOUT_inconnu():
    r = F.evaluer(collecte_ms=None, elements={"dernier_lot_certifie": COLLECTE})
    assert r["statut"] == F.INCONNU and r["raisons"] == ["COLLECTE_SANS_HORODATAGE"]
    assert r["en_retard"] == ["dernier_lot_certifie"]


def test_aucun_element_a_verifier_n_est_pas_une_bonne_nouvelle():
    r = F.evaluer(collecte_ms=COLLECTE, elements={})
    assert r["statut"] == F.INCONNU and "AUCUN_ELEMENT_A_VERIFIER" in r["raisons"]


def test_la_tolerance_absorbe_une_passe_de_scellage_sans_tout_declarer_perime():
    """La certification tourne toutes les 30 min : un retard de 40 min est en route, pas perime."""
    r = F.evaluer(collecte_ms=COLLECTE, elements={"dernier_lot_certifie": COLLECTE - 40 * 60_000})
    assert r["statut"] == F.FRAIS
    juste_au_dela = F.evaluer(collecte_ms=COLLECTE, elements={
        "dernier_lot_certifie": COLLECTE - F.RETARD_TOLERE_MS - 1})
    assert juste_au_dela["statut"] == F.PERIME


def test_un_element_en_AVANCE_sur_la_collecte_n_est_pas_en_retard():
    """Un lot scellé après la dernière ligne lue est normal : le retard devient négatif."""
    r = F.evaluer(collecte_ms=COLLECTE, elements={"dernier_lot_certifie": COLLECTE + 5_000})
    assert r["statut"] == F.FRAIS and r["retards_ms"]["dernier_lot_certifie"] == -5_000


# ───────── 17/11 : LES HORLOGES SE LISENT DANS LES FAITS, PAS DANS DES DATES DE FICHIER ─────────
#
# DEUX FAIBLESSES DE LA VERSION DU 16/11, toutes deux dans mon propre contrôle :
#
# 1. `dernier_rapport_labo` était l'HEURE D'ÉCRITURE du dernier `resultat.json`. Une simple
#    pré-vérification (statut PREFLIGHT_ONLY, aucun rejeu) écrit un tel fichier : elle suffisait à
#    faire taire l'alerte. C'est arrivé le 17/11 à 13:36 — le tunnel annonçait « 115 h de retard »
#    juste avant, et l'aurait annoncé « frais » juste après, sans qu'une seule donnée ait été lue.
# 2. L'âge du tier SAFE n'entrait pas dans le verdict, alors que SEULE une chaîne SAFE peut
#    soutenir une preuve. Mesuré : dernier tag SAFE le 18/10, soit 734 h avant la collecte.
import json as _json


def _ecrire_resultat(racine, nom, charge):
    dossier = racine / "runtime" / "reports" / "copy_vault_quant_lab" / nom
    dossier.mkdir(parents=True, exist_ok=True)
    (dossier / "resultat.json").write_text(_json.dumps(charge), encoding="utf-8")


def test_une_PRE_VERIFICATION_ne_rajeunit_pas_la_chaine_de_preuve(tmp_path):
    """Le défaut exact : un fichier récent qui n'a rien rejoué ne doit pas faire taire l'alerte."""
    _ecrire_resultat(tmp_path, "20261112T160515Z", {
        "status": "MORE_DATA",
        "economic_result": {"safe_inputs": {"fill_end_ms": 1_794_497_124_081,
                                            "book_end_ms": 1_794_497_165_275}}})
    _ecrire_resultat(tmp_path, "20261117T133616Z", {"status": "PREFLIGHT_ONLY"})   # plus récent
    horloges = F.horloges_de_la_chaine(tmp_path)
    assert horloges["dernier_rapport_labo"] == 1_794_497_124_081, (
        "l'horloge du labo est la fin des donnees REJOUEES, pas la date du dernier fichier")


def test_la_fin_utile_est_le_PLUS_PETIT_des_deux_derniers_instants():
    """Une chaîne causale a besoin des fills ET des carnets."""
    assert F.fin_des_donnees_rejouees(
        {"status": "MORE_DATA", "safe_inputs": {"fill_end_ms": 900, "book_end_ms": 500}}) == 500
    assert F.fin_des_donnees_rejouees({"status": "PREFLIGHT_ONLY",
                                        "safe_inputs": {"fill_end_ms": 9, "book_end_ms": 9}}) is None
    assert F.fin_des_donnees_rejouees({"status": "MORE_DATA"}) is None
    assert F.fin_des_donnees_rejouees(
        {"status": "OK", "safe_inputs": {"fill_end_ms": 9, "book_end_ms": None}}) is None


def test_l_age_du_tier_SAFE_entre_dans_le_verdict(tmp_path):
    index = tmp_path / "runtime" / "coffre_certifie" / "COFFRE_INDEX.json"
    index.parent.mkdir(parents=True, exist_ok=True)
    index.write_text(_json.dumps({"tiers": {"SAFE_CLOUD": {"derniers_tags": [
        "data-v2-campaign-copy-vault-e8-broad-2026101716-v8-u0",
        "data-v2-campaign-copy-vault-e8-broad-2026101800-v8-u0"]}}}), encoding="utf-8")
    horloges = F.horloges_de_la_chaine(tmp_path)
    assert horloges["dernier_tag_safe"] == F.date_du_tag_ms("x-2026101800-v8"), "le plus recent des tags"
    collecte = F.date_du_tag_ms("x-2026111712-v8")
    rapport = F.evaluer(collecte_ms=collecte, elements={"dernier_tag_safe": horloges["dernier_tag_safe"]})
    assert rapport["statut"] == F.PERIME
    assert rapport["retards_ms"]["dernier_tag_safe"] // 3_600_000 == 732


def test_sans_aucun_fait_lisible_tout_est_INCONNU_et_la_porte_reste_fermee(tmp_path):
    horloges = F.horloges_de_la_chaine(tmp_path)
    assert horloges == {"dernier_lot_certifie": None, "dernier_rapport_labo": None,
                        "dernier_tag_safe": None}
    assert F.evaluer(collecte_ms=1_790_000_000_000, elements=horloges)["statut"] == F.INCONNU


def test_un_tag_sans_date_ne_fabrique_pas_d_horloge():
    assert F.date_du_tag_ms("data-v2-sans-date") is None
    assert F.date_du_tag_ms("x-2026139900-v8") is None, "mois 13 : date impossible, donc absente"
