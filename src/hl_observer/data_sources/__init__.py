"""Data provider contracts for read-only/local HyperSmart ingestion."""

from hl_observer.data_sources.acquisition_engine import (
    DataAcquisitionEngine,
    DataQualityAssessment,
    DataQualityConfig,
    DataQualityGate,
    DataQualityStatus,
    FetchRequest,
    FetchResult,
    PersistentFetchQueue,
    RequestBudgetManager,
)
from hl_observer.data_sources.historical_backfill_engine import (
    BackfillStopReason,
    HistoricalBackfillConfig,
    HistoricalBackfillEngine,
    HistoricalBackfillResult,
    TtlPageCache,
)
from hl_observer.data_sources.fresh_data_plan import (
    FreshDataPlan,
    FreshDataPlanRequest,
    build_fresh_data_plan,
    format_fresh_data_plan,
)
from hl_observer.data_sources.warehouse_coverage import (
    WarehouseCoverageReport,
    build_warehouse_coverage_report,
    format_warehouse_coverage_report,
)

__all__ = [
    "DataAcquisitionEngine",
    "DataQualityAssessment",
    "DataQualityConfig",
    "DataQualityGate",
    "DataQualityStatus",
    "FetchRequest",
    "FetchResult",
    "PersistentFetchQueue",
    "RequestBudgetManager",
    "BackfillStopReason",
    "HistoricalBackfillConfig",
    "HistoricalBackfillEngine",
    "HistoricalBackfillResult",
    "TtlPageCache",
    "FreshDataPlan",
    "FreshDataPlanRequest",
    "build_fresh_data_plan",
    "format_fresh_data_plan",
    "WarehouseCoverageReport",
    "build_warehouse_coverage_report",
    "format_warehouse_coverage_report",
]
