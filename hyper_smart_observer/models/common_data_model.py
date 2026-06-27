from __future__ import annotations

from dataclasses import dataclass


CDM_REQUIRED_OBJECTS: tuple[str, ...] = (
    "NormalizedFill",
    "NormalizedPosition",
    "NormalizedOpenOrder",
    "MarketMid",
    "OrderBookSnapshot",
    "MarketSignalFeatures",
    "WalletSnapshot",
    "CollectionRun",
    "SourceHealth",
    "LeaderDelta",
    "SignalCandidate",
    "RiskDecision",
    "NoTradeDecision",
    "PaperIntent",
    "PaperTrade",
    "DecisionLedgerEntry",
    "DashboardEvent",
)

REQUIRED_METADATA_GROUPS: tuple[tuple[str, ...], ...] = (
    ("venue",),
    ("source_endpoint", "source_channel"),
    ("source_ts",),
    ("local_received_ts",),
    ("latency_ms",),
    ("raw_ref", "raw_hash"),
    ("data_quality",),
    ("is_stale",),
    ("schema_version",),
    ("adapter_version",),
)

_REST_METADATA = (
    "venue",
    "source_endpoint",
    "source_ts",
    "local_received_ts",
    "latency_ms",
    "raw_hash",
    "data_quality",
    "is_stale",
    "schema_version",
    "adapter_version",
)

_WS_METADATA = (
    "venue",
    "source_channel",
    "source_ts",
    "local_received_ts",
    "latency_ms",
    "raw_hash",
    "data_quality",
    "is_stale",
    "schema_version",
    "adapter_version",
)

_LOCAL_METADATA = (
    "venue",
    "source_endpoint",
    "source_ts",
    "local_received_ts",
    "latency_ms",
    "raw_ref",
    "data_quality",
    "is_stale",
    "schema_version",
    "adapter_version",
)


@dataclass(frozen=True)
class CDMObjectContract:
    name: str
    implemented_by: str
    metadata_fields: tuple[str, ...]
    status: str
    notes: str = ""

    def missing_metadata_requirements(self) -> tuple[str, ...]:
        missing: list[str] = []
        fields = set(self.metadata_fields)
        for alternatives in REQUIRED_METADATA_GROUPS:
            if not any(field in fields for field in alternatives):
                missing.append("|".join(alternatives))
        return tuple(missing)


@dataclass(frozen=True)
class CDMAuditReport:
    contracts: tuple[CDMObjectContract, ...]
    required_objects: tuple[str, ...] = CDM_REQUIRED_OBJECTS

    @property
    def missing_objects(self) -> tuple[str, ...]:
        known = {contract.name for contract in self.contracts}
        return tuple(name for name in self.required_objects if name not in known)

    @property
    def incomplete_objects(self) -> dict[str, tuple[str, ...]]:
        return {
            contract.name: missing
            for contract in self.contracts
            if (missing := contract.missing_metadata_requirements())
        }

    @property
    def is_complete(self) -> bool:
        return not self.missing_objects and not self.incomplete_objects


