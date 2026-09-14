"""Build metadata for an exact, downloadable full-folder release.

The module never follows Windows reparse points.  Regular files and empty
directories are archived, while junctions are recorded and recreated by the
installer with a target relative to the installed root.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


SCHEMA_VERSION = 1
MANIFEST_NAME = "ALINA_FULL_FOLDER_RELEASE.json"
INVENTORY_NAME = "ALINA_FULL_FOLDER_INVENTORY.json"
ARCHIVE_BASENAME = "Alina-SmartFlow-Full.7z"
SECRET_NAMES = frozenset({".env", "id_rsa", "id_ed25519"})
SECRET_SUFFIXES = (".key", ".p12", ".pfx", ".mnemonic", ".seed", ".keystore")
TEMPLATE_SUFFIXES = (".example", ".sample", ".template", ".dist")
PUBLIC_NONSECRET_ENV_HASHES = {
    "runtime/research/github_repos_v24/20_warp_id_solana_trading_bot/.env.copy": "9c487bab0b65e1b888283dd5c6240097d716ed40245bba38338346369ed6cc7c",
    "runtime/research/github_repos_v24/23_octobot/packages/node/.env.test": "d9c2530b74956a812a99e01b6f694d91fe2bce2411bc4b4e5d1754af3a05f38b",
}


class FullFolderReleaseError(RuntimeError):
    """Release construction was refused before publication."""


@dataclass(frozen=True)
class SourceEntry:
    path: str
    kind: str
    size: int = 0
    sha256: str = ""
    target: str = ""
    reason: str = ""

    def as_dict(self) -> dict[str, object]:
        result: dict[str, object] = {"path": self.path, "kind": self.kind}
        if self.kind == "file":
            result.update(size=self.size, sha256=self.sha256)
        elif self.kind == "junction":
            result["target"] = self.target
        elif self.kind == "excluded":
            result["reason"] = self.reason
        return result


def sha256_file(path: str | Path, chunk_size: int = 8 * 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_json(payload: object) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & 0x400)


def _is_public_template(name: str) -> bool:
    lower = name.casefold()
    return lower == ".env.example" or any(lower.endswith(suffix) for suffix in TEMPLATE_SUFFIXES)


def _assert_public_path(relative: str) -> None:
    if relative.replace("\\", "/").casefold() in PUBLIC_NONSECRET_ENV_HASHES:
        return
    name = Path(relative).name.casefold()
    if ((name in SECRET_NAMES or name.startswith(".env.")) and not _is_public_template(name)) or name.endswith(SECRET_SUFFIXES):
        raise FullFolderReleaseError(f"secret filename refused: {relative}")


def _within(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except (OSError, ValueError):
        return False


def _lexically_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def inventory_source(root: str | Path, *, exclude: str | Path | None = None, hash_files: bool = True) -> list[SourceEntry]:
    source = Path(root).resolve()
    excluded = Path(exclude).resolve() if exclude else None
    if not source.is_dir():
        raise FullFolderReleaseError(f"source root does not exist: {source}")
    if excluded is not None and not _within(excluded, source):
        raise FullFolderReleaseError("excluded build directory must be inside source root")

    entries: list[SourceEntry] = []
    for current_text, directory_names, file_names in os.walk(source, topdown=True, followlinks=False):
        current = Path(current_text)
        kept: list[str] = []
        for name in sorted(directory_names, key=str.casefold):
            candidate = current / name
            if excluded is not None and _lexically_within(candidate, excluded):
                continue
            relative = candidate.relative_to(source).as_posix()
            _assert_public_path(relative)
            if _is_reparse(candidate):
                target = candidate.resolve()
                if not _within(target, source):
                    raise FullFolderReleaseError(f"junction target escapes source root: {relative}")
                entries.append(SourceEntry(relative, "junction", target=target.relative_to(source).as_posix()))
                continue
            kept.append(name)
        directory_names[:] = kept

        visible_files: list[str] = []
        for name in sorted(file_names, key=str.casefold):
            path = current / name
            if excluded is not None and _lexically_within(path, excluded):
                continue
            relative = path.relative_to(source).as_posix()
            _assert_public_path(relative)
            if _is_reparse(path):
                raise FullFolderReleaseError(f"file reparse point refused: {relative}")
            size = path.stat().st_size
            normalized = relative.casefold()
            known_public_hash = PUBLIC_NONSECRET_ENV_HASHES.get(normalized)
            try:
                digest = sha256_file(path) if hash_files or known_public_hash else ""
            except PermissionError:
                parts = {part.casefold() for part in Path(relative).parts}
                if "__pycache__" not in parts or path.suffix.casefold() != ".pyc":
                    raise
                entries.append(SourceEntry(relative, "excluded", size=size, reason="unreadable_generated_python_cache"))
                continue
            if known_public_hash and digest != known_public_hash:
                raise FullFolderReleaseError(f"reviewed public environment file changed: {relative}")
            entries.append(SourceEntry(relative, "file", size=size, sha256=digest))
            visible_files.append(name)
        if current != source and not directory_names and not visible_files:
            relative = current.relative_to(source).as_posix()
            entries.append(SourceEntry(relative, "directory"))

    entries.sort(key=lambda entry: (entry.path.casefold(), entry.kind))
    folded: set[str] = set()
    for entry in entries:
        key = entry.path.casefold()
        if key in folded:
            raise FullFolderReleaseError(f"case-insensitive path collision: {entry.path}")
        folded.add(key)
    return entries


def inventory_payload(root: Path, entries: Iterable[SourceEntry], *, head: str) -> dict[str, object]:
    material = [entry.as_dict() for entry in entries]
    files = [entry for entry in material if entry["kind"] == "file"]
    return {
        "schema_version": SCHEMA_VERSION,
        "git_head": head,
        "file_count": len(files),
        "total_bytes": sum(int(entry["size"]) for entry in files),
        "entries": material,
    }


def write_plan(root: Path, output: Path, head: str) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    entries = inventory_source(root, exclude=output, hash_files=True)
    inventory = inventory_payload(root, entries, head=head)
    inventory_bytes = canonical_json(inventory)
    (output / INVENTORY_NAME).write_bytes(inventory_bytes)
    archive_members = [entry.path for entry in entries if entry.kind in {"file", "directory"}]
    (output / "archive-members.txt").write_text("\n".join(archive_members) + "\n", encoding="utf-8", newline="\n")
    snapshots = {
        entry.path: {"size": entry.size, "mtime_ns": (root / Path(entry.path)).stat().st_mtime_ns}
        for entry in entries if entry.kind == "file"
    }
    (output / "source-snapshot.json").write_bytes(canonical_json(snapshots))
    return {"inventory_sha256": sha256_bytes(inventory_bytes), "file_count": inventory["file_count"], "total_bytes": inventory["total_bytes"]}


def finalize(root: Path, output: Path, tag: str, head: str, repository: str) -> dict[str, object]:
    inventory_path = output / INVENTORY_NAME
    snapshot_path = output / "source-snapshot.json"
    if not inventory_path.is_file() or not snapshot_path.is_file():
        raise FullFolderReleaseError("run plan before finalize")
    inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    snapshots = json.loads(snapshot_path.read_text(encoding="utf-8"))
    for relative, expected in snapshots.items():
        stat = (root / Path(relative)).stat()
        if stat.st_size != expected["size"] or stat.st_mtime_ns != expected["mtime_ns"]:
            raise FullFolderReleaseError(f"source changed during archive build: {relative}")
    parts = sorted(output.glob(ARCHIVE_BASENAME + ".*"))
    if not parts:
        raise FullFolderReleaseError("no split archive parts found")
    assets = [{"name": part.name, "size": part.stat().st_size, "sha256": sha256_file(part)} for part in parts]
    manifest = {
        "schema_version": SCHEMA_VERSION,
        "repository": repository,
        "tag": tag,
        "git_head": head,
        "inventory": {"name": INVENTORY_NAME, "size": inventory_path.stat().st_size, "sha256": sha256_file(inventory_path)},
        "archive_first_part": parts[0].name,
        "archive_assets": assets,
        "file_count": inventory["file_count"],
        "total_bytes": inventory["total_bytes"],
    }
    (output / MANIFEST_NAME).write_bytes(canonical_json(manifest))
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("plan", "finalize"):
        item = sub.add_parser(name)
        item.add_argument("--root", type=Path, required=True)
        item.add_argument("--output", type=Path, required=True)
        item.add_argument("--head", required=True)
        if name == "finalize":
            item.add_argument("--tag", required=True)
            item.add_argument("--repository", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            result = write_plan(args.root.resolve(), args.output.resolve(), args.head)
        else:
            result = finalize(args.root.resolve(), args.output.resolve(), args.tag, args.head, args.repository)
    except FullFolderReleaseError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        return 2
    print(json.dumps({"ok": True, **result}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
