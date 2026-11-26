"""Socle bas niveau du compagnon de checkpoints Copy-Vault.

POURQUOI CE MODULE EST À PART (17/11/2026). Ces primitives vivaient dans
``copy_vault_checkpoint_tail.py``. Les réparations du 16/11 (fenêtres de trous, liaison du carnet
pré-signal) l'avaient porté de 739 à 968 lignes pour un plafond de 800, et l'invariant
``test_pas_de_nouveau_fichier_geant`` rougissait à juste titre. Plutôt que de relever le plafond,
ce qui ne dépend d'AUCUN état du compagnon est extrait ici : lecture stricte d'entiers et
d'horodatages, écriture d'une ligne durable, identité de fichier, et le carnet L2 public
(requête + validation).

Rien ne change de comportement : le compagnon réimporte chaque nom tel quel. Aucun ordre, aucune
signature, aucune clé : la seule destination réseau est l'endpoint public ``/info``.
"""
from __future__ import annotations

from contextlib import contextmanager
import errno
import hashlib
import json
import hashlib
import os
import time
import urllib.request
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hl_observer.collection.collecte_fiable import ajouter_atomique
from hl_observer.instrument_identity import preserve_native_instrument_symbol
from hl_observer.normalization.l2_book import normalize_l2_levels

INFO_URL = "https://api.hyperliquid.xyz/info"
MAX_TARGET_LAG_MS = 30_000
CHECKPOINT_SOURCE_RELPATH = Path("runtime") / "data" / "vault_fills_live.jsonl"
CHECKPOINT_SOURCE_LOCK_RELPATH = Path("runtime") / "locks" / "copy_vault_checkpoint_source.lock"
FILL_WRITER_LOCK_RELPATH = Path("runtime") / "locks" / "copy_vault_fill_writer.lock"


class InterprocessLockBusy(RuntimeError):
    """A short-lived cooperative file lock is currently held by another process."""


class CheckpointSourceBusy(InterprocessLockBusy):
    """The forward-only checkpoint companion currently owns the shared source."""


class FillWriterBusy(InterprocessLockBusy):
    """An append is in progress at the fill-file replacement boundary."""


class FillSourceChanged(RuntimeError):
    """A live append arrived while a prepared fill merge was being computed."""


def _lock_contention(error: OSError) -> bool:
    return error.errno in {errno.EACCES, errno.EAGAIN, errno.EDEADLK} or getattr(
        error, "winerror", None
    ) == 33


@contextmanager
def _interprocess_file_lock(lock_path: Path, *, wait_s: float = 0.0,
                            busy_type: type[RuntimeError] = InterprocessLockBusy):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+b")
    locked = False
    try:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        deadline = time.monotonic() + max(0.0, float(wait_s))
        while True:
            handle.seek(0)
            try:
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                locked = True
                break
            except OSError as error:
                if not _lock_contention(error):
                    raise
                if time.monotonic() >= deadline:
                    raise busy_type(f"cooperative lock is busy: {lock_path.name}") from error
                time.sleep(min(0.05, max(0.001, deadline - time.monotonic())))
        yield lock_path
    finally:
        try:
            if locked:
                handle.seek(0)
                if os.name == "nt":
                    import msvcrt

                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


@contextmanager
def copy_vault_checkpoint_source_lock(root: Path, *, wait_s: float = 0.0):
    """Coordinate lane replacement with the forward-only fills tailer.

    The OS releases this advisory lock on process exit. The companion holds it
    for its lifetime; lane merging takes it briefly. Append-only collectors use
    a distinct short lock and continue while this lock is held.
    """
    lock_path = Path(root) / CHECKPOINT_SOURCE_LOCK_RELPATH
    with _interprocess_file_lock(lock_path, wait_s=wait_s, busy_type=CheckpointSourceBusy):
        yield lock_path


@contextmanager
def copy_vault_fill_writer_lock(root: Path, *, wait_s: float = 0.0):
    """Serialize a single append against the final atomic fill-file replacement."""
    lock_path = Path(root) / FILL_WRITER_LOCK_RELPATH
    with _interprocess_file_lock(lock_path, wait_s=wait_s, busy_type=FillWriterBusy):
        yield lock_path


def _strict_int(value: Any, field: str) -> int:
    if type(value) is bool or value is None:
        raise ValueError(f"{field} missing or boolean")
    if isinstance(value, float) and not value.is_integer():
        raise ValueError(f"{field} must be integral")
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        raise ValueError(f"{field} invalid") from None


