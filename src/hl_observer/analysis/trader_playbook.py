from __future__ import annotations

from pydantic import BaseModel, Field

from hl_observer.analysis.methodology_profiler import MethodologyProfile


class TraderPlaybook(BaseModel):
    wallet_address: str
    coin: str | None = None
    playbook_type: str = "OBSERVE_ONLY"
    rule_summary: str
    opening_rules: list[str] = Field(default_factory=list)
    closing_rules: list[str] = Field(default_factory=list)
    risk_rules: list[str] = Field(default_factory=list)
    copy_rules: list[str] = Field(default_factory=list)
    rejected_rules: list[str] = Field(default_factory=list)
    confidence_score: float = 0.0
    status: str = "OBSERVE_ONLY"


def generate_trader_playbook(profile: MethodologyProfile) -> TraderPlaybook:
    return TraderPlaybook(
        wallet_address=profile.wallet_address,
        rule_summary=profile.methodology_summary,
        opening_rules=[f"Observer uniquement les ouvertures avec echantillon suffisant ({item})." for item in profile.best_opening_types],
        closing_rules=["Ne pas suivre les reductions/fermetures comme des ouvertures."],
        risk_rules=["Bloquer si spread, slippage, age du signal ou liquidite echouent."],
        copy_rules=["Paper uniquement tant que le filtre de risque n'autorise pas."],
        rejected_rules=["Ignorer les patterns avec trop peu d'echantillons ou expectancy negative."],
        confidence_score=profile.confidence_score,
        status="OBSERVE_ONLY" if profile.confidence_score < 0.75 else "PAPER_READY",
    )
