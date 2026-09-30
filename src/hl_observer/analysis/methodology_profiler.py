from __future__ import annotations

from pydantic import BaseModel, Field

from hl_observer.analysis.wallet_style import WalletStyle, infer_wallet_style


class MethodologyProfile(BaseModel):
    wallet_address: str
    primary_style: WalletStyle = WalletStyle.UNKNOWN
    best_coins: list[str] = Field(default_factory=list)
    best_opening_types: list[str] = Field(default_factory=list)
    copyability_score: float = 0.0
    risk_score: float = 0.0
    methodology_summary: str
    confidence_score: float = 0.0


def build_methodology_profile(
    *,
    wallet_address: str,
    coins: list[str],
    opening_types: list[str],
    copyability_score: float = 0.0,
) -> MethodologyProfile:
    style = infer_wallet_style(coins=coins, openings=opening_types)
    summary = (
        f"Wallet {wallet_address} observe sur {len(set(coins))} marches. "
        f"Style estime: {style.value}. Les regles restent en observation tant que l'echantillon est insuffisant."
    )
    return MethodologyProfile(
        wallet_address=wallet_address,
        primary_style=style,
        best_coins=sorted(set(coins))[:10],
        best_opening_types=sorted(set(opening_types))[:10],
        copyability_score=copyability_score,
        risk_score=max(0.0, 100.0 - copyability_score),
        methodology_summary=summary,
        confidence_score=0.5 if coins or opening_types else 0.1,
    )
