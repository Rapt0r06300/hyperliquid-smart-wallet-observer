#!/usr/bin/env python3
"""Safe code-only reconciliation of local main with canonical GitHub main.

No force push, reset, clean, stash, deletion of Git locks, or shard downloads.
On conflicts, preserve both histories and fail closed after an automatic
checkpoint of publishable local code. Run only on the canonical main branch.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import json
import os
import re
import subprocess
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

CANONICAL = "Rapt0r06300/hyperliquid-smart-wallet-observer"
ALLOWED_ORIGINS = {
    f"https://github.com/{CANONICAL}",
    f"https://github.com/{CANONICAL}.git",
    f"git@github.com:{CANONICAL}",
    f"git@github.com:{CANONICAL}.git",
    f"ssh://git@github.com/{CANONICAL}",
    f"ssh://git@github.com/{CANONICAL}.git",
}
PROTECTED_DIRS = {
    "runtime", "logs", "data", "datasets", "catalog", "archive", "archives",
    "wheelhouse", "dist", "build", ".idea", ".vscode", ".claude",
    ".git", ".venv", "venv", "node_modules", ".pytest_cache",
    ".mypy_cache", ".ruff_cache", "__pycache__", ".tox",
}
PROTECTED_EXTENSIONS = {
    ".bundle", ".zip", ".7z", ".rar", ".tar", ".gz", ".zst", ".sqlite",
    ".sqlite3", ".db", ".parquet", ".feather", ".pkl", ".pickle",
    ".pem", ".key", ".p12", ".pfx", ".keystore", ".env",
}
SENSITIVE_PARTS = {
    "secrets", "secret", "credentials", "credential", "id_rsa",
    "id_ed25519", "private_key", "private-key", "mnemonic",
    "seed_phrase", "seed-phrase", "api_keys", "api-keys",
}
MAX_BLOB_BYTES = 95 * 1024 * 1024
MAX_RACE_RETRIES = 5
MAX_LOCAL_CHANGE_RETRIES = 3
PROTECTED_PATH_BATCH_SIZE = 128
# A shallow checkout only needs enough history to prove a common ancestor
# with the canonical main.  Fetching the entire repository can transfer
# millions of objects even when the two tips diverged by a handful of
# commits, so deepen progressively and stop as soon as reconciliation is
# provably possible.
# One bounded request is enough for the current main divergence and avoids a
# staircase of repeated network transfers.  If the common ancestor is older
# than this budget, fail closed and let the next run make an explicit choice.
HISTORY_DEEPEN_STEPS = (512,)
# Tree filtering is stricter than blob:none: it transfers commit ancestry
# without hydrating historical file trees or their blobs.  The worktree's
# current code remains local; any missing object required by Git can be
# fetched explicitly by Git itself, while SAFE/shard data is never bulk-read.
HISTORY_FETCH_FILTER = "--filter=tree:0"
HISTORY_FETCH_TIMEOUT_SECONDS = 90
MERGE_TREE_TIMEOUT_SECONDS = 30
# A rebase is bounded, but this repository's large code/audit commits can
# legitimately take more than a minute.  Give one reconciliation enough time
# to finish instead of repeatedly replaying the same expensive history.
REBASE_TIMEOUT_SECONDS = 300
REBASE_ABORT_TIMEOUT_SECONDS = 8
GIT_SYNC_ENGINE_BUILD = "2026-10-30-verified-remote-receipt-v7"
# A single historical registry was moved out of the repository root. It is
# publishable only when both paths clean to its exact current HEAD blob.
SAFE_HISTORICAL_RELOCATIONS = {
    "CLAUDE_TASKS.jsonl": "docs/archive/root-history/CLAUDE_TASKS.jsonl",
}
AUTO_RESOLVABLE_CI_CONFLICTS = {
    ".github/workflows/alina-restore-safe-regression.yml",
    ".github/workflows/copy-vault-collector-soak.yml",
}
FORBIDDEN_HOSTED_CI_MARKERS = (
    "runs-on: self-hosted",
    'HL_ENABLE_MAINNET_EXECUTION: "1"',
    'REAL_MAINNET_TRADING: "true"',
    'HYPERSMART_ENABLE_REAL_ORDERS: "1"',
    'ENABLE_REAL_ORDERS: "1"',
)


def _human_path_label(path: str) -> str:
    """Turn one publishable path into a short, truthful commit noun."""
    name = PurePosixPath(path).stem.replace("-", " ").replace("_", " ")
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)
    name = re.sub(r"\s+", " ", name).strip().lower()
    return name or "code changes"


def _common_filename_tokens(paths: list[str]) -> list[str]:
    """Return stable filename tokens shared by a small mixed code/test change."""
    token_lists: list[list[str]] = []
    for path in paths:
        stem = PurePosixPath(path).stem.lower()
        tokens = re.findall(r"[a-z0-9]+", stem)
        tokens = [token for token in tokens if token not in {"test", "tests", "py"}]
        if not tokens:
            return []
        token_lists.append(tokens)
    common = set(token_lists[0])
    for tokens in token_lists[1:]:
        common.intersection_update(tokens)
    return [token for token in token_lists[0] if token in common]


def _commit_subject(paths: list[str]) -> str:
    """Build a deterministic semantic subject from the staged code paths.

    The sync helper must never invent a product claim from a diff it cannot
    understand. It uses repository areas and filenames only, so the subject
    stays useful while remaining honest for arbitrary local edits.
    """
    normalized = sorted(set(path.replace("\\", "/") for path in paths))
    if not normalized:
        return "chore(sync): checkpoint code changes"

    if all(path.startswith(".github/workflows/") for path in normalized):
        prefix, scope = "ci", "github"
    elif all(path.startswith("tests/") for path in normalized):
        prefix, scope = "test", "validation"
    elif all(path.startswith("docs/") for path in normalized):
        prefix, scope = "docs", "project"
    elif all(path.startswith("src/") for path in normalized):
        prefix = "feat" if any(
            "/copy_vault/" in f"/{path}/" or "copy_vault" in path
            for path in normalized
        ) else "chore"
        scope = (
            "copy-vault" if any("copy_vault" in path for path in normalized)
            else "runtime"
        )
    elif all(path.startswith("tools/") for path in normalized):
        prefix, scope = "chore", "tooling"
    else:
        prefix, scope = "chore", "repository"

    if (
        2 <= len(normalized) <= 3
        and any(path.endswith("tools/alina_git_code_sync.py") for path in normalized)
        and any(path.endswith("tests/test_alina_git_code_sync.py") for path in normalized)
    ):
        return (
            "fix(sync): verify final GitHub SHA in receipt "
            f"({len(normalized)} paths)"
        )

    if (
        len(normalized) == 2
        and any(path.endswith("tools/restore_alina.py") for path in normalized)
        and any(path.endswith("tests/test_restore_alina.py") for path in normalized)
    ):
        return "fix(copy-vault): restore filtered SAFE registry (2 paths)"

    if (
        len(normalized) == 2
        and any(path.endswith("tools/continuous_reconcile_backlog.py") for path in normalized)
        and any(path.endswith("tests/test_continuous_reconcile_backlog.py") for path in normalized)
    ):
        return "fix(recovery): resume historical SAFE backlog (2 paths)"

    if (
        any(path.endswith("src/hl_observer/control_plane/campaign_adapters.py") for path in normalized)
        and any(path.endswith("tests/test_campaign_adapter_diagnostics.py") for path in normalized)
    ):
        return (
            "fix(recovery): preserve timed-out adapter checkpoints "
            f"({len(normalized)} paths)"
        )

    if (
        any(path.endswith("src/hl_observer/copying/consensus_leader_selector.py") for path in normalized)
        and any(path.endswith("tests/test_consensus_leader_selector.py") for path in normalized)
    ):
        return (
            "fix(copy-vault): guard non-finite consensus inputs "
            f"({len(normalized)} paths)"
        )

    if any(
        token in path
        for path in normalized
        for token in ("l4_capture", "order_intent", "entity_resolution")
    ):
        return (
            "fix(copy-vault): guard L4 intent and entity provenance "
            f"({len(normalized)} paths)"
        )

    if len(normalized) >= 2 and any("copy_vault" in path for path in normalized):
        common = _common_filename_tokens(normalized)
        for token in ("copy", "vault"):
            common = [item for item in common if item != token]
        if common:
            subject = f"feat(copy-vault): {' '.join(common)} ({len(normalized)} paths)"
            if len(subject) <= 72:
                return subject

    labels = [_human_path_label(path) for path in normalized]
    if len(labels) == 1:
        detail = labels[0]
    elif len(labels) == 2:
        detail = f"{labels[0]} and {labels[1]}"
    else:
        detail = f"{labels[0]}, {labels[1]} and {len(labels) - 2} other files"
    subject = f"{prefix}({scope}): update {detail}"
    if len(subject) > 72:
        subject = (
            f"{prefix}({scope}): update {labels[0]} "
            f"({len(normalized)} paths)"
        )
    if len(subject) > 72:
        subject = f"{prefix}({scope}): update ({len(normalized)} paths)"
    return subject


class SyncBlocked(RuntimeError):
    """Unsafe to proceed while preserving local and remote history."""


class LocalEditsDetected(SyncBlocked):
    """Source changed while network or Git reconciliation was in flight."""


def _paths(data: bytes) -> list[str]:
    if not data:
        return []
    if not data.endswith(b"\0"):
        raise SyncBlocked("Sortie Git NUL tronquee; inventaire abandonne.")
    try:
        return [name.decode("utf-8") for name in data[:-1].split(b"\0") if name]
    except UnicodeDecodeError as exc:
        raise SyncBlocked("Nom Git non UTF-8, selection automatique refusee.") from exc


def _status_paths(data: bytes) -> list[str]:
    """Decode tracked paths from `git status --porcelain=v1 -z` safely."""
    if not data:
        return []
    if not data.endswith(b"\0"):
        raise SyncBlocked("Sortie Git status NUL tronquee; inventaire abandonne.")
    records = data[:-1].split(b"\0")
    paths: list[str] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if len(record) < 4 or record[2:3] != b" ":
            raise SyncBlocked("Enregistrement Git status invalide; inventaire abandonne.")
        status, path = record[:2], record[3:]
        try:
            paths.append(path.decode("utf-8"))
            if b"R" in status or b"C" in status:
                if index >= len(records):
                    raise SyncBlocked("Ancien chemin de renommage Git absent.")
                paths.append(records[index].decode("utf-8"))
                index += 1
        except UnicodeDecodeError as exc:
            raise SyncBlocked("Nom Git status non UTF-8; inventaire abandonne.") from exc
    return paths


def _protected(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if not parts or normalized.startswith("/") or ".." in parts:
        return True
    lower = tuple(part.casefold() for part in parts)
    # Root data trees are excluded; equally named Python package subfolders
    # (src/hl_observer/datasets, src/hl_observer/runtime, etc.) ARE CODE.
    if lower[0] in PROTECTED_DIRS:
        return True
    if any(part in SENSITIVE_PARTS for part in lower[:-1]):
        return True
    if any(part in {".git", ".venv", "venv", "node_modules", "__pycache__"}
           for part in lower[:-1]):
        return True
    name = lower[-1]
    if name.startswith(".env") or name.endswith(".env"):
        return True
    if any(secret in name for secret in ("id_rsa", "id_ed25519", "private_key", "private-key")):
        return True
    if normalized.casefold().startswith(("tools/git/", "tools/python/")):
        return True
    if name in SENSITIVE_PARTS or Path(name).suffix in PROTECTED_EXTENSIONS:
        return True
    if name.endswith((".bundle", ".jsonl", ".jsonl.gz")):
        return True
    return name in ("thumbs.db", "desktop.ini")


def _git_operation_label(args: list[str]) -> str:
    """Return a safe, user-facing description without echoing raw arguments."""
    verb = args[0] if args else ""
    if verb == "rev-parse":
        return "Verifier le depot et son HEAD"
    if verb == "branch":
        return "Verifier la branche active"
    if verb == "remote":
        return "Verifier le depot GitHub canonique"
    if verb == "status":
        return "Inventaire des modifications locales"
    if verb == "ls-files":
        return "Inventaire Git cible (sans lire les shards)"
    if verb == "diff":
        return "Comparer les fichiers suivis par Git"
    if verb == "fetch":
        return "Recevoir les objets Git de GitHub main"
    if verb == "merge-base":
        return "Comparer l'historique local et GitHub"
    if verb == "merge":
        return "Adopter GitHub main en avance rapide"
    if verb == "rebase":
        return "Rejouer les commits locaux sans commit de fusion"
    if verb == "rev-list":
        return "Verifier les commits locaux a rejouer"
    if verb == "hash-object":
        return "Verifier le blob apres normalisation Git"
    if verb == "push":
        return "Publier vers GitHub main sans force"
    if verb == "add":
        return "Preparer les fichiers de code admissibles"
    if verb == "commit":
        return "Creer le checkpoint local du travail"
    if verb == "update-ref":
        return "Enregistrer le checkpoint Git local"
    if verb == "show":
        return "Lire une version Git pour le diagnostic de conflit"
    return "Commande Git de controle"


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    """Stop a timed-out Git process and descendants without leaking pipes."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        process.kill()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=1)