def build_cdm_contracts() -> tuple[CDMObjectContract, ...]:
    return (
        CDMObjectContract(
            "NormalizedFill",
            "hyper_smart_observer.hyperliquid_client.normalization.normalize_user_fill -> Fill",
            _REST_METADATA,
            "IMPLEMENTED",
            "REST userFills/userFillsByTime fill role with raw payload hash/ref provenance.",
        ),
        CDMObjectContract(
            "NormalizedPosition",
            "hyper_smart_observer.hyperliquid_client.normalization.normalize_position_snapshot -> PositionSnapshot",
            _REST_METADATA,
            "IMPLEMENTED",
            "REST clearinghouseState position snapshot role.",
        ),
        CDMObjectContract(
            "NormalizedOpenOrder",
            "hyper_smart_observer.copy_mode.snapshot_engine._insert_open_order_snapshots",
            _REST_METADATA,
            "CONTRACTED",
            "Open orders are context-only evidence and never create paper intent alone.",
        ),
        CDMObjectContract(
            "MarketMid",
            "hyper_smart_observer.market_signals.mid_stability.MarketMid",
            _REST_METADATA,
            "IMPLEMENTED",
            "Mid source encodes book, fallback trade or missing state.",
        ),
        CDMObjectContract(
            "OrderBookSnapshot",
            "hyper_smart_observer.market_signals.orderbook_features.OrderBookFeatures",
            _REST_METADATA,
            "IMPLEMENTED",
            "L2 book features are pure derived metadata for scan_features export.",
        ),
        CDMObjectContract(
            "MarketSignalFeatures",
            "hyper_smart_observer.market_signals.market_signal_features.MarketSignalFeatures",
            _REST_METADATA,
            "IMPLEMENTED",
            "Runtime/export row contract for edge, liquidity and source health.",
        ),
        CDMObjectContract(
            "WalletSnapshot",
            "hyper_smart_observer.copy_mode.snapshot_engine.LeaderSnapshot",
            _REST_METADATA,
            "IMPLEMENTED",
            "Leader wallet REST snapshot with fills, positions and contextual open orders.",
        ),
        CDMObjectContract(
            "CollectionRun",
            "hyper_smart_observer.copy_mode.snapshot_engine.CollectionRun",
            _LOCAL_METADATA,
            "IMPLEMENTED",
            "Local bounded collection run envelope.",
        ),
        CDMObjectContract(
            "SourceHealth",
            "hyper_smart_observer.copy_mode.snapshot_engine._write_source_health",
            _LOCAL_METADATA,
            "IMPLEMENTED",
            "Local source-health row used by dashboard and preflight.",
        ),
        CDMObjectContract(
            "LeaderDelta",
            "hyper_smart_observer.copy_mode.copy_models.LeaderDelta",
            _WS_METADATA,
            "IMPLEMENTED",
            "Leader position/fill delta role from WS or REST reconciliation.",
        ),
        CDMObjectContract(
            "SignalCandidate",
            "hyper_smart_observer.copy_mode.copy_models.SignalCandidate",
            _WS_METADATA,
            "IMPLEMENTED",
            "Paper-only copy candidate after evidence and edge calculation.",
        ),
        CDMObjectContract(
            "RiskDecision",
            "hyper_smart_observer.risk_engine.risk_state.RiskDecision",
            _LOCAL_METADATA,
            "IMPLEMENTED",
            "Deny-by-default risk gate result.",
        ),
        CDMObjectContract(
            "NoTradeDecision",
            "hyper_smart_observer.copy_mode.copy_models.NoTradeDecision",
            _LOCAL_METADATA,
            "IMPLEMENTED",
            "Structured no-trade ledger row with missing-data explanation.",
        ),
        CDMObjectContract(
            "PaperIntent",
            "hyper_smart_observer.hyperliquid_client.models.PaperIntent",
            _LOCAL_METADATA,
            "IMPLEMENTED",
            "Mock-USDC-only simulation intent.",
        ),
        CDMObjectContract(
            "PaperTrade",
            "hyper_smart_observer.hyperliquid_client.models.PaperTrade",
            _LOCAL_METADATA,
            "IMPLEMENTED",
            "Simulated paper trade record only.",
        ),
        CDMObjectContract(
            "DecisionLedgerEntry",
            "hyper_smart_observer.copy_mode.repository.record_signal_decision",
            _LOCAL_METADATA,
            "CONTRACTED",
            "Append-only decision ledger projection for candidates and no-trade rows.",
        ),
        CDMObjectContract(
            "DashboardEvent",
            "hyper_smart_observer.dashboard.exporter.export_dashboard",
            _LOCAL_METADATA,
            "CONTRACTED",
            "Read-only dashboard projection; empty state is preferred to fake rows.",
        ),
    )


def audit_common_data_model_contracts() -> CDMAuditReport:
    return CDMAuditReport(contracts=build_cdm_contracts())
