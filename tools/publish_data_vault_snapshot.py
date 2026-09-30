from __future__ import annotations

import argparse
import http.client
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from data_vault_core import sha256_file, utc_now

API_HOST = "api.github.com"
UPLOAD_HOST = "uploads.github.com"
API_VERSION = "2022-11-28"
DEFAULT_REPOSITORY = "Rapt0r06300/hypersmart-datasets"


class PublishError(RuntimeError):
    pass


def _headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": API_VERSION,
        "User-Agent": "Alina-Data-Vault",
    }


def api_json(
    method: str,
    path: str,
    token: str,
    payload: dict[str, Any] | None = None,
    *,
    allow_404: bool = False,
) -> dict[str, Any] | None:
    body = None
    headers = _headers(token)
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(
        f"https://{API_HOST}{path}",
        data=body,
        headers=headers,
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        if allow_404 and exc.code == 404:
            return None
        detail = exc.read().decode("utf-8", errors="replace")
        raise PublishError(f"GitHub API {method} {path} failed: {exc.code} {detail}") from exc
    if not raw:
        return {}
    parsed = json.loads(raw.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise PublishError(f"GitHub API returned non-object for {method} {path}")
    return parsed


def release_by_tag(repository: str, tag: str, token: str) -> dict[str, Any] | None:
    encoded = urllib.parse.quote(tag, safe="")
    return api_json(
        "GET",
        f"/repos/{repository}/releases/tags/{encoded}",
        token,
        allow_404=True,
    )


def create_or_resume_draft(
    repository: str,
    *,
    tag: str,
    title: str,
    notes: str,
    token: str,
) -> dict[str, Any]:
    existing = release_by_tag(repository, tag, token)
    if existing is not None:
        if existing.get("draft") is not True:
            return existing
        return existing
    created = api_json(
        "POST",
        f"/repos/{repository}/releases",
        token,
        {
            "tag_name": tag,
            "target_commitish": "main",
            "name": title,
            "body": notes,
            "draft": True,
            "prerelease": False,
            "generate_release_notes": False,
        },
    )
    if not created:
        raise PublishError("release creation returned empty response")
    return created


def _asset_digest(asset: dict[str, Any]) -> str:
    value = str(asset.get("digest") or "")
    prefix = "sha256:"
    return value[len(prefix):] if value.startswith(prefix) else ""


def _local_asset(entry: dict[str, Any]) -> tuple[Path, int, str]:
    path = Path(str(entry.get("path") or "")).resolve()
    if not path.is_file():
        raise PublishError(f"asset missing: {path}")
    size = int(entry.get("size") or 0)
    digest = str(entry.get("sha256") or "").lower()
    if path.stat().st_size != size:
        raise PublishError(f"asset size changed after build: {path.name}")
    actual = sha256_file(path)
    if not digest or actual.lower() != digest:
        raise PublishError(f"asset sha256 changed after build: {path.name}")
    return path, size, actual.lower()


def _existing_asset_map(release: dict[str, Any]) -> dict[str, dict[str, Any]]:
    assets = release.get("assets")
    if not isinstance(assets, list):
        return {}
    return {
        str(item.get("name")): item
        for item in assets
        if isinstance(item, dict) and item.get("name")
    }


def upload_asset_streaming(
    *,
    repository: str,
    release_id: int,
    path: Path,
    name: str,
    token: str,
    content_type: str = "application/octet-stream",
    attempts: int = 3,
) -> dict[str, Any]:
    size = path.stat().st_size
    encoded_name = urllib.parse.quote(name, safe="")
    request_path = (
        f"/repos/{repository}/releases/{release_id}/assets"
        f"?name={encoded_name}"
    )

    last_error = ""
    for attempt in range(1, attempts + 1):
        connection = http.client.HTTPSConnection(UPLOAD_HOST, timeout=180)
        try:
            connection.putrequest("POST", request_path)
            for key, value in _headers(token).items():
                connection.putheader(key, value)
            connection.putheader("Content-Type", content_type)
            connection.putheader("Content-Length", str(size))
            connection.endheaders()

            with path.open("rb") as handle:
                while True:
                    chunk = handle.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    connection.send(chunk)

            response = connection.getresponse()
            raw = response.read()
            if response.status == 201:
                parsed = json.loads(raw.decode("utf-8"))
                if not isinstance(parsed, dict):
                    raise PublishError(f"invalid asset response for {name}")
                return parsed
            last_error = raw.decode("utf-8", errors="replace")
        except (OSError, http.client.HTTPException) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
        finally:
            connection.close()

        if attempt < attempts:
            time.sleep(min(15, 2 ** attempt))

    raise PublishError(f"asset upload failed for {name}: {last_error}")


def verify_or_upload_assets(
    repository: str,
    release: dict[str, Any],
    publish_entries: list[dict[str, Any]],
    token: str,
) -> list[dict[str, Any]]:
    release_id = int(release.get("id") or 0)
    if release_id <= 0:
        raise PublishError("invalid release id")

    existing = _existing_asset_map(release)
    verified: list[dict[str, Any]] = []

    for entry in publish_entries:
        name = str(entry.get("name") or "")
        if not name:
            raise PublishError("publish entry without name")
        path, size, digest = _local_asset(entry)

        remote = existing.get(name)
        if remote is not None:
            remote_size = int(remote.get("size") or 0)
            remote_digest = _asset_digest(remote).lower()
            if remote_size != size:
                raise PublishError(
                    f"existing asset size mismatch for {name}: {remote_size} != {size}"
                )
            if not remote_digest:
                raise PublishError(f"existing asset has no GitHub SHA-256 digest: {name}")
            if remote_digest != digest:
                raise PublishError(
                    f"existing asset digest mismatch for {name}: {remote_digest} != {digest}"
                )
            verified.append(
                {
                    "name": name,
                    "asset_id": int(remote.get("id") or 0),
                    "size": size,
                    "sha256": digest,
                    "reused": True,
                }
            )
            continue

        uploaded = upload_asset_streaming(
            repository=repository,
            release_id=release_id,
            path=path,
            name=name,
            token=token,
        )
        uploaded_size = int(uploaded.get("size") or 0)
        uploaded_digest = _asset_digest(uploaded).lower()
        if uploaded_size != size:
            raise PublishError(
                f"uploaded asset size mismatch for {name}: {uploaded_size} != {size}"
            )
        if not uploaded_digest:
            raise PublishError(f"uploaded asset has no GitHub SHA-256 digest: {name}")
        if uploaded_digest != digest:
            raise PublishError(
                f"uploaded asset digest mismatch for {name}: {uploaded_digest} != {digest}"
            )
        verified.append(
            {
                "name": name,
                "asset_id": int(uploaded.get("id") or 0),
                "size": size,
                "sha256": digest,
                "reused": False,
            }
        )
    return verified


def publish_snapshot(
    *,
    repository: str,
    publish_list_path: Path,
    token: str,
    output_path: Path,
) -> dict[str, Any]:
    payload = json.loads(publish_list_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PublishError("invalid publish list")
    snapshot_id = str(payload.get("snapshot_id") or "")
    tag = str(payload.get("release_tag") or "")
    entries = payload.get("assets")
    if not snapshot_id or not tag or not isinstance(entries, list):
        raise PublishError("publish list missing snapshot_id/release_tag/assets")

    title = f"Alina Data Vault {snapshot_id}"
    notes = (
        "Incremental Alina SmartFlow data backup. "
        "Assets are verified by size and SHA-256. "
        "Paper/read-only dataset storage; no execution capability."
    )
    release = create_or_resume_draft(
        repository,
        tag=tag,
        title=title,
        notes=notes,
        token=token,
    )
    if release.get("draft") is False:
        existing_assets = _existing_asset_map(release)
        missing = [
            str(entry.get("name"))
            for entry in entries
            if str(entry.get("name")) not in existing_assets
        ]
        if missing:
            raise PublishError(
                "release already published but required assets are missing: "
                + ", ".join(missing[:20])
            )

    verified = verify_or_upload_assets(
        repository,
        release,
        [dict(item) for item in entries if isinstance(item, dict)],
        token,
    )

    release_id = int(release.get("id") or 0)
    final_release = api_json(
        "PATCH",
        f"/repos/{repository}/releases/{release_id}",
        token,
        {
            "name": title,
            "body": notes,
            "draft": False,
            "prerelease": False,
        },
    )
    if not final_release:
        raise PublishError("release publication returned empty response")

    final_assets = _existing_asset_map(final_release)
    for row in verified:
        remote = final_assets.get(row["name"])
        if remote is None:
            raise PublishError(f"asset disappeared after publication: {row['name']}")
        if int(remote.get("size") or 0) != int(row["size"]):
            raise PublishError(f"final size mismatch: {row['name']}")
        remote_digest = _asset_digest(remote).lower()
        if not remote_digest:
            raise PublishError(f"final asset has no GitHub SHA-256 digest: {row['name']}")
        if remote_digest != str(row["sha256"]).lower():
            raise PublishError(f"final digest mismatch: {row['name']}")

    result = {
        "schema": "alina.data_vault.published_release.v1",
        "published_at_utc": utc_now(),
        "repository": repository,
        "snapshot_id": snapshot_id,
        "tag": tag,
        "release_id": int(final_release.get("id") or 0),
        "html_url": final_release.get("html_url"),
        "asset_count": len(verified),
        "asset_bytes": sum(int(row["size"]) for row in verified),
        "assets": verified,
        "draft": bool(final_release.get("draft")),
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Publish a prepared Alina Data Vault snapshot to a GitHub Release."
    )
    parser.add_argument("--repository", default=DEFAULT_REPOSITORY)
    parser.add_argument("--publish-list", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--token-env", default="GITHUB_TOKEN")
    args = parser.parse_args(argv)

    token = os.environ.get(args.token_env, "").strip()
    if not token:
        raise SystemExit(f"missing token in environment: {args.token_env}")
    if args.repository != DEFAULT_REPOSITORY:
        raise SystemExit(f"refusing unexpected repository: {args.repository}")

    try:
        result = publish_snapshot(
            repository=args.repository,
            publish_list_path=args.publish_list.resolve(),
            token=token,
            output_path=args.output.resolve(),
        )
    except (PublishError, OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False))
        return 2

    print(json.dumps({"ok": True, **result}, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
