"""Machine contracts for bounded, local-only quantitative experiments.

This module is deliberately offline.  It validates experiment metadata, derives
reproducible signatures and persists compact state.  It never routes orders,
loads wallets or performs network I/O.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

SCHEMA_VERSION = 1
FAMILIES = frozenset({"copy_vault", "lead_lag", "cross_venue_dislocation_v2"})
PHASES = frozenset(
    {
        "feasibility",
        "train_search",
        "sensitivity",
        "walk_forward",
        "anti_overfit",
        "oos",
        "forward",
        "certification",
    }
)
ENGINES = frozenset(
    {"grid", "random", "qmc", "tpe", "cma_es", "nsga2", "successive_halving", "hyperband"}
)
VERDICTS = frozenset({"REJECT", "ITERATE", "FREEZE_CANDIDATE", "BLOCKED"})
_EXPERIMENT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_HYPOTHESIS_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")
_EVALUATOR_RE = re.compile(
    r"^(hl_observer(?:\.[A-Za-z_][A-Za-z0-9_]*)*|"
    r"tools(?:\.[A-Za-z_][A-Za-z0-9_]*)*):([A-Za-z_][A-Za-z0-9_]*)$"
)


class SpecValidationError(ValueError):
    """Raised when an experiment cannot be executed without weakening the contract."""


def _normalize_json(value: Any, *, field_name: str) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise SpecValidationError(f"{field_name} contains non-finite numeric data")
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            if not isinstance(key, str):
                raise SpecValidationError(f"{field_name} object keys must be strings")
            out[key] = _normalize_json(item, field_name=field_name)
        return out
    if isinstance(value, (list, tuple)):
        return [_normalize_json(item, field_name=field_name) for item in value]
    item_method = getattr(value, "item", None)
    if callable(item_method) and value.__class__.__module__.startswith("numpy"):
        return _normalize_json(item_method(), field_name=field_name)
    raise SpecValidationError(f"{field_name} contains non-JSON value {type(value).__name__}")


def _plain_json(value: Any, *, field_name: str) -> Any:
    normalized = _normalize_json(value, field_name=field_name)
    try:
        encoded = json.dumps(normalized, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise SpecValidationError(f"{field_name} must be finite JSON data") from exc
    return json.loads(encoded)


def _non_empty_mapping(value: Any, field_name: str) -> dict[str, Any]:
    if not isinstance(value, Mapping) or not value:
        raise SpecValidationError(f"{field_name} must be a non-empty mapping")
    plain = _plain_json(dict(value), field_name=field_name)
    if not isinstance(plain, dict):
        raise SpecValidationError(f"{field_name} must be an object")
    return plain


def _validate_search_space(value: Any) -> dict[str, Any]:
    space = _non_empty_mapping(value, "search_space")
    for name, domain in space.items():
        if not isinstance(name, str) or not name:
            raise SpecValidationError("search_space keys must be non-empty strings")
        if isinstance(domain, list):
            if not domain:
                raise SpecValidationError(f"search_space.{name} cannot be empty")
            continue
        if isinstance(domain, dict):
            if "min" not in domain or "max" not in domain:
                raise SpecValidationError(f"search_space.{name} range requires min and max")
            lower, upper = domain["min"], domain["max"]
            if not isinstance(lower, (int, float)) or isinstance(lower, bool):
                raise SpecValidationError(f"search_space.{name}.min must be numeric")
            if not isinstance(upper, (int, float)) or isinstance(upper, bool):
                raise SpecValidationError(f"search_space.{name}.max must be numeric")
            if upper < lower:
                raise SpecValidationError(f"search_space.{name}.max must be >= min")
            continue
        raise SpecValidationError(
            f"search_space.{name} must be a categorical list or min/max range"
        )
    return space


def _validate_budget(value: Any) -> dict[str, Any]:
    budget = _non_empty_mapping(value, "budget")
    trials = budget.get("max_trials")
    if not isinstance(trials, int) or isinstance(trials, bool) or not 1 <= trials <= 1_000_000:
        raise SpecValidationError("budget.max_trials must be an integer in [1, 1000000]")
    wall = budget.get("max_wall_seconds")
    if wall is not None and (
        not isinstance(wall, (int, float)) or isinstance(wall, bool) or wall <= 0
    ):
        raise SpecValidationError("budget.max_wall_seconds must be positive when provided")
    return budget


@dataclass(frozen=True, slots=True)
class ExperimentSpec:
    schema_version: int
    experiment_id: str
    family: str
    hypothesis_id: str
    phase: str
    base_sha: str
    data_fingerprint: str
    data_cutoff_utc: str
    evaluator: str
    search_space: dict[str, Any]
    engine: str
    budget: dict[str, Any]
    seed: int
    cost_model: dict[str, Any]
    split_config: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> "ExperimentSpec":
        if not isinstance(payload, Mapping):
            raise SpecValidationError("experiment spec must be a JSON object")
        required = (
            "schema_version",
            "experiment_id",
            "family",
            "hypothesis_id",
            "phase",
            "base_sha",
            "data_fingerprint",
            "data_cutoff_utc",
            "evaluator",
            "search_space",
            "engine",
            "budget",
            "seed",
            "cost_model",
            "split_config",
        )
        missing = [name for name in required if name not in payload]
        if missing:
            raise SpecValidationError("missing required field(s): " + ", ".join(missing))

        schema_version = payload["schema_version"]
        if schema_version != SCHEMA_VERSION:
            raise SpecValidationError(f"schema_version must be {SCHEMA_VERSION}")

        experiment_id = payload["experiment_id"]
        if not isinstance(experiment_id, str) or not _EXPERIMENT_ID_RE.fullmatch(experiment_id):
            raise SpecValidationError("experiment_id must be a safe 1-80 character identifier")

        family = payload["family"]
        if family not in FAMILIES:
            raise SpecValidationError(f"family must be one of {sorted(FAMILIES)}")

        hypothesis_id = payload["hypothesis_id"]
        if not isinstance(hypothesis_id, str) or not _HYPOTHESIS_RE.fullmatch(hypothesis_id):
            raise SpecValidationError("hypothesis_id must be a safe non-empty identifier")

        phase = payload["phase"]
        if phase not in PHASES:
            raise SpecValidationError(f"phase must be one of {sorted(PHASES)}")

        base_sha = payload["base_sha"]
        if not isinstance(base_sha, str) or not _SHA_RE.fullmatch(base_sha):
            raise SpecValidationError("base_sha must be an exact 40-character Git SHA")

        data_fingerprint = payload["data_fingerprint"]
        if not isinstance(data_fingerprint, str) or not data_fingerprint.strip():
            raise SpecValidationError("data_fingerprint must be non-empty")

        data_cutoff_utc = payload["data_cutoff_utc"]
        if not isinstance(data_cutoff_utc, str) or not data_cutoff_utc.strip():
            raise SpecValidationError("data_cutoff_utc must be non-empty")

        evaluator = payload["evaluator"]
        if not isinstance(evaluator, str) or not _EVALUATOR_RE.fullmatch(evaluator):
            raise SpecValidationError(
                "evaluator must be project-local module:function under hl_observer.* or tools.*"
            )

        engine = payload["engine"]
        if engine not in ENGINES:
            raise SpecValidationError(f"engine must be one of {sorted(ENGINES)}")

        seed = payload["seed"]
        if not isinstance(seed, int) or isinstance(seed, bool):
            raise SpecValidationError("seed must be an integer")

        metadata_raw = payload.get("metadata", {})
        if not isinstance(metadata_raw, Mapping):
            raise SpecValidationError("metadata must be a mapping")

        return cls(
            schema_version=SCHEMA_VERSION,
            experiment_id=experiment_id,
            family=family,
            hypothesis_id=hypothesis_id,
            phase=phase,
            base_sha=base_sha.lower(),
            data_fingerprint=data_fingerprint.strip(),
            data_cutoff_utc=data_cutoff_utc.strip(),
            evaluator=evaluator,
            search_space=_validate_search_space(payload["search_space"]),
            engine=engine,
            budget=_validate_budget(payload["budget"]),
            seed=seed,
            cost_model=_non_empty_mapping(payload["cost_model"], "cost_model"),
            split_config=_non_empty_mapping(payload["split_config"], "split_config"),
            metadata=_plain_json(dict(metadata_raw), field_name="metadata"),
        )

    def as_mapping(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "experiment_id": self.experiment_id,
            "family": self.family,
            "hypothesis_id": self.hypothesis_id,
            "phase": self.phase,
            "base_sha": self.base_sha,
            "data_fingerprint": self.data_fingerprint,
            "data_cutoff_utc": self.data_cutoff_utc,
            "evaluator": self.evaluator,
            "search_space": self.search_space,
            "engine": self.engine,
            "budget": self.budget,
            "seed": self.seed,
            "cost_model": self.cost_model,
            "split_config": self.split_config,
            "metadata": self.metadata,
        }

    def scientific_payload(self) -> dict[str, Any]:
        """Return every input that can change the numerical/scientific outcome.

        Human labels (`experiment_id`) and notes (`metadata`) are intentionally excluded from
        cache identity. Engine and trial budget are included because they change sampled candidates.
        """
        return {
            "schema_version": self.schema_version,
            "family": self.family,
            "hypothesis_id": self.hypothesis_id,
            "phase": self.phase,
            "base_sha": self.base_sha,
            "data_fingerprint": self.data_fingerprint,
            "data_cutoff_utc": self.data_cutoff_utc,
            "evaluator": self.evaluator,
            "search_space": self.search_space,
            "engine": self.engine,
            "budget": self.budget,
            "seed": self.seed,
            "cost_model": self.cost_model,
            "split_config": self.split_config,
        }

    def signature(self) -> str:
        payload = json.dumps(
            self.scientific_payload(), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()


def load_spec(path: Path) -> ExperimentSpec:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SpecValidationError(f"cannot read experiment spec: {exc}") from exc
    return ExperimentSpec.from_mapping(payload)


def result_dir(runtime_root: Path, experiment_id: str) -> Path:
    if not _EXPERIMENT_ID_RE.fullmatch(experiment_id):
        raise SpecValidationError("unsafe experiment_id")
    root = Path(runtime_root).resolve()
    candidate = (root / experiment_id).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise SpecValidationError("experiment output escapes runtime root") from exc
    return candidate


def _write_json_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
    try:
        normalized = _plain_json(dict(payload), field_name="json payload")
        text = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        ) + "\n"
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, target)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def write_summary_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    _write_json_atomic(path, payload)


def write_goal_state_atomic(path: Path, payload: Mapping[str, Any]) -> None:
    _write_json_atomic(path, payload)


def load_cached_summary(runtime_root: Path, signature: str) -> dict[str, Any] | None:
    if not re.fullmatch(r"[0-9a-f]{3,64}", signature):
        return None
    path = Path(runtime_root) / "_cache" / f"{signature}.json"
    if not path.is_file():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(value, dict):
        return None
    if value.get("signature") != signature:
        return None
    return value
