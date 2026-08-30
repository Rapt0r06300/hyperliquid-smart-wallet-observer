"""Family adapters for the canonical economic-assumption registry."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from hl_observer.config.frais_venues import hypothese_frais_taker
from hl_observer.economics.assumptions import (
    AssumptionClassification,
    EconomicAssumptionRegistry,
    EconomicRunMode,
    FormulaDefinition,
    make_assumption,
)


@dataclass(frozen=True, slots=True)
class FamilyEconomicContract:
    family: str
    registry: EconomicAssumptionRegistry
    required_ids: tuple[str, ...]
    direct_measured_fields: tuple[str, ...]
    reality_model_version: str

    def receipt(self) -> dict[str, Any]:
        certification = self.registry.certification_receipt(self.required_ids)
        return {
            "schema": "hypersmart.family_economic_contract.v1",
            "family": self.family,
            "reality_model_version": self.reality_model_version,
            "assumption_snapshot_hash": self.registry.snapshot_hash(),
            "certification": certification,
            "direct_measured_fields": list(self.direct_measured_fields),
            "numeric_provenance": {
                assumption_id: list(self.registry.provenance_chain(assumption_id))
                for assumption_id in self.required_ids
            },
            "values": {
                assumption_id: self.registry.get(assumption_id).value
                for assumption_id in self.required_ids
            },
        }


def _register_constant(
    registry: EconomicAssumptionRegistry,
    *,
    assumption_id: str,
    name: str,
    value: float,
    unit: str,
    family: str,
    source_ref: str,
    classification: AssumptionClassification = AssumptionClassification.ASSUMPTION,
) -> None:
    registry.register(
        make_assumption(
            assumption_id=assumption_id,
            name=name,
            value=float(value),
            unit=unit,
            family_scope=(family,),
            classification=classification,
            source_ref=source_ref,
            owner=f"HyperSmart/{family.lower()}",
            certification_eligible=True,
        )
    )


def _register_round_trip_fee(
    registry: EconomicAssumptionRegistry,
    *,
    family: str,
    output_id: str,
    fill_counts: Mapping[str, int],
    reality_model_version: str,
) -> None:
    parent_ids = tuple(sorted(fill_counts))
    counts = {key: int(value) for key, value in fill_counts.items()}
    if not counts or any(value <= 0 for value in counts.values()):
        raise ValueError("fill_counts doit contenir des nombres de fills positifs")

    def evaluate(values: Mapping[str, object]) -> float:
        return sum(float(values[parent]) * counts[parent] for parent in parent_ids)

    expression = " + ".join(f"{counts[parent]}*{parent}" for parent in parent_ids)
    registry.register_formula(
        FormulaDefinition(
            formula_id=f"{family.lower()}.round_trip_fee.v1",
            output_assumption_id=output_id,
            parent_ids=parent_ids,
            expression=expression,
            unit="bps_round_trip",
            version="v1",
            reality_model_version=reality_model_version,
        ),
        evaluate,
        name=f"Frais aller-retour {family}",
        family_scope=(family,),
    )


def build_cross_venue_contract(
    *,
    mode: EconomicRunMode | str = EconomicRunMode.EXPLORATORY,
    adverse_selection_reserve_bps: float = 12.0,
    notional_usd: float = 15.0,
    entry_latency_ms: float = 400.0,
    max_book_age_ms: float = 3_000.0,
) -> FamilyEconomicContract:
    family = "CROSS_VENUE"
    reality = "cross_venue_four_fill_executable_bbo.v1"
    registry = EconomicAssumptionRegistry()
    registry.register(hypothese_frais_taker("HYPERLIQUID", mode=mode))
    registry.register(hypothese_frais_taker("BINANCE", mode=mode))
    _register_constant(
        registry,
        assumption_id="cross_venue.adverse_selection_reserve_bps",
        name="Reserve de selection adverse",
        value=adverse_selection_reserve_bps,
        unit="bps",
        family=family,
        source_ref="project:backtesting/cross_venue_v4_train.py#adverse-selection-reserve",
    )
    _register_constant(
        registry,
        assumption_id="cross_venue.paper_notional_usd",
        name="Notionnel paper par cycle",
        value=notional_usd,
        unit="USD",
        family=family,
        source_ref="project:backtesting/cross_venue_v3_train.py#NOTIONAL_USD",
    )
    _register_constant(
        registry,
        assumption_id="cross_venue.entry_latency_ms",
        name="Delai causal avant entree",
        value=entry_latency_ms,
        unit="ms",
        family=family,
        source_ref="project:backtesting/cross_venue_v3_train.py#LATENCY_MS",
    )
    _register_constant(
        registry,
        assumption_id="cross_venue.max_book_age_ms",
        name="Age maximal du carnet de capacite",
        value=max_book_age_ms,
        unit="ms",
        family=family,
        source_ref="project:backtesting/cross_venue_v3_train.py#MAX_OBSERVATION_GAP_MS",
    )
    _register_round_trip_fee(
        registry,
        family=family,
        output_id="cross_venue.round_trip_fee_bps",
        fill_counts={
            "fee.taker.hyperliquid.bps": 2,
            "fee.taker.binance.bps": 2,
        },
        reality_model_version=reality,
    )
    registry.register_formula(
        FormulaDefinition(
            formula_id="cross_venue.minimum_entry_edge.v1",
            output_assumption_id="cross_venue.minimum_entry_edge_bps",
            parent_ids=(
                "cross_venue.round_trip_fee_bps",
                "cross_venue.adverse_selection_reserve_bps",
            ),
            expression="round_trip_fee_bps + adverse_selection_reserve_bps",
            unit="bps",
            version="v1",
            reality_model_version=reality,
        ),
        lambda values: float(values["cross_venue.round_trip_fee_bps"])
        + float(values["cross_venue.adverse_selection_reserve_bps"]),
        name="Edge executable minimal",
        family_scope=(family,),
    )
    required = (
        "fee.taker.hyperliquid.bps",
        "fee.taker.binance.bps",
        "cross_venue.round_trip_fee_bps",
        "cross_venue.adverse_selection_reserve_bps",
        "cross_venue.minimum_entry_edge_bps",
        "cross_venue.paper_notional_usd",
        "cross_venue.entry_latency_ms",
        "cross_venue.max_book_age_ms",
    )
    return FamilyEconomicContract(
        family=family,
        registry=registry,
        required_ids=required,
        direct_measured_fields=("entry_capacity_usd", "exit_capacity_usd", "bid", "ask"),
        reality_model_version=reality,
    )


def build_lead_lag_contract(
    *,
    mode: EconomicRunMode | str = EconomicRunMode.EXPLORATORY,
    notional_usd: float = 100.0,
    max_book_age_ms: float = 750.0,
    max_execution_observation_delay_ms: float = 750.0,
) -> FamilyEconomicContract:
    family = "LEAD_LAG"
    reality = "lead_lag_delayed_executable_bbo.v2"
    registry = EconomicAssumptionRegistry()
    registry.register(hypothese_frais_taker("HYPERLIQUID", mode=mode))
    _register_round_trip_fee(
        registry,
        family=family,
        output_id="lead_lag.round_trip_fee_bps",
        fill_counts={"fee.taker.hyperliquid.bps": 2},
        reality_model_version=reality,
    )
    for assumption_id, name, value, unit, source in (
        (
            "lead_lag.paper_notional_usd",
            "Notionnel paper",
            notional_usd,
            "USD",
            "project:simulation/lead_lag_measured_replay.py#notional_usd",
        ),
        (
            "lead_lag.max_book_age_ms",
            "Age maximal carnet",
            max_book_age_ms,
            "ms",
            "project:simulation/lead_lag_measured_replay.py#DEFAULT_MAX_BOOK_AGE_MS",
        ),
        (
            "lead_lag.max_execution_observation_delay_ms",
            "Delai maximal observation execution",
            max_execution_observation_delay_ms,
            "ms",
            (
                "project:simulation/lead_lag_measured_replay.py"
                "#DEFAULT_MAX_EXECUTION_OBSERVATION_DELAY_MS"
            ),
        ),
    ):
        _register_constant(
            registry,
            assumption_id=assumption_id,
            name=name,
            value=value,
            unit=unit,
            family=family,
            source_ref=source,
        )
    required = (
        "fee.taker.hyperliquid.bps",
        "lead_lag.round_trip_fee_bps",
        "lead_lag.paper_notional_usd",
        "lead_lag.max_book_age_ms",
        "lead_lag.max_execution_observation_delay_ms",
    )
    return FamilyEconomicContract(
        family=family,
        registry=registry,
        required_ids=required,
        direct_measured_fields=(
            "runtime_latency_p95_ms",
            "entry_capacity_usd",
            "exit_capacity_usd",
            "bid",
            "ask",
        ),
        reality_model_version=reality,
    )


def build_copy_vault_contract(
    *,
    mode: EconomicRunMode | str = EconomicRunMode.EXPLORATORY,
    notional_usd: float,
    copy_delay_ms: float,
    max_reference_lag_ms: float,
    max_target_lag_ms: float,
) -> FamilyEconomicContract:
    family = "COPY_VAULT"
    reality = "copy_vault_exact_checkpoint_executable_bbo.v2"
    registry = EconomicAssumptionRegistry()
    registry.register(hypothese_frais_taker("HYPERLIQUID", mode=mode))
    _register_round_trip_fee(
        registry,
        family=family,
        output_id="copy_vault.round_trip_fee_bps",
        fill_counts={"fee.taker.hyperliquid.bps": 2},
        reality_model_version=reality,
    )
    for assumption_id, name, value, unit, source in (
        (
            "copy_vault.paper_notional_usd",
            "Notionnel paper",
            notional_usd,
            "USD",
            "project:backtesting/copy_vault_protocol.py#NOTIONAL_USD",
        ),
        (
            "copy_vault.copy_delay_ms",
            "Delai de copie",
            copy_delay_ms,
            "ms",
            "project:backtesting/copy_vault_protocol.py#COPY_DELAY_MS",
        ),
        (
            "copy_vault.max_reference_lag_ms",
            "Age maximal reference",
            max_reference_lag_ms,
            "ms",
            "project:backtesting/copy_vault_protocol.py#MAX_REFERENCE_LAG_MS",
        ),
        (
            "copy_vault.max_target_lag_ms",
            "Age maximal cible",
            max_target_lag_ms,
            "ms",
            "project:backtesting/copy_vault_protocol.py#MAX_TARGET_LAG_MS",
        ),
    ):
        _register_constant(
            registry,
            assumption_id=assumption_id,
            name=name,
            value=value,
            unit=unit,
            family=family,
            source_ref=source,
        )
    required = (
        "fee.taker.hyperliquid.bps",
        "copy_vault.round_trip_fee_bps",
        "copy_vault.paper_notional_usd",
        "copy_vault.copy_delay_ms",
        "copy_vault.max_reference_lag_ms",
        "copy_vault.max_target_lag_ms",
    )
    return FamilyEconomicContract(
        family=family,
        registry=registry,
        required_ids=required,
        direct_measured_fields=(
            "entry_capacity_usd",
            "exit_capacity_usd",
            "reference_mid",
            "entry_bid",
            "entry_ask",
            "exit_bid",
            "exit_ask",
        ),
        reality_model_version=reality,
    )


__all__ = [
    "FamilyEconomicContract",
    "build_copy_vault_contract",
    "build_cross_venue_contract",
    "build_lead_lag_contract",
]
