from __future__ import annotations

from hl_observer.backtesting.experiment_environment import (
    build_environment_freeze,
    verify_environment_freeze,
)


def test_environment_freeze_est_stable_et_verifiable():
    kwargs = {
        "code_sha256": "a" * 64,
        "dependency_lock_sha256": "b" * 64,
        "dependencies": {"numpy": "2.0", "python-dateutil": "2.9"},
        "python_version": "3.14.2",
        "platform_name": "win32",
        "architecture": "AMD64",
    }
    first = build_environment_freeze(**kwargs)
    second = build_environment_freeze(
        **{**kwargs, "dependencies": {"python-dateutil": "2.9", "numpy": "2.0"}}
    )

    assert first == second
    assert verify_environment_freeze(first) is True


def test_environment_freeze_refuse_un_hash_incomplet():
    try:
        build_environment_freeze(
            code_sha256="not-a-sha",
            dependency_lock_sha256="b" * 64,
            dependencies={"numpy": "2.0"},
        )
    except ValueError as exc:
        assert "SHA-256" in str(exc)
    else:
        raise AssertionError("un hash incomplet ne doit pas être accepté")


def test_environment_freeze_detecte_une_modification():
    frozen = build_environment_freeze(
        code_sha256="a" * 64,
        dependency_lock_sha256="b" * 64,
        dependencies={"numpy": "2.0"},
        python_version="3.14.2",
        platform_name="win32",
        architecture="AMD64",
    )
    frozen["dependencies"]["numpy"] = "2.1"

    assert verify_environment_freeze(frozen) is False
