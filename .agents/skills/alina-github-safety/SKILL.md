---
name: alina-github-safety
description: Use whenever Alina work reads or writes the GitHub repository, commits changes, updates main, or verifies that work was actually saved.
---

# Alina GitHub Safety

Repository: `Rapt0r06300/hyperliquid-smart-wallet-observer`. Target branch is `main` unless the user explicitly says otherwise.

Before writing, re-read current HEAD. Modify the smallest required set of files. Never manufacture an empty commit.

After writing:
1. re-read `main` HEAD;
2. compare the final commit with its parent;
3. verify expected changed paths appear;
4. require a non-empty diff when content was expected to change;
5. require the final tree SHA to differ from the parent tree;
6. only then report the GitHub work as saved.

If concurrent work moved HEAD, reconcile against the new HEAD rather than overwriting it blindly.

Do not create self-hosted runners, PC-wake workflows, signed exchange actions, keys, or real-order paths.
