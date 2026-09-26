---
name: alina-completion-discipline
description: Use for long or multi-step Alina work when the user asks to continue, finish everything, implement a plan, or avoid premature stops and retry loops.
---

# Alina Completion Discipline

Use one LLM controller only. Do not spawn subagents.

1. Read the exact user request and the smallest relevant slice of the canonical spec.
2. Build a compact done-contract: requested outputs, hard constraints, verification required, and unfinished items.
3. Work the highest-priority unfinished item to a verified state.
4. Record only compact durable progress, then immediately continue to the next independent unfinished item.
5. Do not ask for confirmation merely because an intermediate milestone succeeded.

## Anti-stop rules

Do not stop after planning if implementation was requested. Do not stop after one file, one commit, one test, or one module while requested independent work remains. Do not promise future/background work.

If context is large, preserve a compact checkpoint containing HEAD, changed paths, completed items, remaining items, and exact next action. Resume from the checkpoint instead of rescanning everything.

## Anti-loop rules

Never repeat a materially identical failed action indefinitely.
- failure 1: diagnose;
- failure 2: change method, inputs, or isolation strategy;
- failure 3: mark an exact blocker, preserve valid work, and continue independent tasks.

Do not create dummy files or empty commits to simulate progress.

## Done gate

For GitHub-changing work: re-read final HEAD. If a content change was expected, compare final commit to its parent and require a non-empty diff plus a different tree SHA. Report incomplete work explicitly if a hard external blocker remains.

Platform termination, missing credentials, unavailable tools, safety limits, and external outages are real hard stops; record them precisely rather than claiming completion.
