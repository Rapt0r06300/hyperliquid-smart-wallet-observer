from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from hl_observer.config.settings import Settings
from hl_observer.decision_engine.local_engine import LocalDecision, LocalDecisionEngine
from hl_observer.hyperliquid.schemas import SignalCandidate
from hl_observer.loops.memory import LoopMemoryStore, default_loop_memory_dir
from hl_observer.loops.models import (
    ExecutionFeedback,
    LearningSummary,
    LoopRunResult,
    ResearchThesis,
    stable_hash,
)
from hl_observer.mainnet_readonly_observer.observer import MainnetObservation, MainnetReadOnlyObserver
from hl_observer.testnet.safety import TESTNET_DISABLED_REASON


@dataclass(slots=True)
class LoopEngineeringRunner:
    settings: Settings
    observer: MainnetReadOnlyObserver | None = None
    decision_engine: LocalDecisionEngine | None = None
    memory: LoopMemoryStore | None = None

    def __post_init__(self) -> None:
        if self.decision_engine is None:
            self.decision_engine = LocalDecisionEngine(
                self.settings,
                feed_quality_path=Path("runtime") / "data" / "feed_quality.json",
            )
        if self.memory is None:
            self.memory = LoopMemoryStore(default_loop_memory_dir())

    def run_with_observation(
        self,
        *,
        observation: MainnetObservation,
        candidates: Iterable[SignalCandidate],
        execute_testnet: bool = False,
        confirmed: bool = False,
        notional_usdc: float = 1.0,
    ) -> LoopRunResult:
        if execute_testnet:
            raise RuntimeError(TESTNET_DISABLED_REASON)
        del confirmed
        thesis = ResearchThesis.from_observation(observation)
        assert self.memory is not None
        self.memory.record_thesis(thesis)

        decisions: list[LocalDecision] = []
        feedback: list[ExecutionFeedback] = []
        for index, candidate in enumerate(candidates):
            decision = self.decision_engine.decide_from_candidate(  # type: ignore[union-attr]
                candidate,
                notional_usdc=notional_usdc,
                cloid=f"loop-{candidate.coin.lower()}-{candidate.id}-{index}",
            )
            decisions.append(decision)
            item = ExecutionFeedback.from_decision(decision, status="PREPARED_ONLY")
            feedback.append(item)
            self.memory.record_feedback(item)

        learning = LearningSummary.from_feedback(feedback)
        self.memory.record_learning(learning)
        run_id = f"loop-{stable_hash({'thesis': thesis.to_dict(), 'decisions': [d.to_dict() for d in decisions]})}"
        result = LoopRunResult(
            run_id=run_id,
            thesis=thesis,
            decisions=[decision.to_dict() for decision in decisions],
            feedback=feedback,
            learning=learning,
            memory_dir=self.memory.root,
        )
        self.memory.write_result(result)
        return result

    async def run_once(
        self,
        *,
        coins: list[str] | None = None,
        wallets: list[str] | None = None,
        candidates: Iterable[SignalCandidate] = (),
        include_l2: bool = True,
        include_wallet_fills: bool = False,
        execute_testnet: bool = False,
        confirmed: bool = False,
        notional_usdc: float = 1.0,
    ) -> LoopRunResult:
        if execute_testnet:
            raise RuntimeError(TESTNET_DISABLED_REASON)
        del confirmed
        if self.observer is None:
            self.observer = MainnetReadOnlyObserver()
        observation = await self.observer.observe(
            coins=coins,
            wallets=wallets,
            include_l2=include_l2,
            include_wallet_fills=include_wallet_fills,
        )
        return self.run_with_observation(
            observation=observation,
            candidates=candidates,
            execute_testnet=False,
            confirmed=False,
            notional_usdc=notional_usdc,
        )

    def run_once_sync(self, **kwargs) -> LoopRunResult:
        return asyncio.run(self.run_once(**kwargs))


def load_signal_candidates(path: Path) -> list[SignalCandidate]:
    import json

    raw = json.loads(path.read_text(encoding="utf-8-sig"))
    if isinstance(raw, dict) and "candidates" in raw:
        raw = raw["candidates"]
    if not isinstance(raw, list):
        raise ValueError("candidate JSON must be a list or {'candidates': [...]}")
    return [SignalCandidate.model_validate(item) for item in raw]
