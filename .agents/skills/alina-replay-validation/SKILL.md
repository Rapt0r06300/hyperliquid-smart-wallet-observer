---
name: alina-replay-validation
description: Use to build, run, inspect, or certify deterministic Alina replays from collected market and wallet evidence.
---

# Alina Replay Validation

Replay only from point-in-time evidence available at each simulated decision time.

Validate snapshot/bootstrap state, ordered deltas, sequence gaps, reconnects, dedup identities, event/receive timestamps, quote age, instrument-rule versions, and module-specific evidence before computing signals.

Never zero-fill omitted sparse fields or fabricate hidden queue/trailing-stop state. Unknown proof-critical state becomes UNCERTAIN or UNMEASURABLE.

Replay output must be reproducible from immutable inputs plus code/config SHA. Keep search/tuning evidence separate from final held-out proof.

Prefer deterministic local execution when the user has explicitly launched a local coding session; cloud automation must not depend on the PC.
