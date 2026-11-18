from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from hl_observer.backtesting.copy_vault_protocol import PAPER_EQUITY_USD
from hl_observer.runtime_mode import RuntimeModeDecision, assert_simulation_only, decide_runtime_mode


@dataclass(frozen=True, slots=True)
class CoreConfig:
    project_root: Path = Path(".")
    runtime_dir: Path = Path("runtime")
    data_dir: Path = Path("runtime/data")
    logs_dir: Path = Path("logs")
    #: Le capital paper DU CONTRAT, importe et non recopie. Il valait 350.0 en dur ; le
    #: contrat est passe a 100 USD le 18/11/2026, et un ledger partant d'un autre montant
    #: produirait des PnL, drawdowns et ratios calcules sur un capital qui n'existe pas --
    #: sans que rien ne le signale, chaque module restant coherent avec lui-meme.
    default_starting_balance_usdc: float = PAPER_EQUITY_USD
    runtime_mode: RuntimeModeDecision = field(default_factory=decide_runtime_mode)
    max_retry_attempts: int = 3
    retry_base_delay_seconds: float = 0.25
    circuit_failure_threshold: int = 3
    circuit_recovery_timeout_seconds: float = 30.0

    def validate(self) -> None:
        assert_simulation_only(self.runtime_mode)
        if self.default_starting_balance_usdc <= 0:
            raise ValueError("default_starting_balance_usdc must be positive")


def default_core_config(project_root: str | Path = ".") -> CoreConfig:
    root = Path(project_root).resolve()
    cfg = CoreConfig(
        project_root=root,
        runtime_dir=root / "runtime",
        data_dir=root / "runtime" / "data",
        logs_dir=root / "logs",
    )
    cfg.validate()
    return cfg


__all__ = ["CoreConfig", "default_core_config"]
