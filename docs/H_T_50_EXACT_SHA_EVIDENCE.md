# H-T-50 — Exact-SHA CI / Windows / reproducibility evidence

Status: **IN PROGRESS**

Scope: ASF-E5 only (CI, reproducibility, supply-chain, Windows and release evidence). This file does not certify H-T-51.

## Fresh baseline

- Exact `main` SHA audited before this evidence update: `3428ebe559bb79e125e77955b8e8ce291aabf3a3`.
- `main` is protected, but required status checks are not enforced (`enforcement_level=off`, no required contexts/checks).
- `hypersmart/security-quality`: **GREEN** on the audited SHA.
- `hypersmart/coverage-parallel-probe`: **RED** on the audited SHA.

## Coverage disposition

The coverage workflow infrastructure itself completed all 32 shard jobs successfully. The aggregate ratchet alone failed:

- measured coverage: **93.2398%**;
- baseline/required coverage: **100%**;
- missing lines: **7,968** across **750** files;
- the gate explicitly keeps `max_missing=0` and must not be weakened.

Disposition: **BLOCKED outside ASF-E5 ownership for business-code coverage closure**. E5 must not lower the threshold, exclude files, add skips/xfails, or modify E2/E3/E4-owned business surfaces merely to manufacture green CI.

## Windows portable disposition

The Windows portable workflow is structurally fail-closed and reproducible at install time:

- CPython 3.14 x64 embeddable archive is hash-verified;
- dependencies are downloaded with `--require-hashes` and binaries only;
- installation is offline (`--no-index`) and hash-checked;
- the wheelhouse lock is recalculated and verified;
- `pip check`, tests, freeze evidence and package manifest are produced.

`tools/wheelhouse_lock.py` validates/generates `WHEELHOUSE_LOCK.json` from an already resolved wheelhouse. It does **not** regenerate `requirements-portable.txt` from `requirements-portable.in`.

`requirements-portable.txt` is explicitly marked generated / “do not edit by hand”, but still contains `pip==26.1.2`. The CI bootstrap pin was already remediated to a newer safe pip after the 26.1.2 advisory; therefore the portable dependency lock remains **STALE / BLOCKED** until a canonical lock-generation path is established and the generated lock is regenerated and revalidated. No manual edit of the generated lock is acceptable evidence.

## H-T-50 disposition summary

- CI action pinning / paper-read-only execution: **CORRIGÉ / implemented**.
- Security-quality on audited exact SHA: **GREEN**.
- 32-way coverage sharding infrastructure: **GREEN**.
- Aggregate 100% coverage ratchet: **BLOCKED** by real uncovered code, not by shard infrastructure.
- Windows portable offline/hash validation path: **implemented**.
- Portable requirements lock freshness: **BLOCKED / STALE** pending canonical regeneration path.
- Required status-check enforcement on protected `main`: **BLOCKED / not configured**.
- H-T-51 technical release certification: **NOT READY**.

No +4 USD / 3×4 / positive-PnL criterion is used here. No real trading execution is authorized or implied.
