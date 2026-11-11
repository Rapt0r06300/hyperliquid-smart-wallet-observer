"""AlinaSync : les lanes cloud « marché » et « contexte » sont rapatriées, validées par le certificateur."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))
sys.path.insert(0, str(RACINE / "tools"))

from hl_observer.datasets import coffre_certifie as C  # noqa: E402
import telecharger_lanes_certifiees_github as T  # noqa: E402

NOW = 1_800_000_000_000
VAULT = "0xca230e816bdb34a46960c2f978a30a563d1ae9e0"


def _trade(tid: int, *, price: float = 100.0, coin: str = "xyz:XYZ100") -> dict:
    return {"schema_version": "hypersmart.copy_vault_trades.v1", "coin": coin, "exchange_ts_ms": NOW - 5_000 + tid,
            "received_at_ms": NOW - 4_000 + tid, "price": price, "size": 1.5, "aggressor_side": "BUY",
            "hash": f"0x{tid:064x}", "tid": tid, "source": "HYPERLIQUID_TRADES_WS", "data_origin": "REAL_OBSERVED"}


def _position(szi: float, recu: int) -> dict:
    return {"schema_version": "hypersmart.copy_vault_positions.v1", "vault": VAULT, "coin": "kPEPE", "szi": szi,
            "received_at_ms": recu, "source": "CLEARINGHOUSE_WS"}


def _ecrire(path: Path, lignes: list) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join((l if isinstance(l, str) else json.dumps(l)) + "\n" for l in lignes), encoding="utf-8")


def test_chaque_lane_cloud_a_un_rapatriement_et_chaque_ruban_une_famille_certifiable():
    workflows = {p.name for p in (RACINE / ".github" / "workflows").glob("*.yml")}
    for lane, (workflow, rubans) in T.LANES.items():
        assert workflow in workflows, lane
        texte = (RACINE / ".github" / "workflows" / workflow).read_text(encoding="utf-8")
        for ruban in rubans:
            assert f"runtime/data/{ruban}" in texte           # le workflow publie bien ce ruban en artefact
            assert C.detecter_famille(ruban) is not None      # et le certificateur sait le juger
    lanceur = (RACINE / "ALINA_SYNC_COMPLETE.cmd").read_text(encoding="utf-8", errors="replace")
    assert "telecharger_lanes_certifiees_github.py" in lanceur


def test_seules_les_lignes_certifiables_et_nouvelles_sont_ajoutees_sans_reecrire_le_ruban(tmp_path):
    local = tmp_path / "runtime" / "data" / "copy_vault_trades_lane.jsonl"
    brut_local = json.dumps(_trade(1))
    _ecrire(local, [brut_local])
    artefacts = tmp_path / "artefacts"
    brut_2 = json.dumps(_trade(2), separators=(",", ":"))                       # mise en forme d'origine de la lane
    _ecrire(artefacts / "run-1" / "market-shard-0" / "copy_vault_trades_lane.jsonl",
            [_trade(1), brut_2, _trade(3, price=0.0), "pas du json"])
    _ecrire(artefacts / "run-1" / "market-shard-1" / "copy_vault_trades_lane.jsonl", [brut_2, _trade(4)])

    bilan = T.fusionner_ruban(tmp_path, artefacts, "copy_vault_trades_lane.jsonl", now_ms=NOW)

    lignes = local.read_text(encoding="utf-8").splitlines()
    assert lignes[0] == brut_local and lignes[1] == brut_2                       # ajout seul, ligne conservée telle quelle
    assert [json.loads(l)["tid"] for l in lignes] == [1, 2, 4]
    assert bilan["ajoutees"] == 2 and bilan["doublons"] == 2 and bilan["rejetees"] == 2
    assert bilan["raisons_rejet"]["px_invalide"] == 1 and bilan["raisons_rejet"]["json_invalide"] == 1
    # rejouer le rapatriement n'ajoute rien
    assert T.fusionner_ruban(tmp_path, artefacts, "copy_vault_trades_lane.jsonl", now_ms=NOW)["ajoutees"] == 0
    assert len(local.read_text(encoding="utf-8").splitlines()) == 3


def test_les_positions_des_leaders_arrivent_jusqu_au_coffre(tmp_path):
    """Chaîne complète : artefact de lane → ruban local → certification → index du coffre."""
    import sceller_coffre_local as scl

    artefacts = tmp_path / "artefacts"
    _ecrire(artefacts / "run-9" / "contexte-shard-0" / "copy_vault_positions_lane.jsonl",
            [_position(10.0, NOW - 60_000), _position(12.0, NOW - 30_000), _position(float("nan"), NOW - 10_000),
             _position(5.0, NOW + 3_600_000)])                                   # NaN et horodatage futur : refusés
    bilan = T.fusionner_ruban(tmp_path, artefacts, "copy_vault_positions_lane.jsonl", now_ms=NOW)
    assert bilan["ajoutees"] == 2 and bilan["famille"] == C.FAMILLE_POSITION and bilan["rejetees"] == 2

    assert scl.main(["--root", str(tmp_path), "--now-ms", str(NOW)]) == 0
    index = json.loads((tmp_path / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
    positions = [s for s in index["shards"] if s["famille"] == C.FAMILLE_POSITION]
    assert len(positions) == 1 and positions[0]["deposes"] == 2 and positions[0]["coins"] == ["kPEPE"]


def test_rapatriement_complet_avec_un_gh_simule_et_sans_gh(tmp_path):
    appels: list[list[str]] = []

    def faux_gh(args, cwd):
        appels.append(args)
        if args == ["--version"]:
            return subprocess.CompletedProcess(args, 0, "gh 2", "")
        if args[:2] == ["run", "list"]:
            runs = [{"databaseId": 7, "status": "completed", "conclusion": "success"},
                    {"databaseId": 8, "status": "completed", "conclusion": "failure"},
                    {"databaseId": 9, "status": "in_progress", "conclusion": None}]
            return subprocess.CompletedProcess(args, 0, json.dumps(runs), "")
        if args[:2] == ["run", "download"]:
            dest = Path(args[args.index("-D") + 1])
            _ecrire(dest / "market-shard-0" / "copy_vault_trades_lane.jsonl", [_trade(11), _trade(12)])
            return subprocess.CompletedProcess(args, 0, "", "")
        return subprocess.CompletedProcess(args, 1, "", "inconnu")

    res = T.telecharger_et_fusionner(tmp_path, "market", gh=faux_gh, now_ms=NOW)
    assert res["statut"] == "OK" and res["runs"] == 1
    assert {r["ruban"]: r["ajoutees"] for r in res["rubans"]} == {
        "copy_vault_trades_lane.jsonl": 2, "copy_vault_candle_lane.jsonl": 0}
    assert ["run", "download", "7"] == [a for a in appels if a[:2] == ["run", "download"]][0][:3]   # seul le run réussi

    def sans_gh(args, cwd):
        raise OSError("gh absent")

    avant = (tmp_path / "runtime" / "data" / "copy_vault_trades_lane.jsonl").read_text(encoding="utf-8")
    assert T.telecharger_et_fusionner(tmp_path, "market", gh=sans_gh)["statut"] == "gh_indisponible"
    assert (tmp_path / "runtime" / "data" / "copy_vault_trades_lane.jsonl").read_text(encoding="utf-8") == avant
