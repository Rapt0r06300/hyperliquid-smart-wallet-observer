from __future__ import annotations

from pathlib import Path


DANGEROUS_UI_WORDS = ("buy", "sell", "execute", "copy trade", "withdraw", "connect wallet")


def audit_dashboard_html(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return True, "Dashboard not exported yet."
    text = path.read_text(encoding="utf-8", errors="ignore").lower()
    dangerous = [word for word in DANGEROUS_UI_WORDS if f"<button" in text and word in text]
    if dangerous:
        return False, f"Dangerous dashboard button wording: {dangerous}"
    return True, "Dashboard contains no dangerous action buttons."
