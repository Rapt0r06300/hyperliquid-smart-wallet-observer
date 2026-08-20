from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import requests

API_ROOT = "https://api.github.com"
DEFAULT_TIMEOUT = (30.0, 300.0)
DATASET_TOKEN_ENV = "HYPERSMART_DATASET_TOKEN"
_CONTENT_RANGE_RE = re.compile(r"^bytes\s+(\d+)-(\d+)/(\d+|\*)$", re.IGNORECASE)


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
        target.flush()
        os.fsync(target.fileno())
    if process.returncode != 0:
        destination.unlink(missing_ok=True)
        detail = process.stderr.decode("utf-8", errors="replace").strip()
        raise GitHubTransportError(
            f"Téléchargement GitHub refusé (code {process.returncode}): {detail}"
        )


def _response_status_code(response: object) -> int:
    """Retourne un statut HTTP sûr pour les transports/mocks historiques.

    Les anciens doubles de test ne possédaient pas ``status_code``. Après un
    ``raise_for_status`` réussi ils sont traités comme une réponse complète 200,
    jamais comme un 206 : on ne doit surtout pas append un partiel sans preuve.
    """

    value = getattr(response, "status_code", 200)
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return 200


def _content_range_start(response: object) -> int | None:
    headers = getattr(response, "headers", None)
    if headers is None or not hasattr(headers, "get"):
        return None
    raw = headers.get("Content-Range") or headers.get("content-range")
    if raw is None:
        return None
    match = _CONTENT_RANGE_RE.fullmatch(str(raw).strip())
    if match is None:
        return None
    return int(match.group(1))


def download_release_asset(
    *,
    repository: str,
    asset_id: int,
    destination: Path,
    chunk_bytes: int = 4 * 1024 * 1024,
) -> None:
    """Télécharge un asset privé avec reprise HTTP Range fail-closed.

    Le fichier de destination sert de partiel persistant. Un 206 n'est appendé
    que si ``Content-Range`` confirme exactement l'octet de reprise demandé. Un
    200 redémarre proprement depuis zéro. Un 416 conserve le partiel : le hash
    SHA-256 aval reste l'arbitre final d'intégrité. Les écritures réussies sont
    synchronisées sur disque afin qu'un crash Windows ne transforme pas un
    téléchargement annoncé comme écrit en cache fantôme.
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
            status_code = _response_status_code(response)
            if status_code == 416 and existing > 0:
                # Potentiellement déjà complet. Ne jamais détruire des Gio ici;
                # le hash aval validera ou forcera une reconstruction.
                return
            response.raise_for_status()

            append = existing > 0 and status_code == 206
            if append:
                start = _content_range_start(response)
                if start is None:
                    raise GitHubTransportError(
                        f"Reprise asset {asset_id} refusée: 206 sans Content-Range vérifiable."
                    )
                if start != existing:
                    raise GitHubTransportError(
                        "Reprise asset "
                        f"{asset_id} refusée: Content-Range commence à {start}, attendu {existing}."
                    )

            mode = "ab" if append else "wb"
            with destination.open(mode) as target:
                for chunk in response.iter_content(
                    chunk_size=max(64 * 1024, int(chunk_bytes))
                ):
                    if chunk:
                        target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
    except (requests.RequestException, OSError) as exc:
        # Le partiel déjà présent ou nouvellement écrit est conservé pour une
        # prochaine tentative. Aucune suppression destructive sur erreur réseau.
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
