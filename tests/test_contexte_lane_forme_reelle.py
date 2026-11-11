"""Lane « contexte » : forme RÉELLE du message WebSocket ``clearinghouseState`` et portefeuilles complets.

Message observé auprès de l'API officielle le 2026-11-11 :
``{"channel": "clearinghouseState", "data": {"clearinghouseState": {...}, "dex": "", "user": "0x…"}}``.
L'ancien parseur lisait ``assetPositions`` au premier niveau de ``data`` : il ne trouvait rien, et
les lanes cloud n'avaient jamais écrit une seule position. Les anciens tests validaient une forme
à plat qui n'est pas celle du WebSocket.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.backtesting import copy_vault_copiability as cop  # noqa: E402
from hl_observer.datasets import coffre_certifie as CERT  # noqa: E402
import collecter_contexte_lane as L  # noqa: E402

NOW = 1_794_410_000_000
USER = "0x1e37a337ed460039d1b15bd3bc489de789768d5e"


def _message(positions, *, dex: str = "", valeur: str = "13340863.26") -> dict:
    """Forme réelle (valeurs abrégées) du champ ``data`` d'un message ``clearinghouseState``."""
    return {"dex": dex, "user": USER, "clearinghouseState": {
        "assetPositions": [{"type": "oneWay", "position": p} for p in positions],
        "marginSummary": {"accountValue": valeur, "totalNtlPos": "5234082.5"},
        "crossMarginSummary": {}, "crossMaintenanceMarginUsed": "0", "withdrawable": "0", "time": NOW - 40}}


BTC = {"coin": "BTC", "szi": "2.41355", "leverage": {"type": "cross", "value": 40}, "entryPx": "79404.5",
       "positionValue": "177965.5228", "unrealizedPnl": "-13681.38907"}
KPEPE = {"coin": "kPEPE", "szi": "-150000", "leverage": {"type": "cross", "value": 10}, "entryPx": "0.0049",
         "positionValue": "741.15", "unrealizedPnl": "12.5"}
PLATE = {"coin": "ETH", "szi": "0.0", "positionValue": "0.0", "unrealizedPnl": "0.0"}


def test_les_positions_sont_lues_dans_l_etat_imbrique_du_message_reel():
    lignes = L.parser_positions(_message([BTC, KPEPE, PLATE]), user=USER, recv_ms=NOW)
    assert [(l["coin"], l["szi"]) for l in lignes] == [("BTC", 2.41355), ("kPEPE", -150000.0)]
    assert all(CERT.certifier_position(l, source="CLEARINGHOUSE_WS", now_ms=NOW)[1] == CERT.PASS for l in lignes)
    # la forme à plat (réponse REST) reste lue ; un message sans état ne produit rien
    assert len(L.parser_positions({"assetPositions": [{"position": BTC}]}, user=USER, recv_ms=NOW)) == 1
    assert L.parser_positions({"user": USER, "dex": ""}, user=USER, recv_ms=NOW) == []


def test_portefeuille_complet_avec_valeur_du_compte_et_portee_par_dex():
    snap = L.construire_portefeuille(_message([BTC, KPEPE, PLATE]), user=USER.upper(), recv_ms=NOW)
    assert snap["vault"] == USER and snap["ts_ms"] == NOW and snap["exchange_ts_ms"] == NOW - 40
    assert snap["nav_usd"] == 13340863.26 and snap["n_positions"] == 2
    assert [p["coin"] for p in snap["positions"]] == ["BTC", "kPEPE"]           # identité native, position plate omise
    assert snap["expo_brute_usd"] == round(177965.5228 + 741.15, 2)
    assert snap["expo_nette_usd"] == round(177965.5228 - 741.15, 2)             # le short compte en négatif
    assert snap["portfolio_scope"] == "DEX_PRINCIPAL" and snap["dex"] == ""
    assert CERT.certifier_record(snap, famille=CERT.FAMILLE_SNAPSHOT, source="CLEARINGHOUSE_WS", now_ms=NOW)[1] == CERT.PASS
    # compte à plat : une liste vide, pas une absence de ligne
    vide = L.construire_portefeuille(_message([]), user=USER, recv_ms=NOW)
    assert vide["positions"] == [] and vide["n_positions"] == 0 and vide["levier"] == 0.0
    # une position illisible invalide TOUT l'instantané (jamais de portefeuille amputé)
    assert L.construire_portefeuille(_message([BTC, {"coin": "SOL", "szi": "abc"}]), user=USER, recv_ms=NOW) is None
    assert L.construire_portefeuille({"user": USER}, user=USER, recv_ms=NOW) is None
    hip3 = L.construire_portefeuille(_message([{**BTC, "coin": "xyz:XYZ100"}], dex="xyz"), user=USER, recv_ms=NOW)
    assert hip3["portfolio_scope"] == "DEX:xyz" and hip3["positions"][0]["coin"] == "xyz:XYZ100"
    # même compte, même instant, deux dex : deux portefeuilles distincts pour le coffre
    assert CERT.identite(snap, CERT.FAMILLE_SNAPSHOT) != CERT.identite(hip3, CERT.FAMILLE_SNAPSHOT)
    assert CERT.identite(snap, CERT.FAMILLE_SNAPSHOT) == ("vault_snapshot", USER, NOW)   # identité historique inchangée


