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

from hl_observer.ops.echec_silencieux import noter as _noter_echec

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
    # UNE SEULE LECTURE D'HORLOGE, ET EN UTC (corrige le 2026-11-21). `ts` et `ts_iso`
    # lisaient l'horloge deux fois -- une grandeur, deux valeurs -- et `strftime` sans
    # argument rend l'heure LOCALE sans fuseau. Un signal de crash sert a ordonner des
    # evenements apres coup : un instant naif rend deux crashs du changement d'heure
    # impossibles a classer.
    maintenant = time.time()
    payload = {
        "event": "CRASH_OR_HALT",
        "reason": str(reason)[:500],
        "exit_code": int(exit_code),
        "component": str(component),
        "ts": maintenant,
        "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(maintenant)),
    }
    try:
        sig_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        logger.warning("CRASH_SIGNAL written: %s — %s", sig_path, reason)
    except OSError as exc:
        logger.error("Failed to write crash signal: %s", exc)
    return sig_path


def send_toast(title: str, message: str) -> bool:
    """Tente un toast Windows via PowerShell. Best-effort, jamais bloquant.

    LE TEXTE N'ENTRE PLUS DANS LE SCRIPT (corrige le 2026-11-21). La version precedente
    interpolait `title` et `message` DANS le source PowerShell :

        f"$text[0].AppendChild($template.CreateTextNode('{title}')) > $null; "

    Une simple apostrophe dans une raison de crash cassait le script ; une raison contenant
    `'; <commande>; '` faisait EXECUTER cette commande. Et une raison de crash n'est pas une
    constante : elle vient d'une exception, donc d'une donnee. C'est une injection de commande,
    sans `shell=True` et donc invisible pour la regle qui le cherche.

    Les deux textes passent desormais par l'ENVIRONNEMENT : PowerShell lit `$env:...` comme
    une DONNEE, jamais comme du code. Il n'y a plus de chemin par lequel un message devient
    une instruction.
    """
    try:
        ps_script = (
            "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
            "ContentType = WindowsRuntime] > $null; "
            "$template = [Windows.UI.Notifications.ToastNotificationManager]::"
            "GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02); "
            "$text = $template.GetElementsByTagName('text'); "
            "$text[0].AppendChild($template.CreateTextNode($env:HYPERSMART_TOAST_TITRE)) > $null; "
            "$text[1].AppendChild($template.CreateTextNode($env:HYPERSMART_TOAST_MESSAGE)) > $null; "
            "$toast = [Windows.UI.Notifications.ToastNotification]::new($template); "
            "[Windows.UI.Notifications.ToastNotificationManager]::"
            "CreateToastNotifier('HyperSmart').Show($toast)"
        )
        environnement = dict(os.environ)
        environnement["HYPERSMART_TOAST_TITRE"] = str(title)[:200]
        environnement["HYPERSMART_TOAST_MESSAGE"] = str(message)[:400]
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", ps_script],
            timeout=5,
            capture_output=True,
            env=environnement,
        )
        return True
    except Exception as exc:                                           # noqa: BLE001
        # Best-effort VISIBLE : un toast qui n'arrive jamais sans laisser de trace, c'est la
        # notification de crash qu'on croit avoir et qu'on n'a pas.
        _noter_echec("ops/crash_notification.py:send_toast", exc)
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
    except OSError as exc:
        _noter_echec("ops/crash_notification.py:clear_crash_signal", exc)


__all__ = [
    "notify_crash",
    "write_crash_signal",
    "send_toast",
    "check_crash_signal",
    "clear_crash_signal",
]
