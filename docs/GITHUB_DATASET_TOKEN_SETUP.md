# Private dataset token — one-time GitHub setup

The GitHub-hosted dataset job is fully implemented, but access to the private repository `Rapt0r06300/hypersmart-datasets` requires one repository Actions secret in the public Alina repository.

## Required secret

Name:

`ALINA_DATASET_READ_TOKEN`

The value must be a GitHub token that can **read** the private repository:

`Rapt0r06300/hypersmart-datasets`

Minimum intended scope:

- read repository metadata;
- read Releases and release assets;
- read repository contents needed by the Continuous Vault pointer/index.

No write permission is required for dataset jobs.

## Why a secret is required

The automatic `GITHUB_TOKEN` of `Rapt0r06300/hyperliquid-smart-wallet-observer` is scoped to that repository and cannot read a separate private repository.

The connector used during implementation cannot read or write GitHub Actions secrets, so the secret cannot be created from the chat.

## GitHub UI

In `Rapt0r06300/hyperliquid-smart-wallet-observer`:

1. **Settings**
2. **Secrets and variables**
3. **Actions**
4. **New repository secret**
5. Name: `ALINA_DATASET_READ_TOKEN`
6. Paste the read-only token
7. Save

Do not commit the token into any file.

## Verified state before secret creation

Run `35497137057` proved that the workflow reaches the explicit token gate on a GitHub-hosted Ubuntu runner. The first seven steps succeeded, then `Require private dataset token` failed because both `HYPERSMART_DATASET_TOKEN` and `GH_TOKEN` were empty.

No self-hosted runner is required for this workflow.