def test_un_instantane_n_est_ecrit_que_s_il_change_ou_comme_battement(tmp_path):
    lane = L.LaneContexte(tmp_path / "pos.jsonl", tmp_path / "twap.jsonl", tmp_path / "snap.jsonl")

    async def scenario():
        async def pousser(positions, t, dex=""):
            await lane.ecrire_portefeuille(L.construire_portefeuille(_message(positions, dex=dex), user=USER, recv_ms=t))

        await pousser([BTC], NOW)                                  # premier : écrit
        await pousser([BTC], NOW + 3_000)                          # inchangé : pas écrit
        await pousser([BTC, KPEPE], NOW + 5_000)                   # changé mais < 10 s : pas écrit
        await pousser([BTC, KPEPE], NOW + 11_000)                  # changé, 10 s écoulées : écrit
        await pousser([BTC, KPEPE], NOW + 200_000)                 # inchangé : pas écrit
        await pousser([BTC, KPEPE], NOW + 11_000 + L.BATTEMENT_PORTEFEUILLE_MS)   # battement : écrit
        await pousser([{**BTC, "coin": "xyz:GOLD"}], NOW + 12_000, dex="xyz")     # autre dex : suivi à part, écrit
        await lane.ecrire_portefeuille(None)

    asyncio.run(scenario())
    lignes = [json.loads(l) for l in (tmp_path / "snap.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [(l["ts_ms"] - NOW, l["dex"], l["n_positions"]) for l in lignes] == [
        (0, "", 1), (11_000, "", 2), (12_000, "xyz", 1), (11_000 + L.BATTEMENT_PORTEFEUILLE_MS, "", 2)] or \
        sorted((l["ts_ms"] - NOW, l["dex"], l["n_positions"]) for l in lignes) == sorted([
            (0, "", 1), (11_000, "", 2), (12_000, "xyz", 1), (11_000 + L.BATTEMENT_PORTEFEUILLE_MS, "", 2)])
    assert lane.portefeuilles == 4


def test_l_etude_de_replication_n_additionne_pas_les_portefeuilles_de_dex_differents():
    """Un portefeuille HIP-3 ne contient pas les positions du dex principal : le lire comme complet
    ferait croire que tout le reste vient d'être fermé (faux signal de vente)."""
    principal_1 = L.construire_portefeuille(_message([BTC, KPEPE]), user=USER, recv_ms=NOW)
    hip3 = L.construire_portefeuille(_message([{**BTC, "coin": "xyz:GOLD"}], dex="xyz"), user=USER, recv_ms=NOW + 1_000)
    principal_2 = L.construire_portefeuille(_message([BTC]), user=USER, recv_ms=NOW + 60_000)
    evenements, vus, rejets = cop.position_events_from_snapshots([principal_1, hip3, principal_2])
    assert rejets == {"portefeuille_autre_dex_non_fusionne": 1}
    assert list(vus[USER]) == [NOW, NOW + 60_000]
    changements = [(r.coin, r.start_pos, r.after) for r in evenements.itertuples()]
    assert changements == [("BTC", 0.0, 2.41355), ("kPEPE", 0.0, -150000.0), ("kPEPE", -150000.0, 0.0)]


def test_le_workflow_publie_les_portefeuilles_et_alinasync_les_rapatrie():
    import telecharger_lanes_certifiees_github as T

    workflow = (RACINE / ".github" / "workflows" / "copy-vault-contexte-lanes.yml").read_text(encoding="utf-8")
    assert "runtime/data/copy_vault_snapshots_lane.jsonl" in workflow
    assert "copy_vault_snapshots_lane.jsonl" in T.LANES["contexte"][1]
    assert CERT.detecter_famille("copy_vault_snapshots_lane.jsonl") == (CERT.FAMILLE_SNAPSHOT, "CLEARINGHOUSE_WS")
    assert L.SNAP_OUT.name == "copy_vault_snapshots_lane.jsonl"
