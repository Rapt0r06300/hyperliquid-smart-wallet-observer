from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class DataProviderSpec:
    provider_name: str
    capabilities: tuple[ProviderCapability, ...]
    requires_network: bool
    requires_api_key: bool
    enabled_by_default: bool
    rate_limit_policy: str
    risk_level: str
    docs_url: str | None = None
    output_contract: str = "normalized local events"
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def safe_by_default(self) -> bool:
        return not self.requires_api_key and (not self.requires_network or not self.enabled_by_default)


def capability(name: str, description: str) -> ProviderCapability:
    return ProviderCapability(name=name, description=description)

