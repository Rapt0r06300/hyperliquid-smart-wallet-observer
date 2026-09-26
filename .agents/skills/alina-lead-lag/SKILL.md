---
name: alina-lead-lag
description: Use for Alina Lead-Lag research, replay, timing validation, causal ordering, clock uncertainty, or anti-lookahead checks.
---

# Alina Lead-Lag

Use same-runner cross-venue receive ordering when available. Preserve exchange event time, local wall time, local monotonic receive time, clock probes, RTT and uncertainty separately.

A numerical timestamp lead is not causal proof. Require the measured lag to exceed timing uncertainty or have independent corroboration.

Model BBO sparsity correctly: no update does not refresh a quote. Enforce quote age, reconnect reconciliation, and no-lookahead boundaries.

Evaluate actionable post-signal markout and executable paper translation after fees, slippage, latency and capacity. Reject effects caused by stale quotes, network-path artifacts, clock error, or future information.

Paper/read-only only.
