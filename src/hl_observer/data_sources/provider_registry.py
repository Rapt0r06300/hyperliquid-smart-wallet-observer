from __future__ import annotations

from hl_observer.data_sources.base_provider import DataProviderSpec, capability


def default_provider_specs() -> list[DataProviderSpec]:
    return [
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
                capability("openOrders", "Read open orders as context only."),
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
            provider_name="OkxPublicCopyTradingProvider",
            capabilities=(
                capability("public_lead_ranks", "Read OKX public Copy Trading leader rankings."),
                capability("public_current_positions", "Observe selected leader positions."),
                capability("public_position_history", "Collect bounded public closed-position history."),
            ),
            requires_network=True,
            requires_api_key=False,
            enabled_by_default=False,
            rate_limit_policy="explicit --network-read, fixed ranking snapshot, bounded pages and 0.42s minimum request spacing",
            risk_level="medium",
            docs_url="https://www.okx.com/docs-v5/en/",
            output_contract="venue-scoped discovery and forward observations; never certified PnL without SAFE replay",
            notes=(
                "GET-only endpoints; no order/trade endpoint is allowed",
                "public history omits complete fees, funding, account cashflows and follower execution evidence",
                "OKX candidates cannot enter Hyperliquid backfill",
            ),
        ),
        DataProviderSpec(
            provider_name="ExplorerPublicProvider",
            capabilities=(capability("manual_import", "Import explorer-visible activity supplied by user."),),
            requires_network=True,
            requires_api_key=False,
            enabled_by_default=False,
            rate_limit_policy="disabled by default, no aggressive scraping",
            risk_level="high",
            output_contract="experimental ExplorerEvent rows",
            notes=("Do not bypass protections.", "Prefer manual exports or official /info/WS."),
        ),
        DataProviderSpec(
            provider_name="ThirdPartyProvider",
            capabilities=(capability("optional_exports", "Read manually configured provider exports."),),
            requires_network=True,
            requires_api_key=True,
            enabled_by_default=False,
            rate_limit_policy="disabled unless configured explicitly",
            risk_level="high",
            output_contract="provider-specific normalized imports",
            notes=("No API key is required for default HyperSmart operation.",),
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