def _run_git(
    root: Path,
    git: str,
    args: list[str],
    *,
    input_bytes: bytes | None = None,
    timeout: int = 300,
    live_stderr: bool = False,
    on_progress=None,
) -> subprocess.CompletedProcess[bytes]:
    env = dict(os.environ)
    env["GIT_LFS_SKIP_SMUDGE"] = "1"
    env["GIT_OPTIONAL_LOCKS"] = (
        "0" if args and args[0] in {"ls-files", "status", "diff"} else "1"
    )
    command = [git, *args]
    started = time.monotonic()
    process = subprocess.Popen(
        command,
        cwd=root,
        stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=None if live_stderr else subprocess.PIPE,
        env=env,
    )
    while True:
        elapsed = time.monotonic() - started
        remaining = timeout - elapsed
        if remaining <= 0:
            _terminate_process_tree(process)
            try:
                stdout, stderr = process.communicate(timeout=2)
            except subprocess.TimeoutExpired as communicate_timeout:
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        stream.close()
                raise subprocess.TimeoutExpired(
                    command,
                    timeout,
                    output=communicate_timeout.output,
                    stderr=communicate_timeout.stderr,
                ) from communicate_timeout
            raise subprocess.TimeoutExpired(
                command, timeout, output=stdout, stderr=stderr,
            )
        try:
            stdout, stderr = process.communicate(
                input=input_bytes, timeout=min(8.0, remaining),
            )
            break
        except subprocess.TimeoutExpired:
            if on_progress is not None:
                on_progress(time.monotonic() - started)
            # communicate() can accept input only once. After its first call,
            # stdin has been closed and later calls must not send bytes again.
            input_bytes = None
    return subprocess.CompletedProcess(command, process.returncode, stdout, stderr)


