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
import json
import os
import re
import subprocess
import tempfile
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


class SyncBlocked(RuntimeError):
    """Unsafe to proceed while preserving local and remote history."""


def _paths(data: bytes) -> list[str]:
    if not data:
        return []
    if not data.endswith(b"\0"):
        raise SyncBlocked("Sortie Git NUL tronquee; inventaire abandonne.")
    try:
        return [name.decode("utf-8") for name in data[:-1].split(b"\0") if name]
    except UnicodeDecodeError as exc:
        raise SyncBlocked("Nom Git non UTF-8, selection automatique refusee.") from exc


def _protected(path: str) -> bool:
    normalized = path.replace("\\", "/")
    parts = PurePosixPath(normalized).parts
    if not parts or normalized.startswith("/") or ".." in parts:
        return True
    lower = tuple(part.casefold() for part in parts)
    if any(part in PROTECTED_DIRS or part in SENSITIVE_PARTS for part in lower[:-1]):
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


def _run_git(root: Path, git: str, args: list[str], *,
             input_bytes: bytes | None = None, check: bool = True,
             timeout: int = 300) -> subprocess.CompletedProcess[bytes]:
    env = dict(os.environ)
    env["GIT_LFS_SKIP_SMUDGE"] = "1"
    env["GIT_OPTIONAL_LOCKS"] = (
        "0" if args and args[0] in {"ls-files", "status", "diff"} else "1"
    )
    completed = subprocess.run(
        [git, *args], cwd=root, input=input_bytes, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, env=env, timeout=timeout, check=False,
    )
    if check and completed.returncode:
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        stdout = completed.stdout.decode("utf-8", errors="replace").strip()
        raise SyncBlocked(
            f"git {args[0]} a echoue (code {completed.returncode}): "
            f"{(stderr or stdout)[:1400]}"
        )
    return completed


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
        self.report: dict[str, object] = {
            "schema": "alina.git_code_reconciliation.v1",
            "mode": "DRY_RUN" if dry_run else "SYNC",
            "status": "NOT_STARTED",
            "shard_downloads": False,
            "force_push": False,
            "reset_or_clean": False,
            "local_commit_created": False,
            "merge_commits_created": 0,
            "push_attempts": 0,
            "local_syntax_check": "NOT_RUN",
        }

    def command(self, *args: str, input_bytes: bytes | None = None,
                check: bool = True) -> subprocess.CompletedProcess[bytes]:
        return _run_git(
            self.root, self.git, list(args), input_bytes=input_bytes, check=check
        )

    def text(self, *args: str) -> str:
        return self.command(*args).stdout.decode("utf-8", errors="replace").strip()

    @staticmethod
    def say(message: str) -> None:
        print("  " + message, flush=True)

    def preflight(self) -> Path:
        top = Path(self.text("rev-parse", "--show-toplevel")).resolve()
        if top != self.root:
            raise SyncBlocked(f"Lanceur hors racine du depot: {top}")
        if self.text("branch", "--show-current") != "main":
            raise SyncBlocked("Seule main est autorisee; aucun checkout automatique.")
        if self.text("rev-parse", "--is-shallow-repository") == "true":
            raise SyncBlocked("Clone shallow: historique insuffisant pour fusionner.")
        remote = self.text("remote", "get-url", "origin")
        if remote not in ALLOWED_ORIGINS:
            if not (
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
        return gitdir

    def _inventory(self) -> tuple[list[str], list[str], list[str]]:
        staged = _paths(
            self.command("diff", "--cached", "--name-only", "-z").stdout
        )
        tracked = _paths(
            self.command("ls-files", "--modified", "--deleted", "-z").stdout
        )
        # Git prunes excluded directories; never descend into SAFE shards.
        args = ["ls-files", "--others", "--exclude-standard", "-z"]
        for directory in sorted(PROTECTED_DIRS):
            args.extend(["-x", f"{directory}/", "-x", f"{directory}/**"])
        untracked = _paths(self.command(*args).stdout)
        return staged, tracked, untracked

    def _check_candidates(
        self, staged: list[str], tracked: list[str], untracked: list[str]
    ) -> list[str]:
        staged_protected = [p for p in staged if _protected(p)]
        if staged_protected:
            raise SyncBlocked(
                "Fichiers sensibles deja stages : " + ", ".join(staged_protected[:8])
            )
        tracked_protected = [p for p in tracked if _protected(p)]
        if tracked_protected:
            raise SyncBlocked(
                "Donnees Git suivies mais modifiees localement : "
                + ", ".join(tracked_protected[:8])
                + ". Les proteger avant toute fusion."
            )
        eligible = sorted(
            p for p in set(staged + tracked + untracked) if not _protected(p)
        )
        for path in eligible:
            absolute = self.root / path
            if absolute.is_symlink():
                raise SyncBlocked(f"Lien symbolique non publiable automatiquement: {path}")
            if absolute.is_file() and absolute.stat().st_size > MAX_BLOB_BYTES:
                raise SyncBlocked(f"Fichier >95 Mio interdit dans Git: {path}")
        return eligible

    def _verify_stage(self) -> None:
        staged = _paths(
            self.command("diff", "--cached", "--name-only", "-z").stdout
        )
        if any(_protected(path) for path in staged):
            raise SyncBlocked("L'index contient une archive, des donnees ou un secret.")
        for path in staged:
            full = self.root / path
            if not full.is_file():
                continue
            if full.stat().st_size > MAX_BLOB_BYTES:
                raise SyncBlocked(f"Fichier trop volumineux: {path}")
            if full.stat().st_size <= 2 * 1024 * 1024:
                sample = full.read_bytes()
                if re.search(
                    rb"(?m)^-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----\\r?$",
                    sample,
                ):
                    raise SyncBlocked(f"Materiel de cle privee detecte: {path}")
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
        self.say(f"Fichiers de code locaux a sauvegarder: {len(eligible)}")
        if self.dry_run or not eligible:
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
            return
        for path in self.changed_python_paths:
            try:
                ast.parse((self.root / path).read_bytes(), filename=path)
            except (SyntaxError, UnicodeError, ValueError) as exc:
                self.report["local_syntax_check"] = "FAILED_WIP_CHECKPOINT_PRESERVED"
                raise SyncBlocked(
                    f"Python incomplet ({path}): {exc}. "
                    "WIP sauvegarde en commit local, NON pousse."
                ) from exc
        self.report["local_syntax_check"] = "PASS_NOT_PROOF_OF_TESTS"

    def _assert_no_new_code_changes(self) -> None:
        staged, tracked, untracked = self._inventory()
        eligible = self._check_candidates(staged, tracked, untracked)
        if eligible:
            raise SyncBlocked(
                "Nouvelles modifications Codex/Claude detectees pendant le sync. "
                "Aucune n'est ecrasee; relancer pour les sauvegarder."
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

    def reconcile(self) -> None:
        self.say("Git fetch origin/main : objets Git seulement, jamais AlinaSync...")
        self.command(
            "fetch", "--no-tags", "origin",
            "refs/heads/main:refs/remotes/origin/main",
        )
        remote = self.text("rev-parse", "refs/remotes/origin/main")
        local = self.text("rev-parse", "HEAD")
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
            self.say("Fast-forward : adoption des nouveaux commits GitHub.")
            self.command("merge", "--ff-only", remote)
            return
        self.command(
            "update-ref", "refs/alina-sync/last-local-checkpoint", local
        )
        self.say("Fusion trois-voies du travail local et de GitHub...")
        outcome = self.command(
            "merge", "--no-edit", "--no-ff", remote, check=False
        )
        if outcome.returncode:
            conflicted = _paths(self.command(
                "diff", "--name-only", "--diff-filter=U", "-z"
            ).stdout)
            if self.command("merge", "--abort", check=False).returncode:
                raise SyncBlocked(
                    "Conflit et echec de merge --abort. Intervention manuelle: "
                    + ", ".join(conflicted[:12])
                )
            raise SyncBlocked(
                "Conflit de code: " + ", ".join(conflicted[:12])
                + ". Fusion annulee; deux historiques intacts. "
                "Inspecter avec Codex/Claude avant de relancer."
            )
        self.report["merge_commits_created"] = (
            int(self.report["merge_commits_created"]) + 1
        )

    def publish(self) -> None:
        for attempt in range(1, MAX_RACE_RETRIES + 1):
            self.reconcile()
            self._assert_no_new_code_changes()
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
                continue
            self.say(
                f"Push sans force vers main ({attempt}/{MAX_RACE_RETRIES})..."
            )
            self.report["push_attempts"] = int(self.report["push_attempts"]) + 1
            pushed = self.command(
                "push", "origin", "HEAD:refs/heads/main", check=False
            )
            if pushed.returncode == 0:
                if self.remote_sha() == local:
                    self.report["status"] = "SYNCHRONIZED"
                    self.report["head_after"] = local
                    self.say("SHA local = SHA GitHub; synchronisation verifiee.")
                    return
                self.say("GitHub a de nouveau avance; fusion supplementaire.")
                continue
            if self.remote_sha() != current_remote:
                self.say("Push non-fast-forward refuse; GitHub avance, reprise...")
                continue
            err = pushed.stderr.decode("utf-8", errors="replace").strip()
            raise SyncBlocked(
                "Push refuse (authentification, protection ou reseau): "
                + err[:1500]
            )
        raise SyncBlocked(
            "GitHub avance trop souvent: 5 tentatives sans force ni perte."
        )

    def _write_report(self) -> None:
        dest = self.root / "runtime" / "reports" / "git-sync"
        if dest.is_symlink():
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
        try:
            gitdir = self.preflight()
            with _mutex(gitdir):
                self.checkpoint()
                if self.dry_run:
                    self.report["remote_sha_observed"] = self.remote_sha()
                    self.report["status"] = "DRY_RUN_ONLY"
                    self.say("Dry-run: aucun add, commit, fetch, merge ou push.")
                elif wip_only:
                    self.report["status"] = "LOCAL_CHECKPOINT_ONLY"
                    self.report["head_after"] = self.text("rev-parse", "HEAD")
                    self.say("Commit WIP local seulement, aucun acces GitHub.")
                else:
                    self._syntax_gate()
                    self.publish()
                    self._assert_no_new_code_changes()
                    if self.text("rev-parse", "HEAD") != self.remote_sha():
                        raise SyncBlocked("GitHub a avance; relancer pour finaliser.")
            return 0
        except (SyncBlocked, subprocess.TimeoutExpired, OSError) as exc:
            self.report["status"] = "NO_GO"
            self.report["error"] = str(exc)
            print("  [NO_GO] " + str(exc), flush=True)
            print(
                "  Aucun shard telecharge; aucun push force, reset ou clean.",
                flush=True,
            )
            return 2
        finally:
            self._write_report()


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
        "ALINA CODE SYNC — main local <-> GitHub main — ZERO shard — sans force",
        flush=True,
    )
    return Synchronizer(
        options.root, options.git, dry_run=options.dry_run,
        allow_test_remote=options.test_remote,
    ).run(wip_only=options.wip_only)


if __name__ == "__main__":
    raise SystemExit(main())
