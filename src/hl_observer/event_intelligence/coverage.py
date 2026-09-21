"""Machine-readable coverage registry for the 120 retained Event Intelligence ideas.

The registry is intentionally strict: every retained idea has an explicit owner
component and implementation status so future work cannot silently drop items.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IdeaCoverage:
    idea_id: int
    title: str
    component: str
    status: str
    note: str = ""


def _rows() -> tuple[IdeaCoverage, ...]:
    raw = [
        (1,"Event Intelligence / Global Regime Detector","event_intelligence","IMPLEMENTED"),
        (2,"ExternalEvent contract","external_event.py","IMPLEMENTED"),
        (3,"Ingest time as causal truth","external_event.py","IMPLEMENTED"),
        (4,"Archive events in Data Vault compatible path","archive.py","IMPLEMENTED"),
        (5,"Structured R1/R2 facts retention","archive.py","IMPLEMENTED"),
        (6,"World Monitor REST meta-source","worldmonitor.py","IMPLEMENTED"),
        (7,"Direct primary-source collection","direct_sources.py","IMPLEMENTED"),
        (8,"No dashboard scraping as primary source","worldmonitor.py","IMPLEMENTED"),
        (9,"News Leads Markets","candidates.py","IMPLEMENTED"),
        (10,"Prediction Leading","worldmonitor.py+candidates.py","IMPLEMENTED"),
        (11,"Polymarket read-only only","worldmonitor.py","IMPLEMENTED"),
        (12,"Silent Divergence classification","regimes.py","IMPLEMENTED"),
        (13,"Event regime taxonomy","regimes.py","IMPLEMENTED"),
        (14,"Velocity Spike","features.py","IMPLEMENTED"),
        (15,"Keyword/topic spike framework","features.py","IMPLEMENTED","Raw topic-specific counts plug into causal windows."),
        (16,"Cross-source convergence","worldmonitor.py","IMPLEMENTED"),
        (17,"Triangulation / multi-source corroboration","worldmonitor.py+features.py","IMPLEMENTED"),
        (18,"Corroboration latency","sequences.py+validation.py","IMPLEMENTED"),
        (19,"Fast OSINT/Telegram through WM","worldmonitor.py","IMPLEMENTED"),
        (20,"Dynamic source inventory","source_catalog.py","IMPLEMENTED"),
        (21,"Independent provenance tier","source_catalog.py","IMPLEMENTED"),
        (22,"Source diversity score","features.py","IMPLEMENTED"),
        (23,"Strong event deduplication","external_event.py+archive.py","IMPLEMENTED"),
        (24,"Revisions and corrections retained","external_event.py+archive.py","IMPLEMENTED"),
        (25,"Methodology versioning","external_event.py+protocol.py","IMPLEMENTED"),
        (26,"WM composite scores not direct BUY/SELL","module_bridges.py","IMPLEMENTED"),
        (27,"WM AI forecasts only contextual","module_bridges.py","IMPLEMENTED"),
        (28,"Military/geopolitical events","worldmonitor.py+regimes.py","IMPLEMENTED"),
        (29,"GPS jamming/spoofing","worldmonitor.py","IMPLEMENTED"),
        (30,"Aviation/NOTAM contextual events","source_catalog.py","IMPLEMENTED"),
        (31,"Maritime/AIS/chokepoints","source_catalog.py+module_bridges.py","IMPLEMENTED"),
        (32,"Supply-chain features","regimes.py","IMPLEMENTED"),
        (33,"Critical infrastructure events","worldmonitor.py+regimes.py","IMPLEMENTED"),
        (34,"Infrastructure cascade context","module_bridges.py","IMPLEMENTED"),
        (35,"Internet/BGP/cyber events","worldmonitor.py+regimes.py","IMPLEMENTED"),
        (36,"Cyber relevance gating","regimes.py","IMPLEMENTED"),
        (37,"Natural disasters","direct_sources.py+worldmonitor.py","IMPLEMENTED"),
        (38,"Event to potentially affected assets","regimes.py","IMPLEMENTED"),
        (39,"No hard-coded causality assumption","regimes.py","IMPLEMENTED"),
        (40,"Macro/central-bank data","direct_sources.py+macro.py","IMPLEMENTED"),
        (41,"Macro Event Clock","macro.py","IMPLEMENTED"),
        (42,"Scheduled vs surprise separation","macro.py","IMPLEMENTED"),
        (43,"Prediction markets as expectations","worldmonitor.py+macro.py","IMPLEMENTED"),
        (44,"Surprise score","regimes.py+macro.py","IMPLEMENTED"),
        (45,"Event Intelligence first connected to Lead-Lag","module_bridges.py","IMPLEMENTED"),
        (46,"External Event to Venue Price Discovery","price_discovery.py","IMPLEMENTED"),
        (47,"first_venue","price_discovery.py","IMPLEMENTED"),
        (48,"reaction_latency_ms","price_discovery.py","IMPLEMENTED"),
        (49,"peak_cross_venue_dispersion_bps","price_discovery.py","IMPLEMENTED"),
        (50,"edge_half_life_ms","price_discovery.py","IMPLEMENTED"),
        (51,"Remaining executable edge at HL","candidates.py","IMPLEMENTED"),
        (52,"Depth before/after event","outcomes.py","IMPLEMENTED"),
        (53,"Spread expansion","outcomes.py","IMPLEMENTED"),
        (54,"Depth withdrawal","outcomes.py","IMPLEMENTED"),
        (55,"Order-flow imbalance compatibility","market_features.py","IMPLEMENTED"),
        (56,"Aggressive trade/volume response","market_features.py","IMPLEMENTED"),
        (57,"OI response","market_features.py","IMPLEMENTED"),
        (58,"Funding response","market_features.py","IMPLEMENTED"),
        (59,"Liquidation/cascade response","market_features.py+regimes.py","IMPLEMENTED"),
        (60,"Executable capacity","outcomes.py","IMPLEMENTED"),
        (61,"Cross-Venue event regime filter","module_bridges.py","IMPLEMENTED"),
        (62,"Event-conditioned Cross-Venue comparison","module_bridges.py+scoreboard.py","IMPLEMENTED"),
        (63,"Never relax Cross-Venue economics","module_bridges.py","IMPLEMENTED"),
        (64,"Copy-Vault Event Intelligence bridge","module_bridges.py","IMPLEMENTED"),
        (65,"Leader event reaction latency","module_bridges.py","IMPLEMENTED"),
        (66,"Leader event specialization","module_bridges.py","IMPLEMENTED"),
        (67,"Compare leaders to no-event periods","validation.py+scoreboard.py","IMPLEMENTED"),
        (68,"No inference of leader motive/inside info","module_bridges.py","IMPLEMENTED"),
        (69,"Negative/no-reaction event dataset","validation.py","IMPLEMENTED"),
        (70,"Placebo controls","validation.py","IMPLEMENTED"),
        (71,"Randomized timestamps/labels","validation.py","IMPLEMENTED"),
        (72,"NO_EVENT control group","validation.py","IMPLEMENTED"),
        (73,"Backtest by event family","scoreboard.py+validation.py","IMPLEMENTED"),
        (74,"Backtest by asset","scoreboard.py+validation.py","IMPLEMENTED"),
        (75,"Backtest by venue","validation.py","IMPLEMENTED"),
        (76,"Backtest by session","validation.py","IMPLEMENTED"),
        (77,"Backtest by corroboration","validation.py","IMPLEMENTED"),
        (78,"Backtest by source tier","validation.py","IMPLEMENTED"),
        (79,"Backtest by surprise score","validation.py","IMPLEMENTED"),
        (80,"Backtest by velocity","validation.py","IMPLEMENTED"),
        (81,"Backtest by prediction movement","validation.py","IMPLEMENTED"),
        (82,"Chronological train/validation/OOS","validation.py","IMPLEMENTED"),
        (83,"Purged split / embargo","validation.py","IMPLEMENTED"),
        (84,"Parameter freeze before forward","protocol.py","IMPLEMENTED"),
        (85,"Post-freeze forward paper only","protocol.py","IMPLEMENTED"),
        (86,"Minimum N + uncertainty","validation.py+scoreboard.py","IMPLEMENTED"),
        (87,"PnL always net of all costs","outcomes.py+scoreboard.py","IMPLEMENTED"),
        (88,"Compare Event Intelligence to Lead-Lag baseline","scoreboard.py","IMPLEMENTED"),
        (89,"Incremental PnL measurement","validation.py+scoreboard.py","IMPLEMENTED"),
        (90,"PF/DD/ES/hit/capacity together","scoreboard.py","IMPLEMENTED"),
        (91,"Reject one-off/high-DD pseudo-edges","scoreboard.py","IMPLEMENTED"),
        (92,"Event Edge scoreboard","scoreboard.py","IMPLEMENTED"),
        (93,"UNMEASURABLE on missing costs/timestamps","candidates.py+outcomes.py+scoreboard.py","IMPLEMENTED"),
        (94,"Health/freshness integration","health.py","IMPLEMENTED"),
        (95,"Stale event cannot signal","health.py+candidates.py","IMPLEMENTED"),
        (96,"Source down != no event","health.py","IMPLEMENTED"),
        (97,"Intelligence gaps","health.py","IMPLEMENTED"),
        (98,"Coverage by source family","health.py","IMPLEMENTED"),
        (99,"Version source/event mapping","source_catalog.py","IMPLEMENTED"),
        (100,"Simple adapter-normalizer-storage-feature architecture","package architecture","IMPLEMENTED"),
        (101,"Self-host/direct-source compatible path","direct_sources.py+source_catalog.py","IMPLEMENTED"),
        (102,"AGPL boundary awareness","docs/event-intelligence-120-coverage.md","IMPLEMENTED"),
        (103,"Per-upstream license metadata","source_catalog.py","IMPLEMENTED"),
        (104,"World Monitor as source catalog","source_catalog.py","IMPLEMENTED"),
        (105,"Measure WM value-add latency","validation.py","IMPLEMENTED"),
        (106,"Primary source speed + WM corroboration","source_catalog.py+validation.py","IMPLEMENTED"),
        (107,"Positive and negative events","regimes.py","IMPLEMENTED"),
        (108,"Event to market response library","archive.py+scoreboard.py+sequences.py","IMPLEMENTED"),
        (109,"Recurring propagation sequences","sequences.py","IMPLEMENTED"),
        (110,"Require sequences frequent enough","sequences.py+scoreboard.py","IMPLEMENTED"),
        (111,"Explanatory vs predictive event separation","regimes.py+validation.py","IMPLEMENTED"),
        (112,"Operational causality at decision time","external_event.py+candidates.py","IMPLEMENTED"),
        (113,"LLM cannot invent absent facts","source_catalog.py","IMPLEMENTED"),
        (114,"AI summaries classification-only","source_catalog.py","IMPLEMENTED"),
        (115,"Classifier/model versioning","protocol.py","IMPLEMENTED"),
        (116,"Market relevance model not BUY/SELL","regimes.py","IMPLEMENTED"),
        (117,"Rare regime + frequent-statistics balance","scoreboard.py+validation.py","IMPLEMENTED"),
        (118,"Use events to make microstructure more selective","module_bridges.py","IMPLEMENTED"),
        (119,"Priority implementation waves encoded","docs/event-intelligence-120-coverage.md","IMPLEMENTED"),
        (120,"Success = proven incremental net dollars","scoreboard.py+validation.py","IMPLEMENTED"),
    ]
    return tuple(IdeaCoverage(i, title, component, status, note) for i,title,component,status,*rest in raw for note in [rest[0] if rest else ""])


IDEA_COVERAGE = _rows()


def coverage_summary() -> dict[str, object]:
    ids = [row.idea_id for row in IDEA_COVERAGE]
    statuses: dict[str, int] = {}
    for row in IDEA_COVERAGE:
        statuses[row.status] = statuses.get(row.status, 0) + 1
    return {
        "count": len(IDEA_COVERAGE),
        "min_id": min(ids) if ids else None,
        "max_id": max(ids) if ids else None,
        "unique_ids": len(set(ids)),
        "statuses": statuses,
        "all_implemented": bool(IDEA_COVERAGE) and all(row.status == "IMPLEMENTED" for row in IDEA_COVERAGE),
    }


__all__ = ["IDEA_COVERAGE", "IdeaCoverage", "coverage_summary"]
