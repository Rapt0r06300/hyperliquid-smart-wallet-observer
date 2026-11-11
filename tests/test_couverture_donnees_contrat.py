"""Contrat de couverture : aucun type de donnée collecté ne disparaît entre collecte, coffre et labo."""
from __future__ import annotations

import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.datasets import coffre_certifie as C  # noqa: E402
from hl_observer.datasets import couverture_donnees as R  # noqa: E402
import matrice_couverture_donnees as M  # noqa: E402
import sceller_coffre_local as scl  # noqa: E402

NOW = 1_800_000_000_000


def test_tout_fichier_connu_du_certificateur_est_repertorie_avec_son_producteur():
    connus = set(C._FICHIERS_CONNUS) | set(C.FICHIERS_NON_CERTIFIES)
    assert connus - set(R.flux_par_fichier()) == set()             # rien de certifiable n'est oublié du registre
    assert len({f.fichier for f in R.FLUX}) == len(R.FLUX)         # pas de doublon
    for flux in R.FLUX:
        assert flux.producteur and flux.contenu and flux.usage
        script = flux.producteur.split(" ")[0]
        chemin = RACINE / script if script.startswith("tools/") else RACINE / "src" / "hl_observer" / script
        assert chemin.is_file(), f"producteur introuvable pour {flux.fichier} : {script}"


def test_chaque_flux_est_soit_certifie_dans_sa_famille_soit_ecarte_avec_motif():
    for flux in R.FLUX:
        detecte, motif = C.detecter_famille(flux.fichier), C.motif_non_certifie(flux.fichier)
        if flux.famille is None:
            assert flux.labo == R.NON_CERTIFIE and motif is not None and motif[0] == flux.usage
            assert detecte is None                                 # jamais à la fois écarté et certifié
        elif flux.fichier == "vault_episodes.jsonl":
            assert detecte is None and motif is None               # reconnu par son contenu (reniflage)
        else:
            assert detecte is not None and detecte[0] == flux.famille and motif is None
            assert flux.labo in (R.CONSOMME, R.DISPONIBLE, R.AUXILIAIRE)


def test_chaque_famille_certifiable_a_un_usage_labo_declare():
    """Ajouter une famille au certificateur sans dire ce que le labo en fait casse ce test."""
    familles = {info[0] for info in C._FICHIERS_CONNUS.values()}
    usage = R.usage_par_famille()
    assert familles - set(usage) == set()
    # les familles porteuses du signal et du coût économique sont réellement consommées
    for famille in ("fills_forward", "fills_backfill", "snapshot", "allmids", "book_l2", "bbo", "asset_ctx", "micro_bbo"):
        assert usage[famille] == R.CONSOMME


def test_les_usages_consommes_pointent_vers_du_code_qui_lit_vraiment_la_famille():
    etude = (RACINE / "tools" / "etude_copiabilite.py").read_text(encoding="utf-8")
    for famille in ("fills_forward", "fills_backfill", "snapshot", "allmids", "book_l2", "bbo", "micro_bbo",
                    "asset_ctx", "candle"):
        assert f'"{famille}"' in etude, f"l'étude du labo ne sélectionne pas la famille {famille}"
    labo = (RACINE / "src" / "hl_observer" / "backtesting" / "copy_vault_tier_local.py").read_text(encoding="utf-8")
    assert "_cotation_collecteur_vers_labo" in labo            # cotations du collecteur BBO adaptées
    for famille in ("liquidation", "overshoot", "trades_marche", "venue_book", "venue_dispersion", "position"):
        assert f'"{famille}"' in labo


def _ecrire(path: Path, lignes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(l) + "\n" for l in lignes), encoding="utf-8")