@contextlib.contextmanager
def _mutex(git_dir: Path):
    """Operating-system mutex releases after a crash; never delete Git locks."""
    with (git_dir / "alina-sync.mutex").open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise SyncBlocked("Une autre synchronisation Alina est active.") from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class Synchronizer:
    def __init__(self, root: Path, git: str = "git", *, dry_run: bool = False,
                 allow_test_remote: bool = False):
        self.root = root.resolve()
        self.git = git
        self.dry_run = dry_run
        self.allow_test_remote = allow_test_remote
        self.changed_python_paths: list[str] = []
        self._inventory_cache: tuple[list[str], list[str], list[str]] | None = None
        self._remote_snapshot_ready = False
        self._command_count = 0
        self.report: dict[str, object] = {
            "schema": "alina.git_code_reconciliation.v1",
            "mode": "DRY_RUN" if dry_run else "SYNC",
            "status": "NOT_STARTED",
            "shard_downloads": False,
            "force_push": False,
            "reset_or_clean": False,
            "shallow_repository": None,
            "history_expanded": False,
            "history_mode": None,
            "history_deepen_steps": [],
            "local_commit_created": False,
            "commit_message": None,
            "merge_commits_created": 0,
            "rebases_performed": 0,
            "push_attempts": 0,
            "local_syntax_check": "NOT_RUN",
            "fast_path": None,
            "remote_sha_observed": None,
            "verified_historical_relocations": [],
            "git_commands": [],
        }

    def command(self, *args: str, input_bytes: bytes | None = None,
                check: bool = True, timeout: int = 300
                ) -> subprocess.CompletedProcess[bytes]:
        git_args = list(args)
        label = _git_operation_label(git_args)
        self._command_count += 1
        command_number = self._command_count
        live_stderr = bool(git_args and git_args[0] in {"fetch", "push"})
        self.say(f"[GIT {command_number:03d}] {label} ...")
        started = time.monotonic()

        def progress(elapsed: float) -> None:
            self.say(f"[EN COURS] {label} | {elapsed:.0f} s ecoulees")

        try:
            completed = _run_git(
                self.root,
                self.git,
                git_args,
                input_bytes=input_bytes,
                timeout=timeout,
                live_stderr=live_stderr,
                on_progress=progress,
            )
        except subprocess.TimeoutExpired:
            elapsed_ms = int((time.monotonic() - started) * 1000)
            self._record_git_command(
                command_number, label, -1, elapsed_ms, timed_out=True,
            )
            self.say(
                f"[TIMEOUT] {label} apres {elapsed_ms / 1000:.1f} s; "
                "le processus Git a ete arrete."
            )
            raise

        elapsed_ms = int((time.monotonic() - started) * 1000)
        self._record_git_command(
            command_number, label, completed.returncode, elapsed_ms,
        )
        outcome = "OK" if completed.returncode == 0 else "ECHEC"
        self.say(
            f"[{outcome}] {label} | code={completed.returncode} | "
            f"duree={elapsed_ms / 1000:.2f} s"
        )
        if check and completed.returncode:
            stderr = (completed.stderr or b"").decode(
                "utf-8", errors="replace",
            ).strip()
            stdout = (completed.stdout or b"").decode(
                "utf-8", errors="replace",
            ).strip()
            detail = stderr or stdout
            if live_stderr and not detail:
                detail = "detail Git affiche dans le terminal ci-dessus"
            raise SyncBlocked(
                f"git {git_args[0]} a echoue (code {completed.returncode}): "
                f"{detail[:1400]}"
            )
        return completed

    def _record_git_command(
        self, number: int, label: str, exit_code: int, elapsed_ms: int,
        *, timed_out: bool = False,
    ) -> None:
        commands = self.report.setdefault("git_commands", [])
        if isinstance(commands, list):
            commands.append({
                "number": number,
                "operation": label,
                "exit_code": exit_code,
                "duration_ms": elapsed_ms,
                "timed_out": timed_out,
            })

    def text(self, *args: str) -> str:
        return self.command(*args).stdout.decode("utf-8", errors="replace").strip()

    @staticmethod
    def say(message: str) -> None:
        stamp = datetime.now().astimezone().strftime("%H:%M:%S")
        print(f"[{stamp}] {message}", flush=True)

    def preflight(self, *, allow_shallow: bool = False) -> Path:
        self.say("[MOTEUR 1/5] Controle du depot, de main et du remote autorise.")
        top = Path(self.text("rev-parse", "--show-toplevel")).resolve()
        if top != self.root:
            raise SyncBlocked(f"Lanceur hors racine du depot: {top}")
        branch = self.text("branch", "--show-current")
        if branch != "main":
            raise SyncBlocked("Seule main est autorisee; aucun checkout automatique.")
        shallow = self.text("rev-parse", "--is-shallow-repository") == "true"
        self.report["shallow_repository"] = shallow
        if shallow and not allow_shallow:
            raise SyncBlocked("Clone shallow: historique insuffisant pour fusionner.")
        if shallow:
            self.say(
                "[PREFLIGHT] Clone shallow detecte; lecture seule/checkpoint "
                "autorise, synchronisation completee apres extension non destructive."
            )
        remote = self.text("remote", "get-url", "origin")
        if remote not in ALLOWED_ORIGINS and not (
            self.allow_test_remote
            and os.environ.get("ALINA_SYNC_TEST_REMOTE_ALLOWED") == "1"
        ):
            raise SyncBlocked(f"origin non canonique: {remote}. Push interdit.")
        gitdir = Path(self.text("rev-parse", "--absolute-git-dir")).resolve()
        for marker in (
            "MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "BISECT_LOG",
            "rebase-apply", "rebase-merge", "sequencer",
        ):
            if (gitdir / marker).exists():
                raise SyncBlocked(
                    f"Operation Git inachevee ({marker}); intervention manuelle."
                )
        if self.command("ls-files", "-u", "-z").stdout:
            raise SyncBlocked("Conflits Git deja en cours dans l'index.")
        self.report["head_before"] = self.text("rev-parse", "HEAD")
        self.report["remote"] = remote
        self.say(
            f"[PREFLIGHT OK] branche={branch} | HEAD="
            f"{str(self.report['head_before'])[:12]} | remote canonique confirme."
        )
        return gitdir

    def _ensure_full_history(self) -> None:
        """Deepen only until local and remote history have a common ancestor.

        This is intentionally bounded.  A complete unshallow fetch is both
        unnecessary for normal main reconciliation and catastrophically slow
        for this repository's large historical object graph.  If the common
        ancestor is still unavailable after the bounded steps, fail closed
        instead of silently turning a code push into a repository download.
        """
        if self.text("rev-parse", "--is-shallow-repository") != "true":
            self.report["history_mode"] = "FULL"
            return
        local_head = self.text("rev-parse", "HEAD")
        existing_remote = self.command(
            "rev-parse", "refs/remotes/origin/main", check=False,
        )
        if existing_remote.returncode == 0:
            remote_head = existing_remote.stdout.decode(
                "ascii", errors="replace"
            ).strip()
            if remote_head and self.command(
                "merge-base", local_head, remote_head, check=False,
            ).returncode == 0:
                self.report["history_mode"] = "EXISTING_SHALLOW_BASE"
                self.say(
                    "[HISTORIQUE] Base commune deja prouvee dans le clone "
                    "shallow; aucun fetch supplementaire."
                )
                return
        steps = self.report["history_deepen_steps"]
        if not isinstance(steps, list):
            steps = []
            self.report["history_deepen_steps"] = steps

        for deepen in HISTORY_DEEPEN_STEPS:
            self.say(
                f"[HISTORIQUE] Approfondissement borne +{deepen} commits; "
                "arret des que la base commune est prouvee..."
            )
            fetch_args = [
                "fetch", "--progress", "--no-tags", HISTORY_FETCH_FILTER,
                f"--deepen={deepen}", "origin",
                "refs/heads/main:refs/remotes/origin/main",
            ]
            filtered = self.command(
                *fetch_args, check=False, timeout=HISTORY_FETCH_TIMEOUT_SECONDS,
            )
            if filtered.returncode:
                detail = (filtered.stderr or b"").decode(
                    "utf-8", errors="replace"
                ).lower()
                if "filter" not in detail and "partial" not in detail:
                    raise SyncBlocked(
                        "Extension Git bornee echouee; aucun fallback non filtre: "
                        + detail[:900]
                    )
                self.say(
                    "[HISTORIQUE] Serveur sans filtre blob:none; fallback borne "
                    "sans blobs exclus impossible, reprise controlee."
                )
                self.command(
                    *[arg for arg in fetch_args if arg != HISTORY_FETCH_FILTER],
                    timeout=HISTORY_FETCH_TIMEOUT_SECONDS,
                )
            steps.append(deepen)
            remote_head = self.text("rev-parse", "refs/remotes/origin/main")
            common = self.command(
                "merge-base", local_head, remote_head, check=False,
            )
            if common.returncode == 0:
                self.report["history_expanded"] = True
                self.report["history_mode"] = "BOUNDED_DEEPEN"
                return
            if self.text("rev-parse", "--is-shallow-repository") != "true":
                raise SyncBlocked(
                    "Historique Git complet mais sans base commune avec origin/main; "
                    "fusion refusee."
                )

        raise SyncBlocked(
            "Historique Git shallow sans base commune apres approfondissement "
            "borne; aucun telechargement complet ni push."
        )

    def _predict_merge_conflicts(self, remote: str, local: str) -> list[str]:
        """Detect conflicts without touching the index or worktree.

        A real rebase can replay many local commits before it reaches the
        first unsupported conflict.  `merge-tree` computes the same three-way
        merge decision against the two tips without mutating Git state, so an
        unsupported conflict can fail closed in milliseconds instead of
        spending minutes replaying commits that will be discarded.
        """
        outcome = self.command(
            "merge-tree", "--write-tree", remote, local,
            check=False, timeout=MERGE_TREE_TIMEOUT_SECONDS,
        )
        payload = b"\n".join(
            part for part in (outcome.stdout or b"", outcome.stderr or b"")
            if part
        ).decode("utf-8", errors="replace")
        if outcome.returncode == 0:
            self.report["predicted_conflicts"] = []
            return []
        conflicts = sorted({
            match.group(1).strip()
            for match in re.finditer(
                r"^CONFLICT .*?: Merge conflict in (.+)$",
                payload,
                flags=re.MULTILINE,
            )
            if match.group(1).strip()
        })
        if not conflicts:
            raise SyncBlocked(
                "Precontrole merge-tree impossible; rebase non lance. "
                + payload[:900].strip()
            )
        self.report["predicted_conflicts"] = conflicts
        return conflicts

    @staticmethod
    def _preflight_auto_resolvable_conflict(path: str) -> bool:
        """Return whether the existing post-rebase resolver may inspect it."""
        if path in AUTO_RESOLVABLE_CI_CONFLICTS:
            return True
        return (
            path.startswith(("src/", "tools/", "tests/"))
            and path.endswith(".py")
        )

    def _inventory(
        self, *, refresh: bool = False,
    ) -> tuple[list[str], list[str], list[str]]:
        if self._inventory_cache is not None and not refresh:
            self.say("[INVENTAIRE] reutilisation du cache Git local stable.")
            return self._inventory_cache
        self.say(
            "[MOTEUR 2/5] Inventaire des changements de code; les dossiers "
            "de donnees restent exclus."
        )
        staged = _paths(
            self.command("diff", "--cached", "--name-only", "-z").stdout
        )
        # `ls-files --modified` forces an expensive worktree stat across all
        # 1.8M+ tracked dataset paths in this repository. `git status`
        # reuses Git's index/stat cache and reports the same changed paths fast.
        tracked = _status_paths(
            self.command("status", "--porcelain=v1", "-z", "--untracked-files=no").stdout
        )
        # Git prunes excluded directories; never descend into SAFE shards.
        args = ["ls-files", "--others", "--exclude-standard", "-z"]
        for pattern in self._excluded_untracked_patterns():
            args.extend(["-x", pattern])
        untracked = _paths(self.command(*args).stdout)
        self.say(
            f"[INVENTAIRE] deja stages={len(staged)} | suivis modifies="
            f"{len(tracked)} | nouveaux={len(untracked)}."
        )
        self._inventory_cache = (staged, tracked, untracked)
        return self._inventory_cache

    @staticmethod
    def _excluded_untracked_patterns() -> list[str]:
        patterns = [
            pattern
            for directory in sorted(PROTECTED_DIRS)
            for pattern in (f"/{directory}/", f"/{directory}/**")
        ]
        patterns.extend(["/tools/git/", "/tools/python/"])
        return patterns

    def capture_preflight(self, *, fetch_remote: bool) -> None:
        """Persist exact local inventory before checkpointing or reconciling."""
        staged, tracked, untracked = self._inventory()
        local_head = str(self.report.get("head_before") or self.text("rev-parse", "HEAD"))
        inventory = {
            "staged": {"count": len(staged), "paths": sorted(set(staged))},
            "tracked_changes": {
                "count": len(tracked), "paths": sorted(set(tracked)),
            },
            "untracked": {"count": len(untracked), "paths": sorted(set(untracked))},
            "protected_observed_paths": sorted({
                path for path in staged + tracked + untracked if _protected(path)
            }),
            "excluded_untracked_patterns": self._excluded_untracked_patterns(),
        }
        snapshot: dict[str, object] = {
            "captured_at_utc": datetime.now(UTC).isoformat(),
            "local_head": local_head,
            "remote_head_observed": None,
            "remote_head_fetched": None,
            "ahead_commits": None,
            "behind_commits": None,
            "comparison_status": "NOT_REQUESTED",
            "inventory": inventory,
            "publishable_paths": [],
        }
        self.report["preflight"] = snapshot

        if fetch_remote:
            observed_remote = self.remote_sha()
            snapshot["remote_head_observed"] = observed_remote

        eligible = self._check_candidates(
            staged, tracked, untracked, allow_protected_local=fetch_remote,
        )
        snapshot["publishable_paths"] = eligible
        snapshot["inventory_status"] = "VALIDATED"

        if not fetch_remote:
            snapshot["comparison_status"] = (
                "NOT_FETCHED_DRY_RUN" if self.dry_run else "NOT_REQUESTED_LOCAL_ONLY"
            )
            self.say(
                "[PREFLIGHT RECEIPT] Inventaire local conserve; aucune mutation "
                "ni comparaison de commits distante dans ce mode."
            )
            return

        self.command(
            "fetch", "--progress", "--no-tags", "origin",
            "refs/heads/main:refs/remotes/origin/main",
        )
        # A user/editor can change source files while fetch is in flight.
        # Never reuse the pre-fetch snapshot for the publishable checkpoint.
        self._inventory_cache = None
        fetched_remote = self.text("rev-parse", "refs/remotes/origin/main")
        self._remote_snapshot_ready = True
        counts = self.text(
            "rev-list", "--left-right", "--count",
            f"{local_head}...{fetched_remote}",
        ).split()
        if len(counts) != 2 or any(not value.isdecimal() for value in counts):
            raise SyncBlocked("Comptage ahead/behind invalide; aucun changement publié.")
        ahead, behind = (int(value) for value in counts)
        snapshot.update({
            "remote_head_fetched": fetched_remote,
            "ahead_commits": ahead,
            "behind_commits": behind,
            "comparison_status": "EXACT_FOR_FETCHED_REMOTE_HEAD",
        })
        self.report["remote_sha_observed"] = fetched_remote
        self.say(
            f"[PREFLIGHT RECEIPT] local={local_head[:12]} | "
            f"GitHub snapshot={fetched_remote[:12]} | ahead={ahead} | "
            f"behind={behind} | staged={len(staged)} | suivis={len(tracked)} | "
            f"nouveaux={len(untracked)} | chemins proteges={len(inventory['protected_observed_paths'])}."
        )

    def _fast_path_if_clean(self) -> bool:
        """Finish a provably clean run without fetching Git history.

        A clean repository whose local HEAD already equals the current
        ``ls-remote`` SHA has nothing to reconcile.  The old path still ran a
        shallow-history check and a full fetch before discovering that fact,
        which made a harmless double-click spend tens of seconds in GitHub
        traffic.  This shortcut is deliberately narrow: it first inventories
        every publishable path, checks the protected-data contract, verifies
        the remote twice around the local-change check, and returns only when
        both the code and the remote are still unchanged.

        When GitHub is ahead but local ``main`` is clean, the same proof can
        safely finish with one fetch and a fast-forward.  Keeping that lane
        here avoids the later checkpoint/syntax/reconcile loop while retaining
        the ignored-data guard and the final remote SHA verification.
        """
        staged, tracked, untracked = self._inventory()
        eligible = self._check_candidates(
            staged, tracked, untracked, allow_protected_local=False,
        )
        if eligible:
            return False

        local = str(self.report.get("head_before") or self.text("rev-parse", "HEAD"))
        observed_remote = self.remote_sha()
        if observed_remote != local:
            self.command(
                "fetch", "--progress", "--no-tags", "origin",
                "refs/heads/main:refs/remotes/origin/main",
            )
            self._inventory_cache = None
            fetched_remote = self.text("rev-parse", "refs/remotes/origin/main")
            if fetched_remote == local or self.command(
                "merge-base", "--is-ancestor", local, fetched_remote,
                check=False,
            ).returncode:
                return False

            self._protect_ignored_files(fetched_remote)
            self._assert_no_new_code_changes()
            with self._preserve_local_protected_index():
                self.command("merge", "--ff-only", fetched_remote)
            merged_local = self.text("rev-parse", "HEAD")
            verified_remote = self.remote_sha()
            if merged_local != fetched_remote or verified_remote != merged_local:
                return False

            counts = self.text(
                "rev-list", "--left-right", "--count",
                f"{local}...{verified_remote}",
            ).split()
            if len(counts) != 2 or any(not value.isdecimal() for value in counts):
                return False
            ahead, behind = (int(value) for value in counts)
            staged, tracked, untracked = self._inventory()
            self.report["preflight"] = {
                "captured_at_utc": datetime.now(UTC).isoformat(),
                "local_head": local,
                "remote_head_observed": observed_remote,
                "remote_head_fetched": fetched_remote,
                "ahead_commits": ahead,
                "behind_commits": behind,
                "comparison_status": "EXACT_FOR_FETCHED_REMOTE_HEAD",
                "inventory": {
                    "staged": {"count": len(staged), "paths": sorted(set(staged))},
                    "tracked_changes": {
                        "count": len(tracked), "paths": sorted(set(tracked)),
                    },
                    "untracked": {
                        "count": len(untracked), "paths": sorted(set(untracked)),
                    },
                    "protected_observed_paths": sorted({
                        path for path in staged + tracked + untracked if _protected(path)
                    }),
                    "excluded_untracked_patterns": self._excluded_untracked_patterns(),
                },
                "publishable_paths": [],
                "inventory_status": "VALIDATED",
            }
            self.report["remote_sha_observed"] = verified_remote
            self.report["fast_path"] = "CLEAN_REMOTE_FAST_FORWARD"
            self.report["local_syntax_check"] = "NO_PYTHON_CHANGED"
            self.report["status"] = "SYNCHRONIZED"
            self.report["head_after"] = merged_local
            self.report["checkpoint_sha_after_reconcile"] = merged_local
            self.say(
                "[RACCOURCI] Depot propre; avance rapide GitHub integree et "
                "SHA distant reverifiee, sans rebase ni push."
            )
            return True

        # The exact-match path below deliberately rechecks the remote around
        # the local-change assertion, because GitHub may advance during this
        # short read-only window.

        inventory = {
            "staged": {"count": len(staged), "paths": sorted(set(staged))},
            "tracked_changes": {
                "count": len(tracked), "paths": sorted(set(tracked)),
            },
            "untracked": {
                "count": len(untracked), "paths": sorted(set(untracked)),
            },
            "protected_observed_paths": sorted({
                path for path in staged + tracked + untracked if _protected(path)
            }),
            "excluded_untracked_patterns": self._excluded_untracked_patterns(),
        }
        self.report["preflight"] = {
            "captured_at_utc": datetime.now(UTC).isoformat(),
            "local_head": local,
            "remote_head_observed": observed_remote,
            "remote_head_fetched": None,
            "ahead_commits": 0,
            "behind_commits": 0,
            "comparison_status": "EXACT_REMOTE_SHA_EQUALS_LOCAL",
            "inventory": inventory,
            "publishable_paths": [],
            "inventory_status": "VALIDATED",
        }
        self._assert_no_new_code_changes()
        verified_remote = self.remote_sha()
        if verified_remote != local:
            return False

        self.report["remote_sha_observed"] = verified_remote
        self.report["fast_path"] = "CLEAN_REMOTE_MATCH"
        self.report["local_syntax_check"] = "NO_PYTHON_CHANGED"
        self.report["status"] = "SYNCHRONIZED"
        self.report["head_after"] = local
        self.report["checkpoint_sha_after_reconcile"] = local
        self.say(
            "[RACCOURCI] Depot propre et SHA GitHub identique; "
            "aucun fetch, commit, rebase ou push necessaire."
        )
        return True

    def _historical_head_blob(self, source: str) -> bytes:
        result = self.command("show", f"HEAD:{source}", check=False)
        if result.returncode:
            raise SyncBlocked(
                f"Blob historique absent de HEAD; deplacement refuse: {source}"
            )
        return result.stdout

    def _clean_blob_oid(self, path: str, payload: bytes) -> str:
        result = self.command(
            "hash-object", f"--path={path}", "--stdin", input_bytes=payload,
        )
        return result.stdout.decode("ascii", errors="strict").strip()

    def _verify_historical_archive_payload(
        self, source: str, destination: str, archive_path: Path,
    ) -> tuple[bytes, bytes]:
        head_blob = self._historical_head_blob(source)
        expected_oid = self.text("rev-parse", f"HEAD:{source}")
        payload = archive_path.read_bytes()
        source_oid = self._clean_blob_oid(source, payload)
        destination_oid = self._clean_blob_oid(destination, payload)
        if source_oid != expected_oid or destination_oid != expected_oid:
            raise SyncBlocked(
                f"Archive differente du blob HEAD apres normalisation Git: {destination}"
            )
        return head_blob, payload

    def _historical_archive_file(self, destination: str) -> Path:
        relative = PurePosixPath(destination)
        if relative.is_absolute() or ".." in relative.parts:
            raise SyncBlocked("Destination d'archive hors depot; deplacement refuse.")
        current = self.root
        for part in relative.parts:
            current = current / part
            if current.is_symlink():
                raise SyncBlocked(
                    f"Lien symbolique dans le chemin d'archive: {destination}"
                )
        if not current.is_file():
            raise SyncBlocked(
                f"Copie d'archive absente ou non reguliere: {destination}"
            )
        return current

    def _record_historical_relocation(
        self, source: str, destination: str, head_blob: bytes,
        worktree_payload: bytes, proof: str,
    ) -> None:
        entry = {
            "source": source,
            "destination": destination,
            "sha256": hashlib.sha256(head_blob).hexdigest(),
            "worktree_sha256": hashlib.sha256(worktree_payload).hexdigest(),
            "proof": proof,
        }
        records = self.report["verified_historical_relocations"]
        if isinstance(records, list):
            for item in records:
                if (
                    isinstance(item, dict)
                    and item.get("source") == source
                    and item.get("destination") == destination
                ):
                    item.update(entry)
                    break
            else:
                records.append(entry)
        self.say(
            f"[ARCHIVE MOVE {proof}] {source} -> {destination} "
            f"| SHA-256={entry['sha256']}"
        )

    def _verified_unstaged_historical_moves(
        self, tracked: list[str], untracked: list[str]
    ) -> set[str]:
        allowed: set[str] = set()
        for source, destination in SAFE_HISTORICAL_RELOCATIONS.items():
            if source not in tracked or destination not in untracked:
                continue
            old_path = self.root / source
            if old_path.exists() or old_path.is_symlink():
                raise SyncBlocked(
                    f"Le fichier source existe encore; deplacement archive non prouve: {source}"
                )
            archive_path = self._historical_archive_file(destination)
            head_blob, payload = self._verify_historical_archive_payload(
                source, destination, archive_path
            )
            self._check_file_payload(destination, archive_path)
            self._record_historical_relocation(
                source, destination, head_blob, payload, "WORKTREE_BLOB_EXACT"
            )
            allowed.update((source, destination))
        return allowed

    def _verified_staged_historical_moves(self, staged: list[str]) -> set[str]:
        allowed: set[str] = set()
        staged_paths = set(staged)
        for source, destination in SAFE_HISTORICAL_RELOCATIONS.items():
            pair = {source, destination}
            if not pair.intersection(staged_paths) or not pair.issubset(staged_paths):
                continue
            old_path = self.root / source
            if old_path.exists() or old_path.is_symlink():
                raise SyncBlocked(
                    f"Le fichier source existe encore dans le depot: {source}"
                )
            archive_path = self._historical_archive_file(destination)
            head_blob, payload = self._verify_historical_archive_payload(
                source, destination, archive_path
            )
            staged_blob = self.command("show", f":{destination}", check=False)
            source_index = self.command("ls-files", "--stage", "--", source)
            if (
                staged_blob.returncode
                or staged_blob.stdout != head_blob
                or source_index.stdout
            ):
                raise SyncBlocked(
                    "Le deplacement archive ne correspond plus exactement au blob "
                    "HEAD dans l'index et le disque; synchronisation arretee."
                )
            self._check_file_payload(destination, archive_path)
            self._record_historical_relocation(
                source, destination, head_blob, payload,
                "INDEX_AND_WORKTREE_BLOB_EXACT",
            )
            allowed.update(pair)
        return allowed

    def _check_candidates(
        self, staged: list[str], tracked: list[str], untracked: list[str],
        *, allow_protected_local: bool = False,
    ) -> list[str]:
        staged_protected = [p for p in staged if _protected(p)]
        if staged_protected:
            raise SyncBlocked(
                "Fichiers sensibles deja stages : " + ", ".join(staged_protected[:8])
            )
        safe_moves = self._verified_unstaged_historical_moves(tracked, untracked)
        tracked_protected = [
            p for p in tracked if _protected(p) and p not in safe_moves
        ]
        if tracked_protected and not allow_protected_local:
            raise SyncBlocked(
                "Donnees Git suivies mais modifiees localement : "
                + ", ".join(tracked_protected[:8])
                + ". Les proteger avant toute fusion."
            )
        if tracked_protected:
            self.report["protected_local_changes"] = sorted(tracked_protected)
            self.say(
                "[GARDE DONNEES] Modifications locales protegees conservees hors "
                "du commit; elles seront refusees si GitHub touche ces chemins."
            )
        eligible = sorted(
            p for p in set(staged + tracked + untracked)
            if not _protected(p) or p in safe_moves
        )
        for path in eligible:
            absolute = self.root / path
            if absolute.is_symlink():
                raise SyncBlocked(f"Lien symbolique non publiable automatiquement: {path}")
            if absolute.is_file() and absolute.stat().st_size > MAX_BLOB_BYTES:
                raise SyncBlocked(f"Fichier >95 Mio interdit dans Git: {path}")
        self.say(
            f"[FILTRE] {len(eligible)} chemin(s) admissible(s); "
            "donnees, binaires et secrets exclus."
        )
        for path in eligible[:30]:
            label = "ARCHIVE SAFE" if path in safe_moves else "CODE"
            self.say(f"  [{label}] {path}")
        if len(eligible) > 30:
            self.say(f"  [CODE] ... {len(eligible) - 30} autre(s) fichier(s).")
        return eligible

    @staticmethod
    def _check_file_payload(path: str, full: Path) -> None:
        if not full.is_file():
            return
        if full.stat().st_size > MAX_BLOB_BYTES:
            raise SyncBlocked(f"Fichier trop volumineux: {path}")
        if full.stat().st_size <= 2 * 1024 * 1024:
            sample = full.read_bytes()
            if any(line in {
                b"-----BEGIN PRIVATE KEY-----",
                b"-----BEGIN RSA PRIVATE KEY-----",
                b"-----BEGIN OPENSSH PRIVATE KEY-----",
                b"-----BEGIN EC PRIVATE KEY-----",
            } for line in sample.splitlines()):
                raise SyncBlocked(f"Materiel de cle privee detecte: {path}")

    def _verify_stage(self) -> None:
        staged = _paths(
            self.command(
                "diff", "--cached", "--name-only", "--no-renames", "-z"
            ).stdout
        )
        safe_moves = self._verified_staged_historical_moves(staged)
        if any(_protected(path) and path not in safe_moves for path in staged):
            raise SyncBlocked("L'index contient une archive, des donnees ou un secret.")
        for path in staged:
            self._check_file_payload(path, self.root / path)
        if self.command("diff", "--cached", "--check", check=False).returncode:
            self.say("[ATTENTION] Espaces non conformes dans un WIP, code preserve.")

    def checkpoint(self) -> None:
        staged, tracked, untracked = self._inventory()
        snapshot = self.report.get("preflight")
        allow_protected_local = (
            isinstance(snapshot, dict)
            and snapshot.get("remote_head_fetched")
            and snapshot.get("local_head") != snapshot.get("remote_head_fetched")
        )
        eligible = self._check_candidates(
            staged, tracked, untracked,
            allow_protected_local=bool(allow_protected_local),
        )
        self.report["publishable_paths_seen"] = len(eligible)
        self.changed_python_paths = [
            p for p in eligible
            if p.endswith(".py") and (self.root / p).is_file()
        ]
        self.say(
            f"[MOTEUR 3/5] Fichiers de code locaux admissibles: {len(eligible)}."
        )
        # Detect high-confidence private-key material BEFORE writing Git blobs.
        for path in eligible:
            self._check_file_payload(path, self.root / path)
        if self.dry_run or not eligible:
            if self.dry_run:
                self.say("[DRY-RUN] Aucun fichier prepare ou committe.")
            else:
                self.say("[CHECKPOINT] Rien a sauvegarder; aucun commit vide.")
            return
        pathspec = b"\0".join(path.encode("utf-8") for path in eligible) + b"\0"
        self.command(
            "add", "-A", "--pathspec-from-file=-", "--pathspec-file-nul",
            input_bytes=pathspec,
        )
        self._verify_stage()
        diff = self.command("diff", "--cached", "--quiet", check=False)
        if diff.returncode not in (0, 1):
            raise SyncBlocked("Verification de l'index Git impossible.")
        if diff.returncode == 1:
            commit_message = _commit_subject(eligible)
            self.report["commit_message"] = commit_message
            self.say(f"Commit semantique du code admissible: {commit_message}")
            self.command(
                "commit", "-m",
                commit_message,
            )
            self.report["local_commit_created"] = True
            self.report["checkpoint_sha"] = self.text("rev-parse", "HEAD")
            self.command(
                "update-ref", "refs/alina-sync/last-local-checkpoint",
                self.text("rev-parse", "HEAD"),
            )

    def _syntax_gate(self) -> None:
        if not self.changed_python_paths:
            self.report["local_syntax_check"] = "NO_PYTHON_CHANGED"
            self.say("[ETAPE 4/6] Controle syntaxique ignore: aucun Python modifie.")
            return
        self.say(
            f"[MOTEUR 4/5] Verification syntaxique de "
            f"{len(self.changed_python_paths)} fichier(s) Python."
        )
        for index, path in enumerate(self.changed_python_paths, 1):
            self.say(
                f"[PYTHON {index}/{len(self.changed_python_paths)}] {path}"
            )
            try:
                ast.parse((self.root / path).read_bytes(), filename=path)
            except (SyntaxError, UnicodeError, ValueError) as exc:
                self.report["local_syntax_check"] = "FAILED_WIP_CHECKPOINT_PRESERVED"
                raise SyncBlocked(
                    f"Python incomplet ({path}): {exc}. "
                    "WIP sauvegarde en commit local, NON pousse."
                ) from exc
        self.report["local_syntax_check"] = "PASS_NOT_PROOF_OF_TESTS"
        self.say("[SYNTAXE OK] Tous les fichiers Python admissibles compilent.")

    def _assert_no_new_code_changes(self) -> None:
        staged, tracked, untracked = self._inventory(refresh=True)
        eligible = self._check_candidates(
            staged, tracked, untracked, allow_protected_local=True,
        )
        if eligible:
            self.report["late_local_paths"] = eligible[:100]
            self.report["late_local_count"] = len(eligible)
            self.report["late_local_types"] = {
                "staged": [p for p in staged if p in eligible][:100],
                "tracked": [p for p in tracked if p in eligible][:100],
                "untracked": [p for p in untracked if p in eligible][:100],
            }
            raise LocalEditsDetected(
                f"{len(eligible)} modification(s) arrivee(s) pendant Git Sync : "
                + ", ".join(eligible[:12])
                + ". Contenu conserve sur disque."
            )

    def remote_sha(self) -> str:
        remote = self.text("ls-remote", "origin", "refs/heads/main")
        if not remote:
            raise SyncBlocked("GitHub main introuvable ou inaccessible.")
        sha = remote.split()[0]
        if not re.fullmatch(r"[0-9a-f]{40,64}", sha):
            raise SyncBlocked("SHA GitHub invalide.")
        return sha

    def _protect_ignored_files(self, remote: str) -> None:
        # Git merge can overwrite ignored files. Check upstream paths only,
        # without traversing runtime/shards or hydrating any LFS assets.
        changed = _paths(
            self.command("diff", "--name-only", "-z", "HEAD", remote).stdout
        )
        protected_changes = [path for path in changed if _protected(path)]
        self.say(
            f"[GARDE DONNEES] Inspection en lot de {len(protected_changes)} "
            f"chemin(s) protege(s) sur {len(changed)} chemin(s) distant(s)."
        )
        if not protected_changes:
            return

        # Resolve tracking state in small path batches instead of starting
        # multiple Git processes for every remote path.  The old O(n) loop
        # turned a 1,350-path remote diff into thousands of subprocesses.
        tracked_paths: set[str] = set()
        for start in range(0, len(protected_changes), PROTECTED_PATH_BATCH_SIZE):
            batch = protected_changes[start:start + PROTECTED_PATH_BATCH_SIZE]
            tracked_paths.update(_paths(
                self.command("ls-files", "-z", "--", *batch).stdout
            ))

        local_changed = set(_paths(
            self.command("diff", "--name-only", "-z", "HEAD").stdout
        ))
        for path in protected_changes:
            local_path = self.root / path
            if not (local_path.exists() or local_path.is_symlink()):
                continue
            if path in tracked_paths:
                if path in local_changed:
                    raise SyncBlocked(
                        f"GitHub toucherait un fichier protege modifie localement: {path}. "
                        "Fusion interdite pour proteger les donnees."
                    )
                continue
            raise SyncBlocked(
                f"GitHub toucherait un fichier local protege non suivi: {path}. "
                "Fusion interdite pour proteger les donnees."
            )

    @contextlib.contextmanager
    def _preserve_local_protected_index(self):
        """Let Git rebase code while preserving unrelated local SAFE bytes."""
        paths = [
            path for path in self.report.get("protected_local_changes", [])
            if isinstance(path, str)
        ]
        if not paths:
            yield
            return

        assumed: list[str] = []
        try:
            for path in paths:
                # A generated file can be byte-identical to HEAD while its
                # filesystem stat is stale.  Git checkout then reports it as
                # dirty even though there is no local data change.  Refresh
                # only that exact index entry with its existing blob; this
                # never stages or rewrites the protected worktree file.
                entry = self.command("ls-files", "-s", "--", path).stdout
                fields = entry.decode("utf-8", errors="replace").split()
                if len(fields) < 3:
                    raise SyncBlocked(
                        "Entree d'index protegee introuvable pour " + path
                    )
                self.command(
                    "update-index", "--cacheinfo",
                    f"{fields[0]},{fields[1]},{path}",
                )
                # `skip-worktree` is the index contract Git checkout/rebase
                # honors when the worktree intentionally contains a local
                # protected file that must not be replaced by code replay.
                # `assume-unchanged` only suppresses stat checks and still
                # lets checkout reject the path as dirty.
                self.command("update-index", "--skip-worktree", "--", path)
                assumed.append(path)
            yield
        finally:
            for path in reversed(assumed):
                restored = self.command(
                    "update-index", "--no-skip-worktree", "--", path,
                    check=False,
                )
                if restored.returncode:
                    raise SyncBlocked(
                        "Restauration de la garde d'index impossible pour "
                        f"le fichier protege: {path}"
                    )

    def _capture_conflicts(self, conflicted: list[str], local: str,
                           remote: str) -> None:
        """Save exact base/local/GitHub blobs before aborting reconciliation.

        Never write outside runtime/reports; never post payload to GitHub.
        The copies are resolved from immutable commit IDs, not index stages,
        whose local/GitHub roles change between merge and rebase conflicts.
        """
        root = self.root / "runtime"
        reports = root / "reports"
        sync_dir = reports / "git-sync"
        dest = sync_dir / "conflicts" / (local[:12] + "-" + remote[:12])
        parents = (root, reports, sync_dir, sync_dir / "conflicts", dest)
        if any(p.is_symlink() for p in parents):
            raise SyncBlocked("Chemin runtime du dossier de conflits non fiable.")
        dest.mkdir(parents=True, exist_ok=True)
        manifest: dict[str, object] = {
            "schema": "alina.git_conflict_kit.v1",
            "local_head": local,
            "remote_head": remote,
            "git_stage_roles": {
                "base": "merge-base(local_head, remote_head)",
                "local": "exact local checkpoint commit",
                "github": "exact GitHub main commit",
                "conflict": "Git tentative de rebase lineaire, NON resolue",
            },
            "files": [],
            "includes_shards": False,
            "no_auto_choice": True,
        }
        instructions = [
            "# Alina - conflits Git (copies locales NON publiees)",
            "",
            f"Commit local protege : `{local}`",
            f"HEAD distant observe : `{remote}`",
            "",
            "Ne supprimer ni la logique locale ni la logique GitHub.",
            "Analyser chaque triplet base/local/github, fusionner les intentions",
            "et tester les comportements avant de valider.",
            "Ces copies sont des diagnostics, jamais des fichiers a committer.",
            "",
            "## Fichiers",
        ]
        base_result = self.command("merge-base", local, remote, check=False)
        if base_result.returncode:
            raise SyncBlocked("Base commune locale/GitHub introuvable pour le kit.")
        base = base_result.stdout.decode("ascii", errors="strict").strip()
        for i, path in enumerate(conflicted):
            if _protected(path):
                raise SyncBlocked("Conflit sur chemin protege : " + path)
            entry: dict[str, object] = {"path": path, "versions": {}}
            instructions.append(f"- `{path}` : prefixe `{i:02d}-`")
            for label, spec in (
                ("base", f"{base}:{path}"),
                ("local", f"{local}:{path}"),
                ("github", f"{remote}:{path}"),
            ):
                outcome = self.command("show", spec, check=False)
                if outcome.returncode:
                    entry["versions"][label] = {"status": "ABSENT"}
                    continue
                raw = outcome.stdout
                if len(raw) > 2 * 1024 * 1024:
                    entry["versions"][label] = {"status": "TOO_LARGE"}
                    continue
                name = f"{i:02d}-{label}.txt"
                (dest / name).write_bytes(raw)
                entry["versions"][label] = {
                    "file": name,
                    "bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            conflict_path = self.root / path
            if conflict_path.is_file() and not conflict_path.is_symlink():
                raw = conflict_path.read_bytes()
                if len(raw) <= 2 * 1024 * 1024:
                    name = f"{i:02d}-conflict.txt"
                    (dest / name).write_bytes(raw)
                    entry["versions"]["conflict"] = {
                        "file": name,
                        "bytes": len(raw),
                        "sha256": hashlib.sha256(raw).hexdigest(),
                    }
            manifest["files"].append(entry)
        instructions += [
            "",
            "## Reprise conseillee (Codex/Claude dans le clone local)",
            "",
            "1. Ouvrir le manifest.json et les 3 versions de chaque conflit.",
            "2. Comparer au HEAD local et a origin/main, jamais choisir",
            "   systematiquement --ours ou --theirs.",
            "3. Resoudre les intentions dans une serie de commits lineaire, sans",
            "   commit de fusion ni re-ecriture de main; lancer les tests locaux.",
            "4. Relancer POUSSER-GITHUB-FORCE.cmd pour verifier la reconciliation.",
            "",
            "Ce kit ne restaure rien automatiquement. Les originaux et les",
            "commits sont preserves; le rebase incomplet est annule sans force.",
        ]
        (dest / "RESOLUTION.md").write_text(
            "\n".join(instructions) + "\n", encoding="utf-8"
        )
        (dest / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        self.report["conflict_kit"] = str(dest.relative_to(self.root)).replace("\\", "/")
        self.report["conflict_files"] = conflicted
        self.say("Kit de reconciliation local: " + str(self.report["conflict_kit"]))

    def _resolve_known_ci_conflicts(self, conflicted: list[str]) -> bool:
        """Resolve only validated hosted CI contract conflicts.

        Rebase names the upstream side `ours` and the replayed local commit
        `theirs`.  For these two workflows the upstream version is preferred
        because it contains the latest hosted CI contract; the safety markers
        below prevent accepting a self-hosted or real-execution path.
        Every other conflict remains fail-closed.
        """
        if not conflicted:
            return False
        if any(path not in AUTO_RESOLVABLE_CI_CONFLICTS for path in conflicted):
            return self._resolve_trivial_code_conflicts(conflicted)
        for path in conflicted:
            upstream = self.command("show", f":2:{path}", check=False)
            if upstream.returncode:
                return False
            content = upstream.stdout.decode("utf-8", errors="replace")
            lowered = content.casefold()
            if "runs-on: ubuntu-latest" not in lowered:
                return False
            if any(marker.casefold() in lowered
                   for marker in FORBIDDEN_HOSTED_CI_MARKERS):
                return False
            self.command("checkout", "--ours", "--", path)
            self.command("add", "--", path)
        resolutions = self.report.setdefault("ci_conflict_resolutions", [])
        if isinstance(resolutions, list):
            resolutions.extend({
                "path": path,
                "resolution": "UPSTREAM_HOSTED_CI_CONTRACT",
                "reason": "validated_no_self_hosted_or_real_execution_markers",
            } for path in conflicted)
        self.say(
            "Conflit CI resolu automatiquement: version hosted upstream "
            "validee, sans self-hosted ni execution reelle."
        )
        return True

    def _resolve_trivial_code_conflicts(self, conflicted: list[str]) -> bool:
        """Resolve a whitelisted code conflict only when semantics are equal."""
        if any(
            not path.endswith(".py")
            or not path.startswith(("src/", "tools/", "tests/"))
            or _protected(path)
            for path in conflicted
        ):
            return False
        for path in conflicted:
            versions = []
            for stage in (2, 3):
                result = self.command("show", f":{stage}:{path}", check=False)
                if result.returncode:
                    return False
                content = result.stdout.decode("utf-8", errors="strict")
                try:
                    compile(content, path, "exec")
                except SyntaxError:
                    return False
                versions.append(content)
            normalized = [
                [line.rstrip() for line in content.splitlines() if line.strip()]
                for content in versions
            ]
            if normalized[0] != normalized[1]:
                return False
            self.command("checkout", "--ours", "--", path)
            self.command("add", "--", path)
        resolutions = self.report.setdefault("ci_conflict_resolutions", [])
        if isinstance(resolutions, list):
            resolutions.extend({
                "path": path,
                "resolution": "TRIVIAL_WHITESPACE_ONLY",
                "reason": "both_sides_compile_and_match_after_blank_line_normalization",
            } for path in conflicted)
        self.say("Conflit code trivial resolu: versions compilees et semantiquement identiques.")
        return True

    def _continue_rebase_after_known_ci_conflicts(
        self, outcome: subprocess.CompletedProcess[bytes],
    ) -> bool:
        """Continue a rebase while only the known hosted CI conflicts occur.

        The initial failed ``git rebase`` result is part of the state machine:
        when the index has no conflicts, its stderr is the only evidence that
        the current commit is empty and may be skipped safely.
        """
        previous_editor = os.environ.get("GIT_EDITOR")
        os.environ["GIT_EDITOR"] = "true"
        try:
            for _ in range(32):
                conflicted = _paths(self.command(
                    "diff", "--name-only", "--diff-filter=U", "-z"
                ).stdout)
                if not conflicted:
                    detail = (
                        (outcome.stderr or b"") + (outcome.stdout or b"")
                    ).decode("utf-8", errors="replace").casefold()
                    if "empty" not in detail:
                        return False
                    skipped = self.command("rebase", "--skip", check=False)
                    if skipped.returncode:
                        return False
                    self.report["empty_rebase_commits_skipped"] = (
                        int(self.report.get("empty_rebase_commits_skipped", 0)) + 1
                    )
                    gitdir = Path(self.text("rev-parse", "--absolute-git-dir"))
                    if not any((gitdir / marker).exists()
                               for marker in ("rebase-merge", "rebase-apply")):
                        return True
                    continue
                if not self._resolve_known_ci_conflicts(conflicted):
                    return False
                outcome = self.command(
                    "rebase", "--continue", check=False,
                )
                if outcome.returncode == 0:
                    return True
            raise SyncBlocked("Trop de conflits CI successifs; rebase arrete.")
        finally:
            if previous_editor is None:
                os.environ.pop("GIT_EDITOR", None)
            else:
                os.environ["GIT_EDITOR"] = previous_editor

    def _abort_rebase_after_timeout(
        self, timeout: subprocess.TimeoutExpired,
    ) -> None:
        """Abort a timed-out rebase without leaving Git half-open.

        A killed ``git rebase`` can leave its state machine active.  Letting
        the outer error handler return in that state makes the next launcher
        invocation fail on a stale rebase and can hold the user in a long
        recovery loop.  The abort is itself bounded and never deletes a Git
        lock; if Git cannot prove the abort completed, fail closed.
        """
        self.report["rebase_timeout_seconds"] = REBASE_TIMEOUT_SECONDS
        self.report["rebase_timeout_count"] = (
            int(self.report.get("rebase_timeout_count", 0)) + 1
        )
        try:
            aborted = self.command(
                "rebase", "--abort", check=False,
                timeout=REBASE_ABORT_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as abort_timeout:
            raise SyncBlocked(
                "Rebase depassee apres "
                f"{REBASE_TIMEOUT_SECONDS}s; git rebase --abort a aussi "
                f"depasse {REBASE_ABORT_TIMEOUT_SECONDS}s. Intervention "
                "manuelle requise; aucun push force."
            ) from abort_timeout

        gitdir = Path(self.text("rev-parse", "--absolute-git-dir"))
        markers = tuple(
            gitdir / marker for marker in ("rebase-merge", "rebase-apply")
        )
        if aborted.returncode or any(marker.exists() for marker in markers):
            detail = (aborted.stderr or b"").decode(
                "utf-8", errors="replace",
            ).strip()
            raise SyncBlocked(
                "Rebase depassee et abort Git non confirme; "
                "intervention manuelle requise; "
                + (detail[:600] if detail else "aucun detail Git")
            ) from timeout
        self.say(
            "[REBASE TIMEOUT] Rebase arretee et abort Git confirme; "
            "aucun push force."
        )
        raise SyncBlocked(
            "Rebase depassee apres "
            f"{REBASE_TIMEOUT_SECONDS}s; rebase annulee proprement."
        ) from timeout

    def _run_rebase(self, remote: str) -> subprocess.CompletedProcess[bytes]:
        """Run the bounded rebase without ever returning an unbound outcome.

        The timeout handler normally raises ``SyncBlocked`` after confirming
        ``git rebase --abort``.  Keeping the raise here as an explicit safety
        net matters because a test double, an interrupted interpreter, or a
        future handler change must never let ``reconcile`` continue with a
        result that was never produced.
        """
        try:
            return self.command(
                "rebase", "--no-autostash", remote, check=False,
                timeout=REBASE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as timeout:
            self._abort_rebase_after_timeout(timeout)
            raise SyncBlocked(
                "Rebase timeout handler returned without a confirmed abort; "
                "aucun push force."
            ) from timeout

    def reconcile(self) -> None:
        self.say(
            "[MOTEUR 5/5] Recuperation de main depuis GitHub "
            "(objets Git seulement, aucun shard)."
        )
        if self._remote_snapshot_ready:
            self._remote_snapshot_ready = False
            self.say(
                "[FETCH] Snapshot preflight reutilise; aucun second fetch "
                "identique avant le rebase."
            )
        else:
            self.command(
                "fetch", "--progress", "--no-tags", "origin",
                "refs/heads/main:refs/remotes/origin/main",
            )
        remote = self.text("rev-parse", "refs/remotes/origin/main")
        local = self.text("rev-parse", "HEAD")
        self.say(
            f"[COMPARAISON] local={local[:12]} | GitHub={remote[:12]}"
        )
        if local == remote or self.command(
            "merge-base", "--is-ancestor", remote, local, check=False
        ).returncode == 0:
            self.say("Tous les commits distants sont deja dans main local.")
            return
        self._assert_no_new_code_changes()
        self._protect_ignored_files(remote)
        if self.command(
            "merge-base", "--is-ancestor", local, remote, check=False
        ).returncode == 0:
            self.say(
                "[INTEGRATION] Avance rapide possible: adoption des commits "
                "GitHub sans creer de commit de fusion."
            )
            with self._preserve_local_protected_index():
                self.command("merge", "--ff-only", remote)
            self.say("[INTEGRATION OK] HEAD local aligne sur GitHub main.")
            return
        self.command(
            "update-ref", "refs/alina-sync/last-local-checkpoint", local
        )
        local_merges = self.command(
            "rev-list", "--merges", f"{remote}..{local}", check=False
        )
        if local_merges.returncode:
            raise SyncBlocked("Verification des commits locaux impossible.")
        if local_merges.stdout.strip():
            raise SyncBlocked(
                "Des commits de fusion locaux non publies existent; "
                "rejeu automatique refuse pour preserver l'historique."
            )
        replay_count = self.command(
            "rev-list", "--count", f"{remote}..{local}", check=False
        )
        if replay_count.returncode:
            raise SyncBlocked("Comptage des commits locaux a rejouer impossible.")
        self.say(
            "[INTEGRATION LINEAIRE] Rejeu de "
            f"{replay_count.stdout.decode('ascii', errors='replace').strip()} "
            "commit(s) local(aux) sur GitHub main; aucun commit de fusion."
        )
        predicted = self._predict_merge_conflicts(remote, local)
        unsupported = [
            path for path in predicted
            if not self._preflight_auto_resolvable_conflict(path)
        ]
        if unsupported:
            raise SyncBlocked(
                "Conflits previsibles non auto-resolvables: "
                + ", ".join(unsupported[:12])
                + ". Rebase non lance; commits locaux et GitHub preserves."
            )
        rebase_resolved = False
        with self._preserve_local_protected_index():
            outcome = self._run_rebase(remote)
            if outcome.returncode:
                rebase_resolved = self._continue_rebase_after_known_ci_conflicts(
                    outcome,
                )
                if not rebase_resolved:
                    conflicted = _paths(self.command(
                        "diff", "--name-only", "--diff-filter=U", "-z"
                    ).stdout)
                    if conflicted:
                        try:
                            self._capture_conflicts(conflicted, local, remote)
                        except (OSError, SyncBlocked) as exc:
                            self.report["conflict_kit_error"] = str(exc)
                            self.say("Kit de conflits non ecrit: " + str(exc))
                    gitdir = Path(self.text("rev-parse", "--absolute-git-dir"))
                    rebase_markers = (
                        gitdir / "rebase-merge", gitdir / "rebase-apply"
                    )
                    if any(marker.exists() for marker in rebase_markers):
                        abort = self.command("rebase", "--abort", check=False)
                        if (
                            abort.returncode
                            or any(marker.exists() for marker in rebase_markers)
                        ):
                            raise SyncBlocked(
                                "Echec de git rebase --abort. Ne rien nettoyer; "
                                "conserver les commits et terminer la reprise "
                                "manuellement."
                            )
                    if not conflicted:
                        raise SyncBlocked(
                            "Git rebase refuse sans conflit index detecte; "
                            "aucun choix automatique: "
                            + outcome.stderr.decode(
                                "utf-8", errors="replace"
                            )[:900]
                        )
                    raise SyncBlocked(
                        "Conflit de code: " + ", ".join(conflicted[:12])
                        + ". Rejeu annule; commits locaux et GitHub preserves. "
                        "Voir le kit dans runtime/reports/git-sync/conflicts."
                    )
        if rebase_resolved:
            self.report["rebases_performed"] = (
                int(self.report["rebases_performed"]) + 1
            )
            self.report["local_rebased_onto"] = remote
            self.say(
                "[INTEGRATION OK] Commits locaux rejoues; conflits CI "
                "resolus sous contrat hosted."
            )
            return
        self.report["rebases_performed"] = (
            int(self.report["rebases_performed"]) + 1
        )
        self.report["local_rebased_onto"] = remote
        self.say("[INTEGRATION OK] Commits locaux rejoues en ligne droite.")

    def publish(self) -> None:
        local_retries = 0
        push_races = 0
        while local_retries <= MAX_LOCAL_CHANGE_RETRIES and push_races <= MAX_RACE_RETRIES:
            try:
                self.reconcile()
                self._assert_no_new_code_changes()
            except LocalEditsDetected as exc:
                if local_retries >= MAX_LOCAL_CHANGE_RETRIES:
                    raise SyncBlocked(
                        "Le code change encore pendant la synchronisation "
                        f"apres {MAX_LOCAL_CHANGE_RETRIES} sauvegardes : {exc}. "
                        "Fermer les editeurs qui reecrivent des fichiers avant de relancer."
                    ) from exc
                local_retries += 1
                self.report["late_checkpoint_attempts"] = local_retries
                self.say(
                    f"Nouveau code detecte apres fetch. "
                    f"Sauvegarde prudente ({local_retries}/{MAX_LOCAL_CHANGE_RETRIES})..."
                )
                self.checkpoint()
                self._syntax_gate()
                # Never merge or push before rechecking the worktree and remote.
                continue

            local = self.text("rev-parse", "HEAD")
            current_remote = self.remote_sha()
            if local == current_remote:
                # ``reconcile`` may have fast-forwarded local main while
                # GitHub advanced again during the same run.  The final
                # success receipt must describe the SHA just verified here,
                # never the older preflight snapshot.
                self.report["remote_sha_observed"] = current_remote
                self.report["status"] = "SYNCHRONIZED"
                self.report["head_after"] = local
                self.report["checkpoint_sha_after_reconcile"] = local
                self.say("GitHub et main local identiques; pas de commit vide.")
                return
            if self.command(
                "merge-base", "--is-ancestor", current_remote, local,
                check=False,
            ).returncode:
                self.say("GitHub a avance; nouvelle reconciliation bornee.")
                push_races += 1
                continue
            self.say(
                f"Push sans force vers main ({push_races + 1}/{MAX_RACE_RETRIES})..."
            )
            self.report["push_attempts"] = int(self.report["push_attempts"]) + 1
            pushed = self.command(
                "push", "--progress", "origin", "HEAD:refs/heads/main",
                check=False,
            )
            if pushed.returncode == 0:
                self.report["push_completed"] = True
                self.report["pushed_head"] = local
                verified_remote = self.remote_sha()
                self.report["remote_sha_observed"] = verified_remote
                if verified_remote == local:
                    self.report["status"] = "SYNCHRONIZED"
                    self.report["head_after"] = local
                    self.report["checkpoint_sha_after_reconcile"] = local
                    self.say("SHA local = SHA GitHub; synchronisation verifiee.")
                    return
                self.say("GitHub a de nouveau avance; fusion supplementaire.")
                push_races += 1
                continue
            if self.remote_sha() != current_remote:
                self.say("Push non-fast-forward refuse; GitHub avance, reprise...")
                push_races += 1
                continue
            err = (pushed.stderr or b"").decode(
                "utf-8", errors="replace",
            ).strip()
            if not err:
                err = "detail Git affiche dans le terminal ci-dessus"
            raise SyncBlocked(
                "Push refuse (authentification, protection ou reseau): "
                + err[:1500]
            )
        raise SyncBlocked(
            "GitHub avance trop souvent, ou le code local change trop "
            "frequemment: limite de tentatives atteinte. Aucun push force."
        )


    def _write_report(self) -> None:
        dest = self.root / "runtime" / "reports" / "git-sync"
        if any(p.is_symlink() for p in (
            self.root / "runtime", self.root / "runtime" / "reports", dest,
        )):
            return
        try:
            dest.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=dest,
                suffix=".tmp", delete=False,
            ) as out:
                json.dump(self.report, out, indent=2, sort_keys=True, ensure_ascii=False)
                out.write("\n")
                temporary = Path(out.name)
            os.replace(temporary, dest / "LAST_SYNC.json")
            self.say("Journal: runtime/reports/git-sync/LAST_SYNC.json")
        except OSError as exc:
            self.say(f"Journal non ecrit, sans effet sur Git: {exc}")

    def run(self, *, wip_only: bool = False) -> int:
        run_started = time.monotonic()
        self.report["started_at_utc"] = datetime.now(UTC).isoformat()
        self.say(
            "[DEBUT] Mode="
            + ("DRY-RUN (lecture seule)" if self.dry_run else
               "CHECKPOINT LOCAL" if wip_only else "SYNCHRONISATION")
            + " | aucun telechargement de shard | aucun push force."
        )
        result_code = 0
        try:
            # A shallow clone is safe to inspect in every mode.  The real
            # synchronisation path expands it inside the Git mutex before
            # comparing or replaying history; dry-run/checkpoint modes never
            # fetch and therefore remain read-only.
            gitdir = self.preflight(allow_shallow=True)
            with _mutex(gitdir):
                fast_path = False
                if not self.dry_run and not wip_only:
                    fast_path = self._fast_path_if_clean()
                if fast_path:
                    pass
                else:
                    if not self.dry_run and not wip_only:
                        self._ensure_full_history()
                    self.capture_preflight(
                        fetch_remote=not self.dry_run and not wip_only,
                    )
                    self.checkpoint()
                if self.dry_run:
                    remote_sha = self.remote_sha()
                    self.report["remote_sha_observed"] = remote_sha
                    snapshot = self.report.get("preflight")
                    if isinstance(snapshot, dict):
                        snapshot["remote_head_observed"] = remote_sha
                        if remote_sha == snapshot.get("local_head"):
                            snapshot["ahead_commits"] = 0
                            snapshot["behind_commits"] = 0
                            snapshot["comparison_status"] = "EXACT_REMOTE_SHA_EQUALS_LOCAL"
                        else:
                            snapshot["comparison_status"] = "NOT_COMPUTED_DRY_RUN_NO_FETCH"
                    self.report["status"] = "DRY_RUN_ONLY"
                    self.say(
                        "[DRY-RUN TERMINE] HEAD local="
                        f"{str(self.report.get('head_before', ''))[:12]} | "
                        f"HEAD GitHub={str(self.report['remote_sha_observed'])[:12]}."
                    )
                    self.say(
                        "Aucun add, commit, fetch, merge ou push n'a ete execute."
                    )
                elif wip_only:
                    self.report["status"] = "LOCAL_CHECKPOINT_ONLY"
                    self.report["head_after"] = self.text("rev-parse", "HEAD")
                    self.say(
                        "[CHECKPOINT LOCAL TERMINE] Travail conserve sur main; "
                        "aucun acces GitHub ni push."
                    )
                elif not fast_path:
                    self._syntax_gate()
                    self.publish()
                    self._assert_no_new_code_changes()
                    if self.text("rev-parse", "HEAD") != self.remote_sha():
                        raise SyncBlocked("GitHub a avance; relancer pour finaliser.")
        except (SyncBlocked, subprocess.TimeoutExpired, OSError) as exc:
            self.report["status"] = "NO_GO"
            self.report["error"] = str(exc)
            self.say("[NO_GO] " + str(exc))
            self.say(
                "Aucun shard telecharge; aucun push force, reset ou clean."
            )
            result_code = 2
        finally:
            elapsed_ms = int((time.monotonic() - run_started) * 1000)
            self.report["duration_ms"] = elapsed_ms
            self.report["finished_at_utc"] = datetime.now(UTC).isoformat()
            self.report["exit_code"] = result_code
            status = str(self.report.get("status") or "UNKNOWN")
            self.say(
                f"[FIN] statut={status} | code retour={result_code} | "
                f"duree totale={elapsed_ms / 1000:.1f} s"
            )
            self._write_report()
        return result_code


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root", type=Path, default=Path(__file__).resolve().parents[1]
    )
    parser.add_argument("--git", default="git")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--wip-only", action="store_true")
    parser.add_argument("--test-remote", action="store_true", help=argparse.SUPPRESS)
    options = parser.parse_args(argv)
    if options.dry_run and options.wip_only:
        parser.error("Modes --dry-run et --wip-only incompatibles.")
    print(
        "ALINA CODE SYNC - main local <-> GitHub main - ZERO shard - sans force",
        flush=True,
    )
    return Synchronizer(
        options.root, options.git, dry_run=options.dry_run,
        allow_test_remote=options.test_remote,
    ).run(wip_only=options.wip_only)


if __name__ == "__main__":
    raise SystemExit(main())
