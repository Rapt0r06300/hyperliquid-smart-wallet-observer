"""Atomic, reproducible and evidence-driven portable release orchestrator."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Callable

from hl_observer.collection import verrou_instance
from hl_observer.ops import release_ready
from hl_observer.ops.archive_portable import (
    ArchiveRefuseeError,
    _nom_archive_versionne,
    _version_projet,
    creer_archive_portable,
    etat_git_release,
)
from hl_observer.ops.release_artifacts import produire_artefacts_release
from hl_observer.ops.validation_portable import valider_archive_portable, write_evidence

LOCK_NAME = "portable_release"


def _output_directory(root: Path, configured: str | Path | None) -> Path:
    if configured:
        output = Path(configured).expanduser().resolve()
    else:
        output = (Path(os.environ.get("USERPROFILE", str(Path.home()))) / "Desktop").resolve()
    try:
        output.relative_to(root)
    except ValueError:
        return output
    raise ArchiveRefuseeError("release output directory must be outside project: %s" % output)


def _close_mutex(handle: object) -> None:
    if handle is None:
        return
    try:
        import ctypes
        ctypes.windll.kernel32.ReleaseMutex(handle)
        ctypes.windll.kernel32.CloseHandle(handle)
    except (AttributeError, OSError, TypeError):
        import logging as _lg  # panne rendue VISIBLE (interdiction des except:pass muets)
        _lg.getLogger(__name__).debug("exception ignoree volontairement ici", exc_info=True)


def _acquire_release_lock(root: Path) -> tuple[dict[str, Any], object]:
    mutex_ok, handle = verrou_instance.acquerir_mutex(LOCK_NAME)
    if mutex_ok is False:
        raise ArchiveRefuseeError("another portable release owns the global mutex")
    file_ok, info = verrou_instance.acquerir(root, LOCK_NAME)
    if not file_ok:
        _close_mutex(handle)
        raise ArchiveRefuseeError("another portable release owns the lock file: %s" % info)
    return info, handle


def _release_lock(root: Path):
    class Context:
        info: dict[str, Any] | None = None
        handle: object = None

        def __enter__(self):
            self.info, self.handle = _acquire_release_lock(root)
            return self.info

        def __exit__(self, _type, _value, _traceback):
            if self.info is not None:
                verrou_instance.liberer(root, LOCK_NAME, self.info)
            _close_mutex(self.handle)
            return False

    return Context()


def creer_release_portable(
    root: str | Path,
    *,
    output_directory: str | Path | None = None,
    development: bool = False,
    ci_proof: str | Path | None = None,
    archive_builder: Callable[..., dict[str, Any]] = creer_archive_portable,
    validator: Callable[..., dict[str, Any]] = valider_archive_portable,
    ready_evaluator: Callable[..., dict[str, Any]] = release_ready.evaluer_release,
    artifact_writer: Callable[..., dict[str, Any]] = produire_artefacts_release,
) -> dict[str, Any]:
    """Build twice, validate extracted bytes, then atomically publish on success."""
    root = Path(root).resolve()
    output = _output_directory(root, output_directory)
    output.mkdir(parents=True, exist_ok=True)
    failure_report = output / "RELEASE_FAILED.json"
    failure_report.unlink(missing_ok=True)

    stage = "git_state"
    git: dict[str, Any] = {}
    final_archive: Path | None = None
    publishing: Path | None = None
    try:
        git = etat_git_release(root)
        mode = "developpement" if development else "official"
        if mode == "official" and git.get("dirty"):
            raise ArchiveRefuseeError("official release requires a clean Git checkout")
        version = _version_projet(root)
        if development and git.get("dirty"):
            version += "-dirty"
        final_name = _nom_archive_versionne(root, version, str(git.get("sha", "")))
        final_archive = output / final_name

        stage = "release_lock"
        with _release_lock(root):
            with tempfile.TemporaryDirectory(prefix="hypersmart-portable-release-") as temporary:
                work = Path(temporary)
                first = work / "build-a.zip"
                second = work / "build-b.zip"
                extraction_parent = work / "extractions"
                evidence_path = work / "PORTABLE_VALIDATION.json"
                stage = "build_a"
                first_result = archive_builder(
                    root, first, version=version, mode_release=mode, etat_git=git,
                )
                stage = "build_b"
                second_result = archive_builder(
                    root, second, version=version, mode_release=mode, etat_git=git,
                )
                stage = "extracted_validation"
                evidence = validator(
                    first, archive_repetition=second, ci_proof=ci_proof,
                    extraction_parent=extraction_parent,
                )
                write_evidence(evidence_path, evidence)
                extracted = extraction_parent / "simple"
                stage = "release_ready"
                verdict = ready_evaluator(extracted, preuve=evidence_path)
                if not verdict.get("RELEASE_READY"):
                    failure = {
                        "RELEASE_READY": False,
                        "archive_kept": False,
                        "manquants": verdict.get("manquants", []),
                        "gates": verdict.get("gates", []),
                        "build_a": first_result,
                        "build_b": second_result,
                        "validation": evidence,
                    }
                    failure_report.write_text(
                        json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                        encoding="utf-8", newline="\n",
                    )
                    raise ArchiveRefuseeError(
                        "RELEASE_READY=false: %s" % ", ".join(verdict.get("manquants", []))
                    )
                stage = "atomic_publish"
                publishing = final_archive.with_name(".%s.%d.tmp" % (final_archive.name, os.getpid()))
                publishing.unlink(missing_ok=True)
                shutil.copyfile(first, publishing)
                os.replace(publishing, final_archive)
                publishing = None
                stage = "sidecar_artifacts"
                artifacts = artifact_writer(
                    final_archive,
                    validation={
                        **evidence,
                        "tests": evidence.get("checks", {}).get("tests_archive_extraite", {}),
                        "modules": evidence.get("checks", {}).get("modules_collecteurs", {}),
                        "zero_ecriture_externe": evidence.get("checks", {}).get(
                            "zero_ecriture_externe", {}
                        ),
                    },
                    verdict=verdict,
                    exclusions=first_result.get("exclus_liste", []),
                )
                return {
                    "RELEASE_READY": True,
                    "archive": str(final_archive),
                    "build_a": first_result,
                    "build_b": second_result,
                    "validation": evidence,
                    "verdict": verdict,
                    "artifacts": artifacts,
                }
    except BaseException as exc:
        if publishing is not None:
            publishing.unlink(missing_ok=True)
        if not failure_report.exists():
            failure = {
                "schema": "hypersmart.portable_release_failure.v1",
                "RELEASE_READY": False,
                "archive_kept": False,
                "stage": stage,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "git": git,
            }
            failure_report.write_text(
                json.dumps(failure, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
                encoding="utf-8", newline="\n",
            )
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build and validate an atomic portable release")
    parser.add_argument("--racine", default=".")
    parser.add_argument("--sortie-dir", default="")
    parser.add_argument("--mode-developpement", action="store_true")
    parser.add_argument("--ci-proof", default="")
    args = parser.parse_args(argv)
    try:
        result = creer_release_portable(
            args.racine,
            output_directory=args.sortie_dir or None,
            development=args.mode_developpement,
            ci_proof=args.ci_proof or None,
        )
    except Exception as exc:  # noqa: BLE001 - one fail-closed CLI boundary
        print("RELEASE_REFUSEE: %s" % exc)
        return 1
    print("[OK] RELEASE_READY=true")
    print("[OK] Archive portable publiee: %s" % result["archive"])
    return 0


__all__ = ["LOCK_NAME", "creer_release_portable", "main"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
