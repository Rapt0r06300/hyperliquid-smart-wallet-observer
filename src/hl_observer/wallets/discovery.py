from __future__ import annotations

from pydantic import BaseModel


class WalletCandidate(BaseModel):
    address: str
    source: str
    reason: str
    confidence: float = 0.0
