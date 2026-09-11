# H-T-50 — Exact-SHA CI / Windows / reproducibility evidence

Status: **IN PROGRESS**

Scope: ASF-E5 only (CI, reproducibility, supply-chain, Windows and release evidence). This file does not certify H-T-51.

## Fresh baseline

- Exact `main` SHA audited before this evidence update: `38aa5b4dca1fc6248c83d75e64191f206a033a7a`.
- `main` is protected, but required status checks are not enforced (`enforcement_level=off`, no required contexts/checks).
- `hypersmart/security-quality`: **GREEN** on the audited SHA.
- `hypersmart/coverage-closure-fast`: **GREEN** on the audited SHA.
- `hypersmart/coverage-parallel-probe`: **RED** on the audited SHA.

The latest commit before this evidence refresh (`38aa5b4d...`, `test(ci): isolate autonomous guard monotonic clock`) changes only `tests/test_coverage_closure_autonomous_research_guard.py`; no E2/E3/E4 business surface is touched by that commit.

## Coverage disposition

The current exact-SHA workflow produced **33 artifacts**: one aggregate `coverage-parallel-probe-<sha>` artifact plus **32 `coverage-shard-*` artifacts**. The aggregate artifact is therefore based on a complete 32-shard collection; the red verdict remains the 100% aggregate ratchet, not missing shard evidence.

Fresh aggregate from artifact `coverage-parallel-probe-38aa5b4dca1fc6248c83d75e64191f206a033a7a`:

- measured coverage: **93.20829853113636%**;
- baseline/required coverage: **100%**;
- covered statements: **110,477 / 118,527**;
- missing lines: **8,050**;
- files with gaps: **754**;
- aggregate completeness flag: **false**.

Compared with the previous documented baseline (`3428ebe5...`: 93.2398%, 7,968 missing lines across 750 files), the debt increased by **82 missing lines** and **4 files with gaps**. This is a real coverage movement and must remain visible; it is not grounds to weaken the ratchet.

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
- Coverage-closure-fast on audited exact SHA: **GREEN smoke only; not release evidence for 100%**.
- 32-way coverage collection: **GREEN / complete artifact set**.
- Aggregate 100% coverage ratchet: **BLOCKED** by real uncovered code; fresh exact-SHA value is 93.20829853113636% with 8,050 missing lines.
- Windows portable offline/hash validation path: **implemented**.
- Portable requirements lock freshness: **BLOCKED / STALE** pending canonical regeneration path.
- Required status-check enforcement on protected `main`: **BLOCKED / not configured**.
- H-T-51 technical release certification: **NOT READY**.

No +4 USD / 3×4 / positive-PnL criterion is used here. No real trading execution is authorized or implied.
