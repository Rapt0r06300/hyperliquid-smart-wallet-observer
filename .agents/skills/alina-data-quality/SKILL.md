---
name: alina-data-quality
description: Use to audit or certify Alina market data, Dataset V2 bundles, collector output, timing integrity, continuity, provenance, or replay readiness.
---

# Alina Data Quality

Read the canonical spec's collector and evidence contracts.

Check, at minimum: source identity, schema/version, event and receive timestamps, clock offset/RTT uncertainty, sequence continuity, snapshots plus deltas, duplicates, reconnect boundaries, quote age, missing intervals, archive repairs, hashes, manifest/code SHA, and immutable provenance.

Never silently interpolate a proof-critical gap. Repair only from an authoritative point-in-time source. Otherwise delimit and quarantine the interval.

Evaluate data against the module that will consume it; generic completeness is insufficient. Return a compact machine-readable PASS / QUARANTINE / UNMEASURABLE result with exact reasons and affected intervals.

No real orders or signed probes.
