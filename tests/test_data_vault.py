from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import build_data_vault_snapshot as vault_build
from build_data_vault_snapshot import build_snapshot
from data_vault_core import (
    is_secret_path,
    load_gzip_json,
)
from restore_data_vault_snapshot import (
    needed_assets,
    select_records,
)


class DataVaultTests(unittest.TestCase):
    def _build(
        self,
        source: Path,
        output: Path,
        *,
        previous: Path | None = None,
        snapshot: str = "snap-001",
        tag: str = "alina-vault-snap-001",
        small_limit: int = 1024,
        chunk_size: int = 512,
    ):
        return build_snapshot(
            source_root=source,
            output_root=output,
            previous_index_path=previous,
            snapshot_id=snapshot,
            release_tag=tag,
            source_label="test-project",
            include_roots=("runtime", "data"),
            extra_exclude_prefixes=(),
            small_pack_raw_limit=small_limit,
            raw_chunk_size=chunk_size,
        )

    def test_secret_names_are_refused(self):
        self.assertTrue(is_secret_path(".env"))
        self.assertTrue(is_secret_path("runtime/data/private.key"))
        self.assertTrue(is_secret_path("data/id_rsa"))
        self.assertFalse(is_secret_path("runtime/data/bbo_synchro.jsonl"))

    def test_first_snapshot_builds_index_and_filters_secret_text(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "source"
            output = base / "out"
            (source / "runtime" / "data").mkdir(parents=True)
            (source / "runtime" / "data" / "bbo.jsonl").write_text(
                '{"coin":"ETH","bid":1}\n',
                encoding="utf-8",
            )
            (source / "runtime" / "data" / "danger.txt").write_text(
                "api_key=abcdefghijklmnopqrstuvwxyz123456\n",
                encoding="utf-8",
            )

            result = self._build(source, output)
            summary = result["summary"]
            index = load_gzip_json(Path(result["file_index"]))

            self.assertEqual(summary["changed_files"], 1)
            self.assertEqual(index["source_label"], "test-project")
            self.assertEqual(summary["secret_skip_count"], 1)
            self.assertIn("runtime/data/bbo.jsonl", index["files"])
            self.assertNotIn("runtime/data/danger.txt", index["files"])
            self.assertTrue((output / "assets").is_dir())

    def test_second_snapshot_is_incremental_and_tracks_deletion(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "source"
            first = base / "first"
            second = base / "second"
            (source / "runtime" / "data").mkdir(parents=True)
            a = source / "runtime" / "data" / "a.jsonl"
            b = source / "runtime" / "data" / "b.jsonl"
            a.write_text('{"v":1}\n', encoding="utf-8")
            b.write_text('{"v":1}\n', encoding="utf-8")

            first_result = self._build(source, first)
            previous = Path(first_result["file_index"])

            b.unlink()
            a.write_text('{"v":2}\n', encoding="utf-8")

            second_result = self._build(
                source,
                second,
                previous=previous,
                snapshot="snap-002",
                tag="alina-vault-snap-002",
            )
            summary = second_result["summary"]
            index = load_gzip_json(Path(second_result["file_index"]))

            self.assertEqual(summary["changed_files"], 1)
            self.assertEqual(summary["deleted_count"], 1)
            self.assertIn("runtime/data/a.jsonl", index["files"])
            self.assertIn("runtime/data/b.jsonl", index["files"])
            self.assertTrue(index["files"]["runtime/data/a.jsonl"]["present_local"])
            self.assertFalse(index["files"]["runtime/data/b.jsonl"]["present_local"])
            self.assertEqual(
                index["files"]["runtime/data/b.jsonl"]["deleted_at_snapshot"],
                "snap-002",
            )
            self.assertEqual(
                index["files"]["runtime/data/a.jsonl"]["release_tag"],
                "alina-vault-snap-002",
            )

    def test_unchanged_file_keeps_previous_release_reference(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "source"
            first = base / "first"
            second = base / "second"
            (source / "data").mkdir(parents=True)
            path = source / "data" / "stable.json"
            path.write_text('{"stable":true}\n', encoding="utf-8")

            first_result = self._build(source, first)
            previous = Path(first_result["file_index"])
            second_result = self._build(
                source,
                second,
                previous=previous,
                snapshot="snap-002",
                tag="alina-vault-snap-002",
            )
            index = load_gzip_json(Path(second_result["file_index"]))

            self.assertEqual(second_result["summary"]["changed_files"], 0)
            self.assertTrue(index["files"]["data/stable.json"]["present_local"])
            self.assertEqual(
                index["files"]["data/stable.json"]["release_tag"],
                "alina-vault-snap-001",
            )

    def test_large_file_is_split_into_raw_chunks(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "source"
            output = base / "out"
            (source / "runtime").mkdir(parents=True)
            payload = b"x" * 1500
            (source / "runtime" / "large.bin").write_bytes(payload)

            result = self._build(
                source,
                output,
                small_limit=1000,
                chunk_size=600,
            )
            index = load_gzip_json(Path(result["file_index"]))
            record = index["files"]["runtime/large.bin"]

            self.assertEqual(record["storage"], "raw_chunks")
            self.assertEqual(len(record["chunks"]), 3)
            self.assertEqual(sum(chunk["size"] for chunk in record["chunks"]), 1500)

    def test_restore_selection_uses_presets_and_release_assets(self):
        payload = {
            "files": {
                "runtime/data/bbo_tape.jsonl": {
                    "release_tag": "tag-a",
                    "storage": "zip_entry",
                    "asset": "pack.zip",
                    "size": 10,
                    "sha256": "a",
                },
                "runtime/data/vault_fills.jsonl": {
                    "release_tag": "tag-b",
                    "storage": "raw_chunks",
                    "chunks": [
                        {"asset": "part1.bin", "part": 1},
                        {"asset": "part2.bin", "part": 2},
                    ],
                    "size": 20,
                    "sha256": "b",
                },
                "runtime/other/unrelated.bin": {
                    "release_tag": "tag-c",
                    "storage": "zip_entry",
                    "asset": "other.zip",
                    "size": 30,
                    "sha256": "c",
                },
            }
        }

        selected = select_records(
            payload,
            preset="economic-core",
            contains=(),
            prefixes=(),
        )
        self.assertIn("runtime/data/bbo_tape.jsonl", selected)
        self.assertIn("runtime/data/vault_fills.jsonl", selected)
        self.assertNotIn("runtime/other/unrelated.bin", selected)

        assets = needed_assets(selected)
        self.assertEqual(assets["tag-a"], {"pack.zip"})
        self.assertEqual(assets["tag-b"], {"part1.bin", "part2.bin"})

    def test_current_restore_excludes_archived_deleted_by_default(self):
        payload = {
            "files": {
                "runtime/data/current.jsonl": {
                    "present_local": True,
                    "release_tag": "tag-a",
                    "storage": "zip_entry",
                    "asset": "pack.zip",
                    "size": 10,
                    "sha256": "a",
                },
                "runtime/data/old.jsonl": {
                    "present_local": False,
                    "release_tag": "tag-old",
                    "storage": "zip_entry",
                    "asset": "old.zip",
                    "size": 10,
                    "sha256": "b",
                },
                "runtime/data/stale.jsonl": {
                    "present_local": True,
                    "backup_stale": True,
                    "release_tag": "tag-stale",
                    "storage": "zip_entry",
                    "asset": "stale.zip",
                    "size": 10,
                    "sha256": "c",
                },
            }
        }

        current = select_records(
            payload,
            preset="economic-core",
            contains=(),
            prefixes=(),
        )
        self.assertIn("runtime/data/current.jsonl", current)
        self.assertNotIn("runtime/data/old.jsonl", current)
        self.assertNotIn("runtime/data/stale.jsonl", current)

        historical = select_records(
            payload,
            preset="economic-core",
            contains=(),
            prefixes=(),
            include_archived_deleted=True,
        )
        self.assertIn("runtime/data/current.jsonl", historical)
        self.assertIn("runtime/data/old.jsonl", historical)
        self.assertNotIn("runtime/data/stale.jsonl", historical)

        with_stale = select_records(
            payload,
            preset="economic-core",
            contains=(),
            prefixes=(),
            include_archived_deleted=True,
            include_stale_prior=True,
        )
        self.assertIn("runtime/data/stale.jsonl", with_stale)

    def test_unstable_live_file_keeps_prior_backup_but_marks_it_stale(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "source"
            first = base / "first"
            second = base / "second"
            (source / "runtime" / "data").mkdir(parents=True)
            path = source / "runtime" / "data" / "live.jsonl"
            path.write_text('{"v":1}\n', encoding="utf-8")

            first_result = self._build(source, first)
            previous = Path(first_result["file_index"])
            path.write_text('{"v":2}\n', encoding="utf-8")

            with patch.object(vault_build, "stable_copy", return_value=None):
                second_result = self._build(
                    source,
                    second,
                    previous=previous,
                    snapshot="snap-002",
                    tag="alina-vault-snap-002",
                )

            index = load_gzip_json(Path(second_result["file_index"]))
            record = index["files"]["runtime/data/live.jsonl"]
            self.assertTrue(record["present_local"])
            self.assertTrue(record["backup_stale"])
            self.assertEqual(record["backup_deferred_reason"], "unstable_during_copy")
            self.assertEqual(record["release_tag"], "alina-vault-snap-001")
            self.assertEqual(second_result["summary"]["stale_prior_files"], 1)

    def test_publish_list_contains_metadata_assets(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            source = base / "source"
            output = base / "out"
            (source / "runtime").mkdir(parents=True)
            (source / "runtime" / "x.json").write_text('{"x":1}\n', encoding="utf-8")

            result = self._build(source, output)
            publish = json.loads(
                Path(result["publish_list"]).read_text(encoding="utf-8")
            )
            names = {row["name"] for row in publish["assets"]}

            self.assertIn("VAULT_SNAPSHOT_MANIFEST.json.gz", names)
            self.assertIn("VAULT_FILE_INDEX.json.gz", names)
            self.assertIn("VAULT_SUMMARY.json", names)


if __name__ == "__main__":
    unittest.main()