def test_matrice_de_bout_en_bout_sur_une_collecte_simulee(tmp_path):
    """Collecte simulée → certification → index → matrice : OK, écarté justifié, inconnu signalé."""
    data = tmp_path / "runtime" / "data"
    vault = "0xca230e816bdb34a46960c2f978a30a563d1ae9e0"
    _ecrire(data / "vault_fills_poll.jsonl", [{
        "coin": "MINA", "px": "0.05", "sz": "3.0", "side": "B", "time": NOW - 1000, "tid": 1, "vault": vault,
        "source": "LIVE_POLL", "isSnapshot": False, "observed_at_ms": NOW - 500}])
    _ecrire(data / "vault_snapshots.jsonl", [{"vault": vault, "ts_ms": NOW - 900, "nav_usd": 10.0,
                                             "positions": [{"coin": "BTC", "szi": 1.0}]}])
    _ecrire(data / "bbo_tape.jsonl", [{"venue": "HL", "coin": "BTC", "bid": 1.0, "ask": 2.0,
                                       "recv_wall_ts_ms": NOW - 9, "event_id": "q1"}])
    _ecrire(data / "explorer_inferred_fills.jsonl", [{"vault": vault, "source": "EXPLORER_INFERRED", "certifie": False}])
    _ecrire(data / "flux_invente_demain.jsonl", [{"mystere": 1}])
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    matrice = M.construire(tmp_path)
    par_fichier = {l["fichier"]: l for l in matrice["types"]}
    assert par_fichier["vault_fills_poll.jsonl"]["verdict"] == "OK"
    assert par_fichier["vault_snapshots.jsonl"]["verdict"] == "OK" and par_fichier["vault_snapshots.jsonl"]["au_coffre_lignes"] == 1
    assert par_fichier["bbo_tape.jsonl"]["verdict"] == "OK"
    assert par_fichier["explorer_inferred_fills.jsonl"]["verdict"] == "HORS PÉRIMÈTRE JUSTIFIÉ"
    assert par_fichier["flux_invente_demain.jsonl"]["verdict"] == "MANQUANT"       # jamais ignoré en silence
    assert par_fichier["vault_ledger.jsonl"]["verdict"] == "NON TESTÉ"             # non émis dans cette collecte
    assert matrice["familles_sans_usage_labo"] == []
    assert M.main(["--root", str(tmp_path)]) == 3                                   # un manque fait échouer la commande
    assert "flux_invente_demain.jsonl" in (tmp_path / M.SORTIE / "MATRICE_COUVERTURE.md").read_text(encoding="utf-8")


def test_emis_mais_absent_du_coffre_est_un_manque_pas_un_ok(tmp_path):
    _ecrire(tmp_path / "runtime" / "data" / "hl_allmids_tape.jsonl", [{"ts_ms": NOW - 5, "mids": {"BTC": 1.0}}])
    ligne = {l["fichier"]: l for l in M.construire(tmp_path)["types"]}["hl_allmids_tape.jsonl"]
    assert ligne["verdict"] == "MANQUANT" and "Certificateur" in ligne["explication"]


def test_chaque_famille_certifiable_declare_sa_portee_safe_ou_local_seul():
    """Une nouvelle famille doit dire si elle a une contrepartie SAFE-cloud (sinon : exploratoire seulement)."""
    familles = {info[0] for info in C._FICHIERS_CONNUS.values()}
    assert familles - set(R.EQUIVALENT_SAFE) == set()
    # les données propres à ce PC sont bien déclarées sans contrepartie cloud
    for famille in ("fills_backfill", "vault_ledger", "allmids", "candle", "explorer_tx"):
        assert R.EQUIVALENT_SAFE[famille] == ()


def test_la_matrice_affiche_la_portee_de_chaque_famille(tmp_path):
    _ecrire(tmp_path / "runtime" / "data" / "hl_allmids_tape.jsonl", [{"ts_ms": NOW - 5, "mids": {"BTC": 1.0}}])
    _ecrire(tmp_path / "runtime" / "data" / "bbo_tape.jsonl", [{"venue": "HL", "coin": "BTC", "bid": 1.0, "ask": 2.0,
                                                               "recv_wall_ts_ms": NOW - 9, "event_id": "q1"}])
    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    matrice = M.construire(tmp_path, avec_safe=True)                 # pas de catalogue SAFE ici : dit, pas inventé
    assert matrice["catalogue_safe"] is None
    portee = {f["famille"]: f["portee"] for f in matrice["familles_au_coffre"]}
    assert portee["allmids"].startswith("LOCAL SEUL") and portee["bbo"] == "LOCAL + équivalent SAFE"
    assert "LOCAL SEUL" in M.rendre(matrice)
