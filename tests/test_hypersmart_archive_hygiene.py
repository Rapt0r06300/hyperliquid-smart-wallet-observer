import pytest
from zipfile import ZipFile

from hyper_smart_observer.runtime.archive import create_clean_archive, is_archive_safe_path


def test_archive_safe_path_excludes_runtime_files():
    assert not is_archive_safe_path(__import__("pathlib").Path("logs/runtime.sqlite3"))
    assert not is_archive_safe_path(__import__("pathlib").Path("data/runtime.sqlite3-wal"))
    assert not is_archive_safe_path(__import__("pathlib").Path(".refact/cache.json"))
    assert not is_archive_safe_path(__import__("pathlib").Path(".env"))
    assert is_archive_safe_path(__import__("pathlib").Path("hyper_smart_observer/app/main.py"))
    assert is_archive_safe_path(__import__("pathlib").Path("src/hl_observer/cli.py"))


def test_clean_archive_excludes_logs_data_db(tmp_path):
    root = tmp_path / "repo"
    (root / "hyper_smart_observer").mkdir(parents=True)
    (root / "hyper_smart_observer" / "__init__.py").write_text("# ok\n", encoding="utf-8")
    (root / "src" / "hl_observer").mkdir(parents=True)
    (root / "src" / "hl_observer" / "__init__.py").write_text("# ok\n", encoding="utf-8")
    (root / "logs").mkdir()
    (root / "logs" / "locked.sqlite3").write_bytes(b"db")
    (root / "data").mkdir()
    (root / "data" / "runtime.log").write_text("log", encoding="utf-8")
    (root / ".env").write_text("SECRET=never\n", encoding="utf-8")

    result = create_clean_archive(root, tmp_path / "out", name="clean.zip")

    with ZipFile(result.archive_path) as zip_file:
        names = zip_file.namelist()
    assert "hyper_smart_observer/__init__.py" in names
    assert "src/hl_observer/__init__.py" in names
    assert all(not name.startswith(("logs/", "data/")) for name in names)
    assert ".env" not in names
    assert all(not name.endswith((".sqlite3", ".sqlite3-wal", ".sqlite3-shm", ".db", ".log")) for name in names)
    assert result.archive_path.parent == tmp_path / "out"


def test_clean_archive_refuses_output_inside_project(tmp_path):
    root = tmp_path / "repo"
    (root / "hyper_smart_observer").mkdir(parents=True)
    (root / "hyper_smart_observer" / "__init__.py").write_text("# ok\n", encoding="utf-8")

    with pytest.raises(RuntimeError):
        create_clean_archive(root, root, name="dirty.zip")


def test_clean_archive_powershell_script_contains_safe_staging_rules():
    text = __import__("pathlib").Path("tools/create_clean_archive.ps1").read_text(encoding="utf-8")

    assert "Projet_invest_clean_" in text
    assert "Desktop" in text
    assert "Refused: OutputDir is inside the project" in text
    assert "staging" in text.lower()
    assert '"logs"' in text
    assert '"data"' in text
    assert '".refact"' in text
    assert ".sqlite3" in text
    assert "Compress-Archive" in text
    assert "LANCER_HYPERSMART.cmd" in text


def test_python_archive_manifest_includes_single_launcher():
    text = __import__("pathlib").Path("hyper_smart_observer/runtime/archive.py").read_text(encoding="utf-8")

    assert '"CREER_ARCHIVE_PROPRE.cmd"' in text
    assert '"LANCER_HYPERSMART.cmd"' in text


def test_archive_button_calls_powershell_script():
    text = __import__("pathlib").Path("CREER_ARCHIVE_PROPRE.cmd").read_text(encoding="utf-8")

    assert "create_clean_archive.ps1" in text
    assert "ExecutionPolicy Bypass" in text
