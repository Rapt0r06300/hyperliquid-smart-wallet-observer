from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

import requests

API_ROOT = "https://api.github.com"
DEFAULT_TIMEOUT = (30.0, 300.0)
DATASET_TOKEN_ENV = "HYPERSMART_DATASET_TOKEN"


class GitHubTransportError(RuntimeError):
    """Erreur contrôlée du transport GitHub privé."""


def github_token() -> str | None:
    """Retourne un token runtime sans jamais le journaliser ni le persister.

    Le secret dédié aux datasets est prioritaire. Les variables historiques ne
    restent que pour les usages manuels hors self-hosted.
    """

    for key in (DATASET_TOKEN_ENV, "GH_TOKEN", "GITHUB_TOKEN"):
        value = str(os.getenv(key, "")).strip()
        if value:
            return value
    return None


def _headers(*, accept: str = "application/vnd.github+json") -> dict[str, str]:
    headers = {
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "Alina-SmartFlow-Research-Runner",
    }
    token = github_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _api_url(path: str) -> str:
    text = str(path).strip()
    if text.startswith("https://"):
        return text
    return f"{API_ROOT}/{text.lstrip('/')}"


def _gh_path() -> str | None:
    return shutil.which("gh")


def _gh_json_fallback(path: str) -> Any:
    gh = _gh_path()
    if not gh:
        raise GitHubTransportError(
            "Aucun token GitHub runtime et GitHub CLI (gh) absent. "
            f"Sur le runner autonome, {DATASET_TOKEN_ENV} doit être fourni par le secret dédié."
        )
    process = subprocess.run(
        [gh, "api", path],
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
    )
    if process.returncode != 0:
        detail = (process.stderr or process.stdout or "").strip()
        raise GitHubTransportError(
            f"GitHub a refusé la lecture de l'API (code {process.returncode}): {detail}"
        )
    try:
        return json.loads(process.stdout)
    except json.JSONDecodeError as exc:
        raise GitHubTransportError("GitHub a renvoyé un JSON illisible.") from exc


def get_json(path: str) -> Any:
    """Lit l'API avec le token runtime; `gh` reste un fallback manuel."""

    if not github_token():
        return _gh_json_fallback(path)
    try:
        response = requests.get(
            _api_url(path),
            headers=_headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise GitHubTransportError(
            f"Lecture HTTPS GitHub impossible pour {path}: {type(exc).__name__}"
        ) from exc
    try:
        return response.json()
    except ValueError as exc:
        raise GitHubTransportError("GitHub a renvoyé un JSON illisible.") from exc


def _download_with_gh(path: str, destination: Path) -> None:
    gh = _gh_path()
    if not gh:
        raise GitHubTransportError(
            "Aucun token GitHub runtime et GitHub CLI (gh) absent; téléchargement privé impossible."
        )
    with destination.open("wb") as target:
        process = subprocess.run(
            [gh, "api", "-H", "Accept: application/octet-stream", path],
            stdout=target,
            stderr=subprocess.PIPE,
        )
    if process.returncode != 0:
        destination.unlink(missing_ok=True)
        detail = process.stderr.decode("utf-8", errors="replace").strip()
        raise GitHubTransportError(
            f"Téléchargement GitHub refusé (code {process.returncode}): {detail}"
        )


def download_release_asset(
    *,
    repository: str,
    asset_id: int,
    destination: Path,
    chunk_bytes: int = 4 * 1024 * 1024,
) -> None:
    """Télécharge un asset privé avec reprise HTTP Range lorsque possible.

    Un fichier partiel existant n'est plus supprimé au démarrage. Si GitHub
    honore ``Range`` (206), le téléchargement reprend à l'octet suivant. Si le
    serveur renvoie 200, le fichier est proprement recommencé. Les contrôles
    SHA-256 en aval restent la preuve finale d'intégrité.
    """

    path = f"repos/{repository}/releases/assets/{int(asset_id)}"
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not github_token():
        destination.unlink(missing_ok=True)
        _download_with_gh(path, destination)
        return

    existing = destination.stat().st_size if destination.exists() else 0
    headers = _headers(accept="application/octet-stream")
    if existing > 0:
        headers["Range"] = f"bytes={existing}-"

    try:
        with requests.get(
            _api_url(path),
            headers=headers,
            timeout=DEFAULT_TIMEOUT,
            stream=True,
            allow_redirects=True,
        ) as response:
            if response.status_code == 416 and existing > 0:
                # Le fichier est potentiellement déjà complet. Le hash aval
                # décidera; on évite de détruire des Gio valides ici.
                return
            response.raise_for_status()
            append = existing > 0 and response.status_code == 206
            mode = "ab" if append else "wb"
            with destination.open(mode) as target:
                for chunk in response.iter_content(chunk_size=max(64 * 1024, int(chunk_bytes))):
                    if chunk:
                        target.write(chunk)
                target.flush()
    except requests.RequestException as exc:
        # Conservation volontaire du .part pour la prochaine reprise.
        raise GitHubTransportError(
            f"Téléchargement HTTPS GitHub impossible pour l'asset {asset_id}: {type(exc).__name__}"
        ) from exc


__all__ = [
    "DATASET_TOKEN_ENV",
    "GitHubTransportError",
    "download_release_asset",
    "get_json",
    "github_token",
]
