from __future__ import annotations

from hyper_smart_observer.data_sources.base_provider import DataProviderSpec, capability


def default_provider_specs() -> list[DataProviderSpec]:
    return [
        DataProviderSpec(
            provider_name="ManualImportProvider",
            capabilities=(
                capability("wallets_csv_json_txt", "Import local wallet lists and fixtures."),
                capability("fills_positions_exports", "Import already exported fills/positions."),
            ),
            requires_network=False,
            requires_api_key=False,
            enabled_by_default=True,
            rate_limit_policy="local files only",
            risk_level="low",
            output_contract="WalletUniverseEntry and normalized local rows",
        ),
        DataProviderSpec(
            provider_name="LocalCacheProvider",
            capabilities=(
                capability("wallet_index", "Read indexed local wallet activity."),
                capability("simulation_inputs", "Feed local simulation and benchmark without network."),
            ),
            requires_network=False,
            requires_api_key=False,
            enabled_by_default=True,
            rate_limit_policy="local filesystem/database only",
            risk_level="low",
            output_contract="IndexedWallet and local event rows",
        ),
        DataProviderSpec(
            provider_name="OfficialInfoProvider",
            capabilities=(
                capability("allMids", "Read current mids once per run."),
                capability("clearinghouseState", "Read user positions."),
                capability("userFillsByTime", "Read fills with bounded timestamp pagination."),
                capability("userFills", "Read recent fills."),
                capability("openOrders", "Read open orders as context only."),
                capability("frontendOpenOrders", "Read frontend open orders as context only."),
            ),
            requires_network=True,
            requires_api_key=False,
            enabled_by_default=False,
            rate_limit_policy="explicit --network-read, max leaders, timestamp cursors, stopped_reason",
            risk_level="medium",
            docs_url="https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint",
            output_contract="read-only snapshots/fills/open-order context",
        ),
        DataProviderSpec(
            provider_name="OfficialWsProvider",
            capabilities=(
                capability("trades", "Public trades for broad wallet discovery."),
                capability("userFills", "Shortlist-only user fills."),
                capability("allMids", "Live mid marks."),
                capability("bbo_l2Book", "Liquidity and spread context."),
            ),
            requires_network=True,
            requires_api_key=False,
            enabled_by_default=False,
            rate_limit_policy="duration bounded, max 10 user-specific users, read-only",
            risk_level="medium",
            docs_url="https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/websocket/subscriptions",
            output_contract="stream events with isSnapshot handling",
        ),
        DataProviderSpec(
            provider_name="HistoricalArchiveProvider",
            capabilities=(capability("historical_fixtures", "Read local historical archives for replay/backtest."),),
            requires_network=False,
            requires_api_key=False,
            enabled_by_default=True,
            rate_limit_policy="local archive files only",
            risk_level="low",
            output_contract="normalized historical rows",
        ),
    ]


def provider_registry_report() -> str:
    lines = [
        "provider_registry=research_only",
        "| Provider | Network | API key | Enabled default | Risk | Capabilities |",
        "|---|---:|---:|---:|---|---|",
    ]
    for provider in default_provider_specs():
        caps = ", ".join(cap.name for cap in provider.capabilities)
        lines.append(
            f"| {provider.provider_name} | {provider.requires_network} | {provider.requires_api_key} | "
            f"{provider.enabled_by_default} | {provider.risk_level} | {caps} |"
        )
    return "\n".join(lines)
