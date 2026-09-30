"""Qualité & opérations — cœurs PURS, testés. Exécution du backlog :
prometheus_metrics_text (IDEA-40, format d'exposition des métriques), ProxyRotator (IDEA-34,
rotation d'IP anti-ban), ModelRegistry (IDEA-72, versionnage de modèles), nonregression_check
(IDEA-77), autodoc_functions (IDEA-80, doc auto depuis les docstrings). Aucun ordre.
"""
from __future__ import annotations

import inspect
import json
import os


def prometheus_metrics_text(metrics: dict, *, prefix: str = "hypersmart") -> str:
    """Sérialise des métriques au format d'exposition Prometheus (le serveur reste à brancher)."""
    lines = []
    for k, v in sorted(metrics.items()):
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            name = f"{prefix}_{k}".replace(" ", "_").replace("-", "_")
            lines.append(f"# TYPE {name} gauge")
            lines.append(f"{name} {v}")
    return "\n".join(lines) + "\n"


class ProxyRotator:
    """Rotation d'IP/proxies en round-robin, avec mise à l'écart des proxies défaillants."""

    def __init__(self, proxies):
        self.proxies = list(proxies)
        self.i = 0
        self.failed = set()

    def next(self):
        healthy = [p for p in self.proxies if p not in self.failed]
        if not healthy:
            self.failed.clear()                 # tous KO -> on retente tout
            healthy = list(self.proxies)
        if not healthy:
            return None
        p = healthy[self.i % len(healthy)]
        self.i += 1
        return p

    def mark_failed(self, proxy) -> None:
        self.failed.add(proxy)


class ModelRegistry:
    """Registre de modèles versionnés (on sait toujours quel modèle a produit quel résultat)."""

    def __init__(self, base: str):
        self.base = base

    def save(self, name: str, version: int, model, metadata: dict | None = None) -> str:
        os.makedirs(self.base, exist_ok=True)
        p = os.path.join(self.base, f"{name}.v{int(version)}.json")
        with open(p, "w", encoding="utf-8") as f:
            json.dump({"model": model, "metadata": metadata or {}}, f, default=str)
        return p

    def load(self, name: str, version: int):
        p = os.path.join(self.base, f"{name}.v{int(version)}.json")
        try:
            with open(p, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None


def nonregression_check(baseline: dict, current: dict, *, tolerance: float = 0.05) -> list:
    """Détecte les RÉGRESSIONS : une métrique qui se dégrade au-delà de la tolérance."""
    regs = []
    for k, base in baseline.items():
        if k not in current:
            regs.append({"metric": k, "issue": "MISSING"})
            continue
        cur = current[k]
        if isinstance(base, (int, float)) and isinstance(cur, (int, float)):
            if base > 0 and (base - cur) / abs(base) > tolerance:
                regs.append({"metric": k, "issue": "REGRESSION", "baseline": base, "current": cur})
    return regs


def autodoc_functions(module) -> str:
    """Génère un markdown depuis les docstrings d'un module (documentation auto)."""
    lines = [f"# {module.__name__}", "", (module.__doc__ or "").strip(), ""]
    for name, obj in sorted(vars(module).items()):
        if name.startswith("_"):
            continue
        if inspect.isfunction(obj) or inspect.isclass(obj):
            doc = (obj.__doc__ or "").strip().split("\n")[0]
            lines.append(f"- **{name}** — {doc}")
    return "\n".join(lines) + "\n"