def _exact_positive_timestamp(value: Any, field: str) -> int:
    """Require an observed positive integer timestamp with no coercion."""
    if type(value) is not int or value <= 0:
        raise ValueError(f"{field} must be a positive integer")
    return value


def _append_jsonl(path: Path, payload: Mapping[str, Any]) -> None:
    # 26/11/2026 : ajout ATOMIQUE. `copy_vault_l2_tape.jsonl` a trois ecrivains (le collecteur userfills, ce socle via
    # le tail des points de controle, et AlinaSync) ; deux ajouts "a" simultanes perdent des lignes sous Windows
    # (mesure). Memes octets qu'avant : JSON compact, fin de ligne "\n", fsync.
    ajouter_atomique(path, json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n",
                     fins_texte=False, fsync=True)


def fetch_hyperliquid_l2_book(coin: str, *, timeout_s: float = 2.0) -> dict[str, Any] | None:
    """Fetch one public read-only Hyperliquid L2 book.

    The only network destination is the official ``/info`` endpoint.  No
    credential, signature or write payload exists in this module.
    """

    body = json.dumps({"type": "l2Book", "coin": preserve_native_instrument_symbol(coin)}).encode("utf-8")
    request = urllib.request.Request(
        INFO_URL,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "HyperSmart/read-only"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=max(0.2, float(timeout_s))) as response:
            if int(response.status) != 200:
                return None
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    return payload if isinstance(payload, dict) else None


def _file_identity(
    stat: os.stat_result, path: Path | None = None, prefix_len: int | None = None
) -> list[int | str]:
    """Stable identity for replacement detection; appends must not look like rotation.

    Device/inode is normally enough, but a filesystem may reuse the same inode immediately
    after unlink/recreate.  A bounded hash of the first 4 KiB makes that replacement visible
    without hashing the 666 MiB lane or changing when bytes are appended at the end.
    """
    head = ""
    longueur = 0
    if path is not None:
        try:
            with path.open("rb") as handle:
                longueur = min(max(0, int(prefix_len)) if prefix_len is not None else 4096,
                                int(stat.st_size))
                head = hashlib.sha256(handle.read(longueur)).hexdigest()
        except OSError:
            head = ""
            longueur = 0
    return [int(stat.st_dev), int(stat.st_ino), longueur, head]


def _file_identity_changed(previous: Any, current: list[int | str]) -> bool:
    """Detect replacement while tolerating append growth of a short file."""
    if not isinstance(previous, list) or len(previous) < 2:
        return previous is not None
    if previous[:2] != current[:2]:
        return True
    if len(previous) < 4:
        return False
    try:
        longueur = int(previous[2])
    except (TypeError, ValueError):
        return True
    return longueur > 0 and previous[3] != current[3]


def _parse_book(raw: Mapping[str, Any], *, received_at_ms: int) -> dict[str, Any] | None:
    try:
        exchange_ts_ms = _exact_positive_timestamp(raw["time"], "time")
        received_at_ms = _exact_positive_timestamp(received_at_ms, "received_at_ms")
        raw_bids, raw_asks = raw["levels"][0], raw["levels"][1]
        bids = normalize_l2_levels(
            [[row["px"], row["sz"]] for row in raw_bids], side="bid"
        )
        asks = normalize_l2_levels(
            [[row["px"], row["sz"]] for row in raw_asks], side="ask"
        )
        if bids is not None:
            bids = bids[:5]
        if asks is not None:
            asks = asks[:5]
    except (KeyError, IndexError, TypeError, ValueError, OverflowError):
        return None
    if (
        exchange_ts_ms <= 0
        or received_at_ms < exchange_ts_ms
        or received_at_ms - exchange_ts_ms > MAX_TARGET_LAG_MS
        or not bids
        or not asks
        or any(px <= 0 or size <= 0 for px, size in bids + asks)
        or bids[0][0] >= asks[0][0]
    ):
        return None
    capacity_usd = min(
        sum(px * size for px, size in bids),
        sum(px * size for px, size in asks),
    )
    if capacity_usd <= 0:
        return None
    return {
        "exchange_ts_ms": exchange_ts_ms,
        "bid": bids[0][0],
        "ask": asks[0][0],
        "bids5": bids,
        "asks5": asks,
        "capacity_usd": capacity_usd,
    }


__all__ = [
    "INFO_URL", "MAX_TARGET_LAG_MS", "fetch_hyperliquid_l2_book",
    "_append_jsonl", "_exact_positive_timestamp", "_file_identity", "_parse_book", "_strict_int",
]
