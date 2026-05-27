from __future__ import annotations

from pydantic import BaseModel, Field


class FollowState(BaseModel):
    active_signals: dict[str, str] = Field(default_factory=dict)
    mode: str = "OBSERVE_ONLY"
