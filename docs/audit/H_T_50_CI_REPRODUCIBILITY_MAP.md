# H—T-50 — CI / reproductibility / supply-chain / Windows / scoreboards

Status: **IN PROGRESS / EVIDENCE MAP UPDATED**  
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
| Reproducible pip bootstrap | CORRIGÉ | all workflow bootstrap sites consume `requirements-ci-bootstrap.txt` with `--require-hashes`; pip is pinned to 26.2.1 after the supply-chain gate rejected vulnerable 26.1.2 |
| Coverage parallel probe | IMPLEMENTED, CURRENTLY RED | exact-SHA `905e8caccf6c47e58cfdaef73fc1d120e7b907a9` reports `hypersmart/coverage-parallel-probe=failure`; no threshold/skip/exclusion was changed |
| Branch protection | PARTIAL | `main` is protected, but required status checks remain non-enforced / absent in the last verified branch-protection evidence |
| Dependency resolution reproducibility | PARTIAL / BLOCKED | pip bootstrap is fixed, but editable `.[dev]`, research requirements and auxiliary tools still permit time-dependent resolution |
| Windows portable lock | BLOCKED / STALE | `requirements-portable.txt` is generated and still carries `pip==26.1.2`; `requirements-portable.in` is range-based and no executable canonical lock-regeneration command is present in repository code |
| Project dependency declarations | BOUNDED, NOT LOCKED | `pyproject.toml` and `requirements-portable.in` use compatibility ranges; valid packaging metadata but not a byte-for-byte reproducible environment authority |
| Exact-SHA release evidence | IN PROGRESS | every H—T-50/51 disposition must bind CI evidence to the exact release SHA, never to an ancestor assumption |

## Reproducibility disposition

The previous unpinned `pip install --upgrade pip` behavior is **CORRIGÉ**: workflow bootstrap now uses a hash-locked requirements authority. The supply-chain gate correctly rejected pip 26.1.2 because of PYSEC-2026-3721; the canonical bootstrap was moved to pip 26.2.1 without adding an ignore, xfail, skip, exclusion, or weaker gate.

The environment as a whole is still **PARTIAL / BLOCKED**. CI continues to resolve some project/tool dependencies from ranges, so a fresh resolver can select different versions over time. H—T-50 cannot claim full reproducibility until the remaining CI/runtime dependency authorities have an explicit lock strategy and Linux/Windows parity evidence.

## Windows portable lock disposition

`requirements-portable.in` explicitly says it must be resolved into `requirements-portable.txt`, while the generated lock says not to edit it by hand. The generated lock still contains pip 26.1.2, now inconsistent with the security-approved CI bootstrap.

Repository search finds references to the portable lock and historical roadmap text mentioning `pip-compile`, but no executable, canonical lock-regeneration script/workflow is present in the current codebase. Therefore E5 will not hand-edit the generated lock or fabricate regeneration evidence. This is classified **BLOCKED** until a canonical generator contract is implemented or recovered and then exercised on Windows with fresh exact-SHA proof.

## Coverage disposition

At exact SHA `905e8caccf6c47e58cfdaef73fc1d120e7b907a9`, `hypersmart/security-quality` is GREEN and `hypersmart/coverage-parallel-probe` is RED. This remains real technical debt. No baseline, coverage target, shard scope, skip, xfail, or exclusion is changed to manufacture green.

## Branch-protection disposition

`main` is protected, but the last verified protection evidence did not enforce required status contexts. Protection therefore does not yet prove H—T-50 gates are administratively mandatory. H—T-51 must not claim release certification until the required checks are explicitly enforced and freshly verified.

## Next safe E5 units

1. Implement or recover a canonical portable-lock regeneration contract, then regenerate and validate Windows portable dependencies without manual lock editing.
2. Continue replacing CI-only time-dependent dependency resolution with explicit maintained authorities, one independently testable unit at a time.
3. Produce Linux/Windows parity evidence and classify every remaining red gate with owner/disposition.
4. Build the exact-SHA H—T-50 evidence bundle, then move to H—T-51 only after remaining blockers have explicit disposition.

No Copy-Vault, Lead-Lag or Cross-Venue business logic is modified by this map.
