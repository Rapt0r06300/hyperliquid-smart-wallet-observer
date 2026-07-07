from hl_observer.release.clean_archive import build_clean_archive_plan


def _make_tree(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "ok.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / ".env").write_text("PRIVATE_KEY=abc\n", encoding="utf-8")
    (tmp_path / ".env.example").write_text("PRIVATE_KEY=\n", encoding="utf-8")
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "run.log").write_text("noise\n", encoding="utf-8")
    (tmp_path / "secret.key").write_text("KEYMATERIAL\n", encoding="utf-8")
    return tmp_path


def test_excludes_secrets_logs_keeps_source(tmp_path):
    _make_tree(tmp_path)
    plan = build_clean_archive_plan(tmp_path)
    inc = set(plan.included)
    exc = {p: r for p, r in plan.excluded}
    assert "src/ok.py" in inc or "src\\ok.py" in inc
    assert exc.get(".env") == "secret_env"
    assert exc.get("secret.key") == "secret_file"
    assert any(r == "excluded_dir" for r in exc.values())  # logs/
    # .env.example is allowed (not a secret)
    assert ".env.example" in inc


def test_clean_when_no_fake(tmp_path):
    _make_tree(tmp_path)
    plan = build_clean_archive_plan(tmp_path)
    assert plan.clean is True and plan.fake_findings == 0 and plan.blockers == ()


def test_fake_data_blocks_archive(tmp_path):
    _make_tree(tmp_path)
    (tmp_path / "src" / "bad.py").write_text("mid_price = random.uniform(1, 2)\n", encoding="utf-8")
    plan = build_clean_archive_plan(tmp_path)
    assert plan.clean is False and plan.fake_findings >= 1
    assert any("fake-data" in b for b in plan.blockers)


def test_to_dict_shape(tmp_path):
    _make_tree(tmp_path)
    d = build_clean_archive_plan(tmp_path).to_dict()
    assert set(d) == {"included", "excluded", "clean", "blockers", "fake_findings"}
