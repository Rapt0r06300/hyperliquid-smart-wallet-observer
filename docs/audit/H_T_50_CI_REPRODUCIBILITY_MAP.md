# H—T-50 — CI / reproductibility / supply-chain / Windows / scoreboards

Status: **IN PROGRESS / EVIDENCE MAP ESTABLISHED**  
Scope: CI reproducibility, dependency/supply-chain integrity, Windows parity, exact-SHA evidence and scoreboard/release gates.  
Done contract: technical proof only. Economic +4 USD targets are explicitly outside this lot.

## Current verified surfaces

| Requirement | State | Canonical evidence |
| --- | --- | --- |
| Paper/read-only CI | IMPLEMENTED | `.github/workflows/ci.yml` forces `HL_ENABLE_MAINNET_EXECUTION=0` and `HL_ENABLE_TESTNET_EXECUTION=0`; CI permissions are `contents: read` |
| Linux regression matrix | IMPLEMENTED | `tests-linux` runs six deterministic shards after the security/import gate |
| Windows critical-path CI | IMPLEMENTED | `tests-windows` runs critical runtime, portability, launcher, archive and safety tests on `windows-latest` |
| Runtime replay / forward parity | IMPLEMENTED | `runtime-replay` exercises paper pipeline, producer/consumer, replay parity, portability and HARVEST launcher checks |
| Third-party GitHub Actions pinning | IMPLEMENTED ON CANONICAL CI | canonical `ci.yml` pins checkout/setup-python/upload-artifact to immutable commit SHAs |
| Coverage parallel probe | IMPLEMENTED, CURRENT RUN PENDING | `.github/workflows/coverage-parallel-probe.yml`; exact-SHA result remains a blocking evidence input |
| Branch protection | PARTIAL | `main` is protected, but required status checks currently have `enforcement_level=off` and no required contexts |
| Dependency resolution reproducibility | BLOCKED / NOT YET COMPLETE | canonical CI upgrades `pip` dynamically and installs `.[dev]` plus research requirements without an exact resolved lock for the full environment |
| Project dependency declarations | BOUNDED, NOT LOCKED | `pyproject.toml` uses compatibility ranges; this is valid packaging metadata but not a byte-for-byte reproducible environment lock |
| Exact-SHA release evidence | IN PROGRESS | every H—T-50/51 disposition must bind CI evidence to the exact release SHA, never to an ancestor assumption |

## Reproducibility finding

The canonical CI is security-conscious but not yet fully reproducible. `actions/*` dependencies are pinned by immutable commit SHA, while Python dependency resolution remains time-dependent because CI executes `python -m pip install --upgrade pip` and resolves `python -m pip install -e ".[dev]"` from version ranges. The project metadata intentionally constrains versions with lower/upper bounds, but a fresh run can still select a different transitive environment over time.

This is a **real H—T-50 blocker**, not a reason to weaken tests. Closure requires an explicit, maintained resolution strategy (for example a canonical hash-locked requirements set/wheelhouse contract covering the CI/runtime environment) and proof that Linux + Windows consume the same declared dependency authority where applicable.

## Branch-protection finding

`main` is protected, but the current branch response reports required-status-check enforcement as off with an empty required-context set. Protection therefore does not yet prove that H—T-50 gates are impossible to bypass administratively. H—T-51 must not claim release certification from branch protection until required checks are explicitly enforced and freshly verified.

## Exact-SHA boundary

At the start of this map, HEAD was `31e59a84be33cbd379418670079c9b7400215b3b`. Its `coverage-parallel-probe` run was queued, not green. This map intentionally records the state as pending instead of inheriting success from an earlier commit.

## Next safe E5 units

1. Inventory the repository's existing wheelhouse/lock/release-integrity mechanisms and classify them as canonical, partial, historical, superseded or blocked.
2. Close any CI-only reproducibility gaps with TDD/verification where behavior changes are required; never lower coverage, thresholds or test scope.
3. Verify Windows and Linux consume equivalent dependency/evidence contracts.
4. Build the exact-SHA H—T-50 evidence bundle, then move to H—T-51 only after remaining blockers have explicit disposition.

No Copy-Vault, Lead-Lag or Cross-Venue business logic is modified by this map.