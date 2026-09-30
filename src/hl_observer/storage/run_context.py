from __future__ import annotations

from dataclasses import dataclass

try:
    from enum import StrEnum
except ImportError:
    from enum import Enum

    class StrEnum(str, Enum):
        pass

from hl_observer.utils.time import now_ms


class RunContext(StrEnum):
    LIVE = "LIVE"
    BACKTEST = "BACKTEST"
    REPLAY = "REPLAY"
    TEST_FIXTURE = "TEST_FIXTURE"


@dataclass(frozen=True, slots=True)
class RunContextScope:
    context: RunContext
    run_id: str
    paper_session_id: str
    started_at_ms: int

    @property
    def pnl_namespace(self) -> str:
        return f"{self.context.value}:{self.paper_session_id}"


def build_run_context_scope(
    context: RunContext | str,
    *,
    run_id: str,
    paper_session_id: str | None = None,
    started_at_ms: int | None = None,
) -> RunContextScope:
    resolved = context if isinstance(context, RunContext) else RunContext(str(context).upper())
    clean_run_id = str(run_id or "").strip()
    if not clean_run_id:
        raise ValueError("run_id is required to isolate paper PnL")
    clean_session = str(paper_session_id or clean_run_id).strip()
    if not clean_session:
        raise ValueError("paper_session_id is required to isolate paper PnL")
    return RunContextScope(
        context=resolved,
        run_id=clean_run_id,
        paper_session_id=clean_session,
        started_at_ms=now_ms() if started_at_ms is None else max(0, int(started_at_ms)),
    )


def assert_same_run_context(left: RunContextScope, right: RunContextScope) -> None:
    if left.context != right.context:
        raise ValueError(
            f"run context mismatch: {left.context.value} cannot mix with {right.context.value}"
        )
    if left.paper_session_id != right.paper_session_id:
        raise ValueError(
            f"paper session mismatch: {left.paper_session_id} cannot mix with {right.paper_session_id}"
        )


def may_merge_pnl(left: RunContextScope, right: RunContextScope) -> bool:
    try:
        assert_same_run_context(left, right)
    except ValueError:
        return False
    return True
