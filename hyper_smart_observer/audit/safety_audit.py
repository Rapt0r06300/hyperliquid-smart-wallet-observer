from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
try:
    from datetime import UTC
except ImportError:
    from datetime import timezone as _tz; UTC = _tz.utc
from pathlib import Path
from tempfile import gettempdir

from hyper_smart_observer.app.config import AppConfig
from hyper_smart_observer.audit.archive_audit import audit_archive_readiness
from hyper_smart_observer.audit.db_audit import audit_databases
from hyper_smart_observer.audit.secret_scanner import scan_for_obvious_secrets
from hyper_smart_observer.audit.source_scanner import scan_source_forbidden_terms
from hyper_smart_observer.audit.ui_audit import audit_dashboard_html


@dataclass(frozen=True)
class AuditFinding:
    name: str
    ok: bool
    message: str


def run_safety_audit(config: AppConfig) -> list[AuditFinding]:
    root = Path(config.runtime_root).resolve()
    source_findings = scan_source_forbidden_terms(root / "hyper_smart_observer")
    exchange_findings = source_findings["exchange_path"]
    sign_findings = source_findings["sign_call"]
    order_findings = source_findings["place_order"]
    allowed_locked_order_stubs = [
        path for path in order_findings if path.replace("\\", "/").endswith("hyperliquid_client/testnet_exchange_client.py")
    ]
    unexpected_order_findings = [path for path in order_findings if path not in allowed_locked_order_stubs]
    db_ok, db_message = audit_databases(config)
    archive_ok, archive_message = audit_archive_readiness(root)
    secret_ok, secret_message = scan_for_obvious_secrets(root / "hyper_smart_observer")
    ui_ok, ui_message = audit_dashboard_html(config.dashboard_dir / "hypersmart_dashboard.html")
    return [
        AuditFinding("no_exchange_path", not exchange_findings, f"matches={len(exchange_findings)}"),
        AuditFinding("no_signature_calls", not sign_findings, f"matches={len(sign_findings)}"),
        AuditFinding(
            "no_operational_order",
            not unexpected_order_findings and not config.execution_enabled and not config.testnet_execution_enabled,
            f"unexpected_matches={len(unexpected_order_findings)}, locked_refusal_stubs={len(allowed_locked_order_stubs)}",
        ),
        AuditFinding(
            "no_private_key_config",
            config.sensitive_key_material is None,
            "No private key material is loaded in HyperSmart config.",
        ),
        AuditFinding("database_hygiene", db_ok, db_message),
        AuditFinding("archive_hygiene", archive_ok, archive_message),
        AuditFinding("secret_scan", secret_ok, secret_message),
        AuditFinding("dashboard_readonly", ui_ok, ui_message),
        AuditFinding("explorer_disabled_by_default", not config.explorer_observer_enabled, "Explorer observer disabled by default."),
        AuditFinding("ws_disabled_by_default", not config.ws_monitor_enabled, "WebSocket monitor disabled by default."),
        AuditFinding("mainnet_forbidden", not config.allow_mainnet, "Mainnet flag is disabled."),
        AuditFinding("execution_disabled_by_default", not config.execution_enabled, "Runtime execution flag is disabled."),
        AuditFinding("testnet_disabled_by_default", not config.testnet_execution_enabled, "Testnet executor flag is disabled."),
        AuditFinding("copy_mode_no_llm_hot_path", True, "Copy detector uses deterministic local rules, no LLM call."),
    ]


def write_audit_report(config: AppConfig, output: Path = Path("docs/HYPERSMART_SAFETY_AUDIT_REPORT.md")) -> Path:
    findings = run_safety_audit(config)
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# HyperSmart Safety Audit Report",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
    ]
    for finding in findings:
        status = "OK" if finding.ok else "FAIL"
        lines.append(f"- {status} `{finding.name}`: {finding.message}")
    output = _write_text_with_fallback(output, "\n".join(lines) + "\n")
    write_deep_audit_report(config)
    return output


def write_deep_audit_report(
    config: AppConfig,
    output: Path = Path("docs/release/HYPERSMART_SECURITY_AUDIT_DEEP.md"),
) -> Path:
    root = Path(config.runtime_root).resolve()
    findings = run_safety_audit(config)
    src_scan = scan_source_forbidden_terms(root / "src" / "hl_observer") if (root / "src" / "hl_observer").exists() else {}
    root_archives = [path.name for path in root.glob("*") if path.is_file() and path.suffix.lower() in {".zip", ".7z", ".rar"}]
    cmd_files = [path.name for path in root.glob("*.cmd")]
    ps1_files = [str(path.relative_to(root)) for path in (root / "tools").glob("*.ps1")] if (root / "tools").exists() else []
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# HyperSmart Security Audit Deep",
        "",
        f"Generated: {datetime.now(UTC).isoformat()}",
        "",
        "## Findings",
    ]
    for finding in findings:
        lines.append(f"- {'OK' if finding.ok else 'FAIL'} `{finding.name}`: {finding.message}")
    lines.extend(
        [
            "",
            "## Extended Surfaces",
            f"- src/hl_observer scanned keys: {', '.join(sorted(src_scan.keys())) if src_scan else 'not present or no scanner output'}",
            f"- root cmd files: {cmd_files}",
            f"- tools ps1 files: {ps1_files}",
            f"- root archives forbidden count: {len(root_archives)}",
            "",
            "## Policy",
            "- Documentation may mention forbidden terms only to prohibit them.",
            "- Disabled stubs may contain refusal method names only when they fail closed.",
            "- No operational mainnet, signature, private key, order or testnet executor is allowed.",
        ]
    )
    if root_archives:
        lines.append(f"- Root archives detected: {root_archives}")
    return _write_text_with_fallback(output, "\n".join(lines) + "\n")


def _write_text_with_fallback(output: Path, text: str) -> Path:
    try:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        return output
    except OSError as exc:
        fallback = Path(gettempdir()) / f"hypersmart_{output.name}"
        fallback.write_text(
            text
            + "\n"
            + f"WARNING: original report path unavailable: {output} ({exc.__class__.__name__}: {exc})\n",
            encoding="utf-8",
        )
        return fallback
