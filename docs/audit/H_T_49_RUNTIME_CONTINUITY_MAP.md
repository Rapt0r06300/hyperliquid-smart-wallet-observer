# H—T-49 — AgiFlow / Task Graph / runtime continuity map

Status: **TECHNICALLY COMPLETE / READY FOR REVIEW**  
Scope: roadmap V5 §§26→28F + validated 776+ runtime-continuity additions.  
Done contract: technical proof only. Economic +4 USD targets are explicitly outside this lot.

## Canonical surfaces

| Requirement | State | Canonical evidence |
| --- | --- | --- |
| Persistent Task Graph | IMPLEMENTED + HARDENED | `src/hl_observer/ops/task_graph_contract.py`, `tests/test_task_graph_contract.py`, persisted release/timeline tests |
| Ownership token / lease | IMPLEMENTED + HARDENED | fail-closed owner/token/lease checks, authenticated handoff, expired-lease rejection, canonical task-id uniqueness |
| Dependency integrity | IMPLEMENTED + HARDENED | dangling dependency, malformed dependency payload and self-dependency are rejected before restore/mutation |
| Resumable interrupted work | IMPLEMENTED + TESTED | persisted graph keeps ownership history and evidence attempts across restore/reclaim paths |
| Done Contract | IMPLEMENTED | task state carries verifiable evidence/status instead of inferring completion from prose or economic outcome |
| Doctor / runtime checks | IMPLEMENTED + TESTED | `src/hl_observer/cli.py` doctor, `hyper_smart_observer/app/main.py` doctor/runtime-check commands; failure paths covered by CLI/health diagnostics tests |
| Safety / fail-fast checks | IMPLEMENTED + TESTED | `src/hl_observer/security/safety_audit.py`, `hyper_smart_observer/audit/safety_audit.py`, `tests/test_safety_audit.py`, `tests/test_audit_multi_directory_safety.py`, `tests/test_hypersmart_audit_safety.py`, CLI command failure tests |
| SQLite / runtime DB hygiene | IMPLEMENTED + FAIL-CLOSED | `hyper_smart_observer/audit/db_audit.py` delegates to runtime file scanning and is included in the aggregate safety audit |
| Archive readiness / symlink safety | IMPLEMENTED + HARDENED | `hyper_smart_observer/audit/archive_audit.py`, archive additional/symlink/repository-hygiene tests; latest symlink escape hardening preserves fail-closed archive boundaries |
| Read-only dashboard | IMPLEMENTED | dashboard export/status surfaces are observational only; safety audit includes dashboard validation; UI status consumes audit state instead of enabling execution |
| Current vs historical | IMPLEMENTED BY AUTHORITY RULE | current runtime state is driven by current code/runtime contracts; historical audit/backups/KILL evidence remain traceable but are not treated as current executable truth |
| Measured-law / negative evidence memory | IMPLEMENTED | measured-law and killed-hypothesis registries remain durable evidence; negative evidence cannot be silently recycled as a fresh passing hypothesis |
| +4 USD objective | NOT A DONE GATE | intentionally excluded from AgiFlow technical completion for this roadmap lot |

## Adversarial Task Graph hardening already delivered

The persisted graph now rejects, fail-closed, at least the following corrupted or unauthorized states:

- node/lease `task_id` divergence;
- node/lease owner divergence;
- unauthenticated ownership handoff;
- expired-lease mutation/release misuse;
- duplicate canonical task IDs;
- empty mutation credentials;
- dangling dependencies;
- malformed `depends_on` payloads;
- unknown/non-string task types;
- inconsistent ownership timelines;
- self-dependencies;
- archive paths escaping the allowed root through symlinks.

Interrupted-work recovery preserves ownership/history and increments evidence attempts rather than silently declaring Done.

## Verification boundary

At exact SHA `4c6152f8e3c97d2fe44bdcba6a4deabc29ef3f9c`, all 32 pytest shards of the repository-wide probe completed successfully. Subsequent source changes before this map are restricted to additional Task Graph TDD hardening, the coverage-workflow recursive-discovery repair and a Lead-Lag documentation update. No doctor, DB audit, archive-audit implementation, safety-audit implementation or dashboard execution surface was relaxed.

The current-HEAD Actions query at review time reports no failed workflow for `1ac5e0d47c78740257dd7eade2fb038eaea1d50f`; long-running coverage/CI jobs may still be queued and remain owned by H—T-50 rather than being duplicated as an H—T-49 Done condition.

## Completion decision

All four H—T-49 acceptance criteria are satisfied at the technical-contract level:

1. §§26→28F + 776+ are linked to resumable state, ownership and evidence-backed Done Contracts.
2. AgiFlow completion is explicitly technical and never keyed to +4 USD.
3. Doctor/runtime/safety/SQLite/archive/dashboard surfaces have fail-closed checks and regression coverage; the Task Graph recovery path has dedicated adversarial persistence tests.
4. Historical assets remain traceable while current runtime authority stays anchored to current contracts/evidence.

Repository-wide coverage percentage and branch-protection administration remain H—T-50 responsibilities and must not be copied into this lot as false blockers.
