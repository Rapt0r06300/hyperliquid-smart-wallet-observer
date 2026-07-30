"""Sources de fills : normalisation, autorité de la source, streaming avec reprise.

Le test qui protège le projet : `test_un_miroir_non_verifie_nest_jamais_autoritatif`. Un edge mesuré sur des
données dont on ne peut pas prouver la provenance n'est pas un edge, c'est une rumeur.

Paper/read-only : 0 réseau, 0 ordre réel, 0 clé, 0 signature.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.following import fills_sources as FS  # noqa: E402

T0 = 1_700_000_000_000


def _ecrire(tmp_path, lignes, nom="f.jsonl"):
    p = tmp_path / nom
    p.write_text("\n".join(json.dumps(x) if isinstance(x, dict) else str(x) for x in lignes) + "\n",
                 encoding="utf-8")
    return p


# ═══════════════ autorité de la source ═══════════════
def test_un_miroir_non_verifie_nest_jamais_autoritatif():
    assert FS.est_autoritative("node_fills_by_block") is True
    assert FS.est_autoritative("vault_fills") is True
    assert FS.est_autoritative("miroir_non_verifie") is False
    fill, _ = FS.normaliser_fill(
        {"user": "0xa", "coin": "BTC", "sz": 1, "px": 100, "time": T0, "side": "B"},
        source="miroir_non_verifie")
    assert fill["autoritative"] is False


def test_une_source_inconnue_nest_jamais_autoritative():
    assert FS.est_autoritative("un_truc_trouve_sur_internet") is False
    fill, motif = FS.normaliser_fill({"user": "0xa"}, source="un_truc_trouve_sur_internet")
    assert fill is None and motif == "SOURCE_INCONNUE"


# ═══════════════ normalisation des schémas réels ═══════════════
def test_le_schema_vault_fills_est_normalise_avec_start_position():
    brut = {"vault": "0xABC", "ts_ms": T0, "coin": "btc", "px": 62088.0, "sz": 0.05,
            "signe": 1, "dir": "Open Long", "start_position": 74.27, "oid": 495129870817}
    fill, motif = FS.normaliser_fill(brut, source="vault_fills")
    assert motif is None
    assert fill["user"] == "0xabc" and fill["coin"] == "BTC"      # normalisation de casse
    assert fill["start_pos"] == 74.27 and fill["time"] == T0
    assert fill["autoritative"] is True


def test_le_signe_est_traduit_en_side_quand_side_manque():
    achat, _ = FS.normaliser_fill({"vault": "0xa", "coin": "BTC", "px": 1.0, "sz": 1.0,
                                   "ts_ms": T0, "signe": 1}, source="vault_fills_live")
    vente, _ = FS.normaliser_fill({"vault": "0xa", "coin": "BTC", "px": 1.0, "sz": 1.0,
                                   "ts_ms": T0, "signe": -1}, source="vault_fills_live")
    assert achat["side"] == "B" and vente["side"] == "A"


def test_le_hash_sert_de_tid_quand_tid_manque():
    fill, _ = FS.normaliser_fill({"vault": "0xa", "coin": "BTC", "px": 1.0, "sz": 1.0,
                                  "ts_ms": T0, "signe": 1, "hash": "0xdead"}, source="vault_fills_live")
    assert fill["tid"] == "0xdead"


def test_le_schema_officiel_node_fills_est_reconnu():
    brut = {"user": "0xF00", "coin": "ETH", "sz": "2.5", "px": "3000.5", "time": T0,
            "startPosition": "-1.5", "side": "A", "tid": 42, "twapId": "tw9"}
    fill, motif = FS.normaliser_fill(brut, source="node_fills_by_block")
    assert motif is None and fill["start_pos"] == -1.5 and fill["twap_id"] == "tw9"
    assert fill["sz"] == 2.5 and fill["px"] == 3000.5           # chaines converties


# ═══════════════ deny-by-default ═══════════════
def test_chaque_champ_manquant_a_son_motif():
    base = {"vault": "0xa", "coin": "BTC", "px": 1.0, "sz": 1.0, "ts_ms": T0, "signe": 1}
    cas = {"WALLET_OU_COIN_ABSENT": {"vault": None}, "TAILLE_ABSENTE": {"sz": 0},
           "PRIX_ABSENT": {"px": None}, "HORODATAGE_ABSENT": {"ts_ms": None},
           "SENS_INCONNU": {"signe": None}}
    for motif_attendu, patch in cas.items():
        brut = {**base, **patch}
        fill, motif = FS.normaliser_fill(brut, source="vault_fills")
        assert fill is None and motif == motif_attendu, motif_attendu


def test_un_champ_absent_nest_jamais_complete():
    fill, _ = FS.normaliser_fill({"vault": "0xa", "coin": "BTC", "px": 1.0, "sz": 1.0,
                                  "ts_ms": T0, "signe": 1}, source="vault_fills")
    assert "start_pos" not in fill and "twap_id" not in fill     # absent reste absent


# ═══════════════ validation d'échantillon ═══════════════
def test_la_validation_voit_labsence_de_prix_sur_200_lignes(tmp_path):
    p = _ecrire(tmp_path, [{"adresse": "0xa", "coin": "BTC", "side": "LONG", "ts_ms": T0}] * 20)
    r = FS.valider_schema(p, source="node_fills_by_block")
    assert r["statut"] == "AUCUN_FILL_EXPLOITABLE" and r["utilisable"] is False
    assert r["refus"]["WALLET_OU_COIN_ABSENT"] == 20 or r["refus"].get("TAILLE_ABSENTE") == 20


def test_la_validation_signale_la_presence_de_start_pos(tmp_path):
    p = _ecrire(tmp_path, [{"vault": "0xa", "coin": "BTC", "px": 1.0, "sz": 1.0, "ts_ms": T0,
                            "signe": 1, "start_position": 3.0}] * 5)
    r = FS.valider_schema(p, source="vault_fills")
    assert r["statut"] == "VALIDE" and r["start_pos_disponible"] is True
    assert r["taux_normalisable"] == 1.0


def test_la_validation_dune_source_non_autoritative_le_dit(tmp_path):
    p = _ecrire(tmp_path, [{"user": "0xa", "coin": "BTC", "px": 1.0, "sz": 1.0, "time": T0, "side": "B"}])
    r = FS.valider_schema(p, source="miroir_non_verifie")
    assert r["autoritative"] is False and "bootstrap" in r["note"]


def test_fichier_absent(tmp_path):
    r = FS.valider_schema(tmp_path / "rien.jsonl", source="vault_fills")
    assert r["statut"] == "FICHIER_ABSENT" and r["utilisable"] is False


# ═══════════════ streaming et reprise ═══════════════
def test_le_flux_compte_les_refus_sans_les_taire(tmp_path):
    p = _ecrire(tmp_path, [{"vault": "0xa", "coin": "BTC", "px": 1.0, "sz": 1.0, "ts_ms": T0, "signe": 1},
                           "PAS DU JSON", [1, 2],
                           {"vault": "0xa", "coin": "BTC", "px": 1.0, "ts_ms": T0, "signe": 1}])
    stats = FS.StatsIngestion()
    fills = list(FS.flux_fills(p, source="vault_fills", stats=stats))
    r = stats.resume()
    assert len(fills) == 1 and r["n_fills"] == 1
    assert r["refus"]["JSON_INVALIDE"] == 1 and r["refus"]["PAS_UN_OBJET"] == 1
    assert r["refus"]["TAILLE_ABSENTE"] == 1


def test_la_reprise_ne_relit_pas_ce_qui_est_deja_ingere(tmp_path):
    lignes = [{"vault": "0xa", "coin": "BTC", "px": 1.0, "sz": 1.0, "ts_ms": T0 + i, "signe": 1}
              for i in range(10)]
    p = _ecrire(tmp_path, lignes)
    ckpt = FS.Checkpoint.charger(tmp_path / "ckpt.json")
    premiers = list(FS.flux_fills(p, source="vault_fills", checkpoint=ckpt, max_fills=4))
    ckpt.enregistrer()
    assert len(premiers) == 4 and ckpt.offset > 0

    repris = FS.Checkpoint.charger(tmp_path / "ckpt.json")
    assert repris.offset == ckpt.offset and repris.n_fills == 4
    suivants = list(FS.flux_fills(p, source="vault_fills", checkpoint=repris))
    assert len(suivants) == 6                                   # les 4 premiers ne sont pas relus
    assert {f["time"] for f in premiers} & {f["time"] for f in suivants} == set()


def test_max_fills_borne_reellement_la_lecture(tmp_path):
    p = _ecrire(tmp_path, [{"vault": "0xa", "coin": "BTC", "px": 1.0, "sz": 1.0, "ts_ms": T0 + i,
                            "signe": 1} for i in range(100)])
    assert len(list(FS.flux_fills(p, source="vault_fills", max_fills=7))) == 7


def test_le_flux_est_un_generateur_pas_une_liste_en_ram(tmp_path):
    import types
    p = _ecrire(tmp_path, [{"vault": "0xa", "coin": "BTC", "px": 1.0, "sz": 1.0, "ts_ms": T0, "signe": 1}])
    assert isinstance(FS.flux_fills(p, source="vault_fills"), types.GeneratorType)


def test_securite_aucun_appel_reel():
    src = (RACINE / "src" / "hl_observer" / "following" / "fills_sources.py").read_text(encoding="utf-8")
    for interdit in ('"/exchange"', "'/exchange'", "requests.get", "requests.post", "import websocket",
                     "websockets.connect", "eth_account", "Account.from_key", "private_key"):
        assert interdit not in src, "appel interdit dans fills_sources: %s" % interdit
