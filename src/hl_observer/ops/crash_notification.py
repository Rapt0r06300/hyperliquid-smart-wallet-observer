"""OPS-1 — Notification de crash/halt (Windows toast ou fichier signal).

Paper-only, lecture seule. Ne touche jamais un ordre réel.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path

logger = logging.getLogger(__name__)

SIGNAL_DIR = "runtime/data"
SIGNAL_FILE = "crash_signal.json"


def _project_root() -> Path:
    return Path(os.environ.get("ALINA_PROJECT_ROOT", ".")).resolve()


def write_crash_signal(
    reason: str,
    *,
    exit_code: int = 1,
    component: str = "moteur",
) -> Path:
    """Écrit un fichier signal JSON que le moniteur peut détecter."""
    sig_dir = _project_root() / SIGNAL_DIR
    sig_dir.mkdir(parents=True, exist_ok=True)
    sig_path = sig_dir / SIGNAL_FILE
    payload = {
        "event": "CRASH_OR_HALT",
        "reason": str(reason)[:500],
        "exit_code": int(exit_code),
        "component": str(component),
        "ts": time.time(),
        "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    try:
        sig_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.warning("CRASH_SIGNAL written: %s — %s", sig_path, reason)
    except OSError as exc:
        logger.error("Failed to write crash signal: %s", exc)
    return sig_path


def send_toast(title: str, message: str) -> bool:
    """Tente un toast Windows via PowerShell. Best-effort, jamais bloquant."""
    try:
        ps_script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
            "ContentType = WindowsRuntime] > $null; "
            "$template = [Windows.UI.Notifications.ToastNotificationManager]::"
            "GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
            "$text = $template.GetElementsByTagName('text'); "
            f"$text[0].AppendChild($template.CreateTextNode('{title}')) > $null; "
            f"$text[1].AppendChild($template.CreateTextNode('{message}')) > $null; "
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
            "[Windows.UI.Notifications.ToastNotificationManager]::"
            "CreateToastNotifier('HyperSmart').Show($toast)"
        )
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            timeout=5,
            capture_output=True,
        )
        return True
    except Exception:
        return False


def notify_crash(reason: str, *, exit_code: int = 1, component: str = "moteur") -> None:
    """Point d'entrée unifié : écrit le signal + tente le toast."""
    write_crash_signal(reason, exit_code=exit_code, component=component)
    send_toast("HyperSmart HALT", f"{component}: {reason[:100]}")


def check_crash_signal() -> dict | None:
    """Lit le signal de crash s'il existe. Pour le moniteur de santé."""
    sig_path = _project_root() / SIGNAL_DIR / SIGNAL_FILE
    if not sig_path.exists():
        return None
    try:
        data = json.loads(sig_path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def clear_crash_signal() -> None:
    """Efface le signal après traitement."""
    sig_path = _project_root() / SIGNAL_DIR / SIGNAL_FILE
    try:
        sig_path.unlink(missing_ok=True)
    except OSError:
        pass


__all__ = [
    "notify_crash",
    "write_crash_signal",
    "send_toast",
    "check_crash_signal",
    "clear_crash_signal",
]
