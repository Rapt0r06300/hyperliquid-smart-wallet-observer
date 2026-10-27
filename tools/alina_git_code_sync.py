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
    "runtime", "logs", "data", "datasets", "archive", "archives",
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
GIT_SYNC_ENGINE_BUILD = "2026-10-27-linear-safe-relocation-v3"
# A single historical registry was moved out of the repository root. It is
# publishable only when both paths clean to its exact current HEAD blob.
SAFE_HISTORICAL_RELOCATIONS = {
    "CLAUDE_TASKS.jsonl": "docs/archive/root-history/CLAUDE_TASKS.jsonl",
}


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
            process.kill()
            stdout, stderr = process.communicate()
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
        self._command_count = 0
        self.report: dict[str, object] = {
            "schema": "alina.git_code_reconciliation.v1",
            "mode": "DRY_RUN" if dry_run else "SYNC",
            "status": "NOT_STARTED",
            "shard_downloads": False,
            "force_push": False,
            "reset_or_clean": False,
            "local_commit_created": False,
            "merge_commits_created": 0,
            "rebases_performed": 0,
            "push_attempts": 0,
            "local_syntax_check": "NOT_RUN",
            "verified_historical_relocations": [],
            "git_commands": [],
        }

    def command(self, *args: str, input_bytes: bytes | None = None,
                check: bool = True) -> subprocess.CompletedProcess[bytes]:
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

    def preflight(self) -> Path:
        self.say("[MOTEUR 1/5] Controle du depot, de main et du remote autorise.")
        top = Path(self.text("rev-parse", "--show-toplevel")).resolve()
        if top != self.root:
            raise SyncBlocked(f"Lanceur hors racine du depot: {top}")
        branch = self.text("branch", "--show-current")
        if branch != "main":
            raise SyncBlocked("Seule main est autorisee; aucun checkout automatique.")
        if self.text("rev-parse", "--is-shallow-repository") == "true":
            raise SyncBlocked("Clone shallow: historique insuffisant pour fusionner.")
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

    def _inventory(self) -> tuple[list[str], list[str], list[str]]:
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
        return staged, tracked, untracked

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

        eligible = self._check_candidates(staged, tracked, untracked)
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
        fetched_remote = self.text("rev-parse", "refs/remotes/origin/main")
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
        self.say(
            f"[PREFLIGHT RECEIPT] local={local_head[:12]} | "
            f"GitHub snapshot={fetched_remote[:12]} | ahead={ahead} | "
            f"behind={behind} | staged={len(staged)} | suivis={len(tracked)} | "
            f"nouveaux={len(untracked)} | chemins proteges={len(inventory['protected_observed_paths'])}."
        )

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
        self, staged: list[str], tracked: list[str], untracked: list[str]
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
        if tracked_protected:
            raise SyncBlocked(
                "Donnees Git suivies mais modifiees localement : "
                + ", ".join(tracked_protected[:8])
                + ". Les proteger avant toute fusion."
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
        eligible = self._check_candidates(staged, tracked, untracked)
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
            self.say("Commit de sauvegarde du code Codex/Claude (WIP inclus)...")
            self.command(
                "commit", "-m",
                "chore(local-sync): sauvegarde des modifications Codex Claude WIP",
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
        staged, tracked, untracked = self._inventory()
        eligible = self._check_candidates(staged, tracked, untracked)
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
        self.say(
            f"[GARDE DONNEES] Inspection de {len(changed)} chemin(s) distant(s) "
            "susceptibles d'affecter des fichiers locaux proteges."
        )
        for path in changed:
            if not _protected(path):
                continue
            local_path = self.root / path
            if not (local_path.exists() or local_path.is_symlink()):
                continue
            if self.command(
                "ls-files", "--error-unmatch", "--", path, check=False
            ).returncode:
                raise SyncBlocked(
                    f"GitHub toucherait un fichier local protege non suivi: {path}. "
                    "Fusion interdite pour proteger les donnees."
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

    def reconcile(self) -> None:
        self.say(
            "[MOTEUR 5/5] Recuperation de main depuis GitHub "
            "(objets Git seulement, aucun shard)."
        )
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
        outcome = self.command(
            "rebase", "--no-autostash", remote, check=False
        )
        if outcome.returncode:
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
            rebase_markers = (gitdir / "rebase-merge", gitdir / "rebase-apply")
            if any(marker.exists() for marker in rebase_markers):
                abort = self.command("rebase", "--abort", check=False)
                if abort.returncode or any(marker.exists() for marker in rebase_markers):
                    raise SyncBlocked(
                        "Echec de git rebase --abort. Ne rien nettoyer; "
                        "conserver les commits et terminer la reprise manuellement."
                    )
            if not conflicted:
                raise SyncBlocked(
                    "Git rebase refuse sans conflit index detecte; aucun choix "
                    "automatique: "
                    + outcome.stderr.decode("utf-8", errors="replace")[:900]
                )
            raise SyncBlocked(
                "Conflit de code: " + ", ".join(conflicted[:12])
                + ". Rejeu annule; commits locaux et GitHub preserves. "
                "Voir le kit dans runtime/reports/git-sync/conflicts."
            )
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
                self.report["status"] = "SYNCHRONIZED"
                self.report["head_after"] = local
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
                if self.remote_sha() == local:
                    self.report["status"] = "SYNCHRONIZED"
                    self.report["head_after"] = local
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
            gitdir = self.preflight()
            with _mutex(gitdir):
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
                else:
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
