"""Univers officiel des marchés et liste de coins des collecteurs L2 (dex HIP-3 compris).

Faits vérifiés auprès de l'API officielle le 2026-11-11, que ces tests figent hors ligne :
``xyz:XYZ100`` et ``kPEPE`` sont des identifiants valides ; ``XYZ:XYZ100`` et ``KPEPE`` sont
refusés ; un seul abonnement WebSocket à un nom inconnu fait fermer toute la connexion.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.collection import univers_perps as U  # noqa: E402
from hl_observer.datasets import coffre_certifie as C  # noqa: E402
from hl_observer.ops import collecteur_registry as REG  # noqa: E402
import generer_coins_lanes as G  # noqa: E402
import watch_economic_collectors as WATCH  # noqa: E402


def _post(charge):
    if charge == {"type": "meta"}:
        return {"universe": [{"name": "BTC"}, {"name": "kPEPE"}, {"name": "VIEUX", "isDelisted": True}]}
    if charge == {"type": "perpDexs"}:
        return [None, {"name": "xyz"}, {"name": "km"}, {"name": "casse"}]
    if charge == {"type": "meta", "dex": "xyz"}:
        return {"universe": [{"name": "xyz:XYZ100"}, {"name": "xyz:NVDA"}]}
    if charge == {"type": "meta", "dex": "km"}:
        return {"universe": [{"name": "km:US500"}]}
    raise OSError("dex illisible")


def test_univers_officiel_dex_principal_et_hip3_sans_marches_retires():
    assert U.interroger_univers(_post) == {"": ["BTC", "kPEPE"], "xyz": ["xyz:XYZ100", "xyz:NVDA"], "km": ["km:US500"]}


def test_seuls_les_noms_exacts_sont_abonnables():
    univers = {"BTC", "kPEPE", "xyz:XYZ100"}
    demandes = ["BTC", "KPEPE", "kPEPE", "XYZ:XYZ100", "xyz:XYZ100", "xyz:xyz100", " BTC ", "", "INCONNU"]
    abonnables, inconnus = U.filtrer_abonnables(demandes, univers)
    assert abonnables == ["BTC", "kPEPE", "xyz:XYZ100"]
    assert inconnus == ["KPEPE", "XYZ:XYZ100", "xyz:xyz100", "INCONNU"]
    # vérification impossible : rien n'est rejeté sur la foi d'une vérification qui n'a pas eu lieu
    assert U.filtrer_abonnables(["BTC", "KPEPE"], None) == (["BTC", "KPEPE"], [])


def test_cache_de_l_univers_reprise_reseau_coupe_et_jamais_d_univers_invente(tmp_path):
    appels = []

    def post(charge):
        appels.append(charge)
        return _post(charge)

    def panne(charge):
        raise OSError("réseau coupé")

    assert U.charger_univers(tmp_path, post=panne, now=1_000.0) is None            # ni réseau ni cache
    univers = U.charger_univers(tmp_path, post=post, now=1_000.0)
    assert univers == {"BTC", "kPEPE", "xyz:XYZ100", "xyz:NVDA", "km:US500"}
    n = len(appels)
    assert U.charger_univers(tmp_path, post=post, now=1_000.0 + 3_600) == univers and len(appels) == n   # cache frais
    assert U.charger_univers(tmp_path, post=panne, now=1_000.0 + 48 * 3_600) == univers                  # cache ancien > rien
    # une réponse sans le dex principal n'écrase jamais le cache
    assert U.charger_univers(tmp_path, post=lambda c: {} if c == {"type": "meta"} else _post(c),
                             now=1_000.0 + 72 * 3_600) == univers


def test_liste_de_coins_ajouts_du_labo_verifies_et_plafonnes():
    univers = {"BTC", "kPEPE", "xyz:XYZ100", "xyz:NVDA", "km:US500"}
    resultat = G.composer(["BTC", "kPEPE", "DELISTE"], ["xyz:XYZ100", "XYZ:FAUX", "BTC", "xyz:NVDA", "km:US500"],
                          univers, max_coins=4)
    assert resultat["coins"] == ["BTC", "kPEPE", "xyz:XYZ100", "xyz:NVDA"]
    assert resultat["retires_inconnus_de_l_exchange"] == ["DELISTE"]
    assert resultat["demandes_refusees_inconnues"] == ["XYZ:FAUX"]
    assert resultat["demandes_hors_plafond"] == ["km:US500"]
    # univers non vérifiable : la liste existante est conservée, AUCUN nom non vérifié n'est ajouté
    sans = G.composer(["BTC", "kPEPE"], ["xyz:XYZ100"], None)
    assert sans["coins"] == ["BTC", "kPEPE"] and sans["ajoutes"] == [] and sans["univers_verifie"] is False


def test_generateur_ecrit_la_liste_locale_et_ne_publie_pas_sans_univers(tmp_path, monkeypatch):
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "copy_vault_coins.json").write_text(json.dumps({"coins": ["BTC", "kPEPE"]}), encoding="utf-8")
    (tmp_path / "runtime" / "data").mkdir(parents=True)
    (tmp_path / G.BESOINS).write_text(json.dumps({"needs": [
        {"need": "PRIX_MANQUANT"},
        {"need": "SPREAD_MANQUANT", "top_coins": ["ignore"], "coins_by_notional": [["xyz:XYZ100", 0.2], ["XYZ:FAUX", 0.1]]},
    ]}), encoding="utf-8")
    monkeypatch.setattr(G, "charger_univers", lambda root: {"BTC", "kPEPE", "xyz:XYZ100"})
    assert G.main(["--root", str(tmp_path)]) == 0
    locale = json.loads((tmp_path / G.LISTE_LOCALE).read_text(encoding="utf-8"))
    assert locale["coins"] == ["BTC", "kPEPE", "xyz:XYZ100"] and locale["_provenance"]["n_hip3"] == 1
    assert locale["_provenance"]["demandes_refusees_inconnues"] == ["XYZ:FAUX"]
    avant = (tmp_path / "config" / "copy_vault_coins.json").read_text(encoding="utf-8")
    monkeypatch.setattr(G, "charger_univers", lambda root: None)
    assert G.main(["--root", str(tmp_path), "--publier"]) == 3                       # jamais de publication à l'aveugle
    assert (tmp_path / "config" / "copy_vault_coins.json").read_text(encoding="utf-8") == avant


def test_les_lanes_ne_s_abonnent_jamais_a_un_marche_inconnu(tmp_path, monkeypatch):
    """Régression : un coin invalide dans la liste faisait fermer la connexion de toute la lane."""
    import asyncio

    spec = importlib.util.spec_from_file_location("lane_l2_test", RACINE / "tools" / "collecter_l2_lane.py")
    lane = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(lane)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "copy_vault_coins.json").write_text(
        json.dumps({"coins": ["BTC", "KPEPE", "xyz:XYZ100", "kPEPE"]}), encoding="utf-8")
    monkeypatch.setattr(lane, "charger_univers", lambda root: {"BTC", "kPEPE", "xyz:XYZ100"})
    abonnes: list[list[str]] = []

    async def fausse_connexion(lane_obj, coins, socket_id, deadline):
        abonnes.append(list(coins))

    monkeypatch.setattr(lane, "_connexion", fausse_connexion)
    # la liste locale demandée n'existe pas : repli sur la liste commitée
    args = lane.argparse.Namespace(
        root=str(tmp_path), coins_file="runtime/data/copy_vault_coins_local.json", shard_index=0, shard_count=1,
        coins_par_connexion=40, duree_s=10.0, out="", bbo_out="", heartbeat="")
    assert asyncio.run(lane._boucle(args)) == 0
    assert abonnes == [["BTC", "xyz:XYZ100", "kPEPE"]]
    sante = json.loads((tmp_path / "runtime" / "data" / "l2_lane_sante_0.json").read_text(encoding="utf-8"))
    assert sante["marches_inconnus_non_abonnes"] == ["KPEPE"]


def test_le_collecteur_l2_des_leaders_est_lance_par_le_profil_du_lanceur_et_certifie():
    entree = next(c for c in REG.REGISTRE if c["nom"] == "l2-leaders")
    assert entree["script"] == "tools/collecter_l2_lane.py" and (RACINE / entree["script"]).is_file()
    assert entree["paper_read_only"] is True and entree["real_execution"] is False
    assert "l2-leaders" in WATCH.DEFAULT_NAMES and "l2-leaders" in REG.COLLECTEURS_HARVEST
    assert "vault-collector" in WATCH.DEFAULT_NAMES                    # historique des vaults : même lanceur
    # le ruban qu'il écrit est connu du certificateur (famille des carnets), jamais « INCONNU »
    assert C.detecter_famille("copy_vault_l2_lane.jsonl") == (C.FAMILLE_BOOK_L2, "HYPERLIQUID_L2_WS")
    assert C.detecter_famille("copy_vault_bbo_lane.jsonl")[0] == C.FAMILLE_BBO
    lanceur = (RACINE / "LANCER_COLLECTEURS_COPY_VAULT.cmd").read_text(encoding="utf-8", errors="replace")
    assert "generer_coins_lanes.py" in lanceur
