"""OPS-1 — Alertes opérateur: ne jamais découvrir un problème par hasard.

Détecte depuis l'état runtime: kill-switch/halt, source de données morte, drawdown
proche du seuil, disque presque plein, redémarrage. Pur: produit une liste
d'alertes avec sévérité. L'écriture (fichier/notification desktop) se fait ailleurs.
"""

from __future__ import annotations

INFO, WARN, CRITICAL = "INFO", "WARN", "CRITICAL"


def evaluate_alerts(
    status: dict,
    *,
    now_ms: int,
    max_source_silence_ms: int = 60_000,
    drawdown_warn_usd: float = 8.0,
    drawdown_crit_usd: float = 20.0,
    disk_free_warn_pct: float = 10.0,
    prev_boot_id: str | None = None,
) -> list[dict]:
    """Retourne les alertes actives, triées par sévérité (CRITICAL d'abord)."""

    alerts: list[dict] = []
    s = status if isinstance(status, dict) else {}

    halt = s.get("halt_state") or (s.get("graded_halt") or {}).get("state")
    if str(halt or "").upper() == "RED":
        alerts.append({"severity": CRITICAL, "code": "HALT_RED", "msg": "arrêt de risque niveau RED actif"})
    elif str(halt or "").upper() == "AMBER":
        alerts.append({"severity": WARN, "code": "HALT_AMBER", "msg": "risque AMBER: taille réduite"})
    if (s.get("kill_switch") or {}).get("active") is True:
        alerts.append({"severity": CRITICAL, "code": "KILL_SWITCH", "msg": "kill-switch actif — trading bloqué"})

    last_data_ms = int(s.get("last_data_update_ms") or 0)
    if last_data_ms > 0 and (int(now_ms) - last_data_ms) > max_source_silence_ms:
        alerts.append({"severity": CRITICAL, "code": "SOURCE_DEAD",
                       "msg": f"source silencieuse depuis {(now_ms - last_data_ms)//1000}s"})

    dd = abs(float(s.get("session_drawdown_usd") or 0.0))
    if dd >= drawdown_crit_usd:
        alerts.append({"severity": CRITICAL, "code": "DRAWDOWN_CRIT", "msg": f"drawdown {dd:.2f} USD ≥ seuil critique"})
    elif dd >= drawdown_warn_usd:
        alerts.append({"severity": WARN, "code": "DRAWDOWN_WARN", "msg": f"drawdown {dd:.2f} USD approche le seuil"})

    disk = float(s.get("disk_free_pct") or 100.0)
    if disk <= disk_free_warn_pct:
        alerts.append({"severity": WARN, "code": "DISK_LOW", "msg": f"disque libre {disk:.0f}%"})

    boot = s.get("boot_id")
    if prev_boot_id is not None and boot is not None and str(boot) != str(prev_boot_id):
        alerts.append({"severity": INFO, "code": "SERVER_RESTARTED", "msg": "le serveur a redémarré"})

    rank = {CRITICAL: 0, WARN: 1, INFO: 2}
    alerts.sort(key=lambda a: rank[a["severity"]])
    return alerts


def alerts_summary(alerts: list[dict]) -> dict:
    return {
        "count": len(alerts),
        "critical": sum(1 for a in alerts if a["severity"] == CRITICAL),
        "warn": sum(1 for a in alerts if a["severity"] == WARN),
        "worst": alerts[0]["severity"] if alerts else "NONE",
    }


__all__ = ["INFO", "WARN", "CRITICAL", "evaluate_alerts", "alerts_summary"]
