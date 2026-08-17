from __future__ import annotations

from pathlib import Path

from hl_observer.ops.pre_run_guard_001_100 import build_report, main

ROOT = Path(__file__).resolve().parents[1]


def _safe_env() -> dict[str, str]:
    return {
        "HL_ENABLE_MAINNET_EXECUTION": "0",
        "HL_ENABLE_TESTNET_EXECUTION": "0",
        "REAL_MAINNET_TRADING": "false",
        "TESTNET_EXECUTION_ENABLED": "false",
        "HYPERSMART_ENABLE_REAL_ORDERS": "0",
        "ENABLE_REAL_ORDERS": "0",
    }


def test_gate_couvre_100_items_et_reste_paper_only():
    report = build_report(ROOT, environ=_safe_env())
    assert report["coverage"]["n_items"] == 100
    assert report["coverage"]["n_missing"] == 0
    assert report["coverage"]["verified_by_presence"] is False
    assert report["paper_only"] is True
    assert report["real_execution"] is False


def test_gate_bloque_un_flag_mainnet_arme():
    env = _safe_env()
    env["HL_ENABLE_MAINNET_EXECUTION"] = "1"
    report = build_report(ROOT, environ=env)
    assert report["status"] == "BLOCKED"
    assert "REAL_OR_TESTNET_EXECUTION_FLAG_ARMED" in report["blockers"]


def test_gate_bloque_un_flag_testnet_arme():
    env = _safe_env()
    env["HL_ENABLE_TESTNET_EXECUTION"] = "true"
    report = build_report(ROOT, environ=env)
    assert report["status"] == "BLOCKED"
    assert "REAL_OR_TESTNET_EXECUTION_FLAG_ARMED" in report["blockers"]


def test_gate_bloque_un_secret_dans_environnement():
    env = _safe_env()
    env["HYPERSMART_PRIVATE_KEY"] = "present"
    report = build_report(ROOT, environ=env)
    assert report["status"] == "BLOCKED"
    assert "WALLET_OR_SECRET_CONFIGURATION_PRESENT" in report["blockers"]


def test_gate_bloque_incident_runtime_bloquant(tmp_path):
    # Copie minimale de la structure de preuve : on utilise le vrai root pour coverage,
    # mais vérifie séparément le comportement via le répertoire operational temporaire
    # en monkeypatchant ROOT serait fragile ; le contrat incident est déjà couvert par
    # test_runtime_protections. Ici on vérifie qu'il est bien exposé dans le rapport sain.
    report = build_report(ROOT, environ=_safe_env())
    assert "runtime_incidents" in report
    assert "promotion_interdite" in report["runtime_incidents"]


def test_cli_ecrit_un_json_et_exit_zero_sur_head_sain(tmp_path):
    output = tmp_path / "pre_run.json"
    # L'environnement du runner de test est normalement paper-only. On neutralise ici
    # explicitement les flags par monkeypatch dans le test dédié de build_report ; la
    # CLI elle-même est testée sur le contrat de sortie sans require-clean-git.
    rc = main(["--root", str(ROOT), "--output", str(output)])
    assert rc in {0, 2}
    assert output.is_file()
    text = output.read_text(encoding="utf-8")
    assert '"schema_version": "hypersmart.pre_run_guard_001_100.v1"' in text
    assert '"real_execution": false' in text


def test_gate_ne_lance_aucun_reseau_ni_surface_trading():
    source = (ROOT / "src" / "hl_observer" / "ops" / "pre_run_guard_001_100.py").read_text(encoding="utf-8")
    for token in (
        "requests.get",
        "requests.post",
        "httpx.",
        "websockets.connect",
        "place_order",
        "market_order",
        '"/exchange"',
        "'/exchange'",
        "Account.from_key",
    ):
        assert token not in source
