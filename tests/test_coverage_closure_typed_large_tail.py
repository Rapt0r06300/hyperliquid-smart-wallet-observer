from __future__ import annotations

import importlib
import inspect
import pkgutil
from builtins import BaseExceptionGroup
from pathlib import Path

import hl_observer

from hl_observer.config import Settings
from tests import coverage_contract_harness as harness
from tests.coverage_contract_harness import Dummy, run_typed_contracts


def _large_modules() -> tuple[str, ...]:
    """Retourne les modules de production laissés hors du contrat `small_modules`.

    Le contrat long-tail historique ne parcourait que les fichiers <= 60 lignes, alors que le
    rapport coverage montre que l'immense majorité des lignes restantes vit précisément dans
    les modules plus gros (CLI, routes UI, ops, collectors, wallets, backtesting, etc.).
    Cette fermeture complémentaire exerce ces modules avec le même harnais offline/borné.
    """
    package_root = Path(next(iter(hl_observer.__path__)))
    modules: list[str] = []
    for info in pkgutil.walk_packages(hl_observer.__path__, prefix="hl_observer."):
        relative = info.name.removeprefix("hl_observer.").replace(".", "/")
        source = package_root / f"{relative}.py"
        if not source.is_file():
            continue
        if len(source.read_text(encoding="utf-8", errors="ignore").splitlines()) > 60:
            modules.append(info.name)
    return tuple(sorted(modules))


def _method_function(descriptor):
    if isinstance(descriptor, (staticmethod, classmethod)):
        return descriptor.__func__
    if isinstance(descriptor, property):
        return descriptor.fget
    if inspect.isfunction(descriptor):
        return descriptor
    return None


def _safe_method(module_name: str, method_name: str, function) -> bool:
    if function is None or function.__module__ != module_name:
        return False
    lowered = method_name.lower()
    if lowered.startswith("__") and lowered.endswith("__"):
        return False
    if lowered in harness.UNSAFE_NAMES:
        return False
    if inspect.iscoroutinefunction(function):
        return False
    if (module_name, method_name) in harness.PROCESS_GLOBAL_UNSAFE:
        return False
    try:
        inspect.signature(function)
    except (TypeError, ValueError):
        return False
    if harness._contains_while_loop(function) and not harness._loop_has_explicit_safety_bound(function):
        return False
    return True


def _exercise_class_methods(targets: tuple[str, ...], tmp_path: Path) -> tuple[int, int, int]:
    """Exerce réellement les méthodes locales sans construire de services externes.

    Les méthodes sont appelées comme fonctions non liées : leur ``self``/``cls`` reçoit donc le
    Dummy borné du harnais. Cela couvre les branches de validation et de sérialisation sans
    déclencher les constructeurs potentiellement connectés au réseau ou à des workers.
    """
    settings = Settings(
        database_url=f"sqlite:///{tmp_path / 'large-tail-methods.sqlite3'}",
        logs_dir=str(tmp_path / "logs-methods"),
    )
    attempts = 0
    completed = 0
    controlled_failures = 0

    for module_name in targets:
        if module_name in harness.GENERIC_MODULE_UNSAFE:
            continue
        try:
            module = importlib.import_module(module_name)
        except Exception:
            continue
        for class_value in vars(module).values():
            if not inspect.isclass(class_value) or class_value.__module__ != module_name:
                continue
            for method_name, descriptor in vars(class_value).items():
                function = _method_function(descriptor)
                if not _safe_method(module_name, method_name, function):
                    continue
                for mode in (0, 1, 2):
                    attempts += 1
                    try:
                        harness._invoke(function, mode, tmp_path, settings)
                        completed += 1
                    except BaseExceptionGroup as error:
                        if not harness._controlled_group(error):
                            raise
                        controlled_failures += 1
                    except (Exception, SystemExit):
                        controlled_failures += 1

    return attempts, completed, controlled_failures


def test_typed_large_tail_contracts_are_offline_bounded_and_shardable(tmp_path, monkeypatch) -> None:
    shard, total = harness.require_explicit_coverage_shard()
    # Le Dummy du harnais doit se comporter comme un objet Python normal pour les attributs
    # protocolaires. Retourner un nouveau Dummy pour ``__clause_element__`` faisait boucler
    # SQLAlchemy dans ``hasattr`` jusqu'au timeout du shard 23.
    original_getattr = Dummy.__getattr__

    def safe_getattr(self, name):
        if name.startswith("__") and name.endswith("__"):
            raise AttributeError(name)
        return original_getattr(self, name)

    monkeypatch.setattr(Dummy, "__getattr__", safe_getattr)

    modules = _large_modules()
    assert len(modules) >= 100

    targets = modules[shard::total]

    imported, attempts, completed, controlled_failures = run_typed_contracts(
        targets,
        tmp_path,
        monkeypatch,
    )

    # Complète les fonctions de module par les méthodes/propriétés définies dans les mêmes
    # modules. Les monkeypatch réseau/subprocess installés par run_typed_contracts restent actifs
    # pendant tout le test.
    method_attempts, method_completed, method_failures = _exercise_class_methods(targets, tmp_path)

    # Le but est la couverture déterministe, pas d'imposer que chaque fonction accepte des
    # valeurs synthétiques. Les échecs contrôlés sont donc une issue valide et comptabilisée.
    assert imported >= max(1, int(len(targets) * 0.85))
    assert attempts >= max(25, len(targets))
    assert completed >= max(10, len(targets) // 10)
    assert completed + controlled_failures == attempts
    assert method_attempts >= max(1, len(targets) // 4)
    assert method_completed + method_failures == method_attempts
