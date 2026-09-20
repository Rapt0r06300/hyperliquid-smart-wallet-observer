# Event Intelligence archive and source health

Alina stores Event Intelligence as structured R1/R2-style evidence rather than
retaining article text.

## Persistent archive

Default path:

`runtime/data/event_intelligence/events_r2.jsonl`

Every JSONL record contains:

- a strictly increasing sequence;
- the prior record SHA-256;
- the canonical payload SHA-256;
- the structured event payload;
- the current record SHA-256.

This forms a tamper-evident append-only chain. Existing records are verified on
open; a broken sequence, modified payload, duplicate identity or broken chain fails
closed instead of being silently accepted.

Deduplication is persistent across process restarts using `(source, event_id)`.

Article headline, snippet, body and summary text are intentionally absent from the
archive payload. The archive is designed for causal backtests, audit and long-lived
R1/R2 evidence, not for building a copy of publishers' content.

## Health and freshness

World Monitor coverage is translated into Alina's existing source-health model:

- fresh complete/current coverage plus fresh usable events -> `HEALTHY`;
- technically fresh coverage with no usable event -> `NO_FRESH_SIGNAL`;
- partial coverage -> `DATA_INCOMPLETE`;
- stale coverage -> `STALE`;
- unavailable/error/disabled or failed fetch -> `CRITICAL`;
- timestamps from the future -> `CRITICAL` clock failure.

This keeps the distinction between "the source works" and "the source produced a
fresh signal". A source outage is never interpreted as a quiet world.

## Data Vault

`source_discovery` recognizes `events_r2.jsonl` under an
`event_intelligence` directory as the `event_intelligence` dataset family.
It therefore enters the same family-source manifest used by the FULL/COLD and
incremental dataset tooling.

This change only prepares durable evidence for later private Data Vault backup.
It does not start a collector, make a hosted API request, or use a self-hosted
runner.
