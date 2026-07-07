from hl_observer.storage.database import create_sqlite_engine


def test_sqlite_engine_pool_is_sized_for_local_dashboard_polling(tmp_path):
    engine = create_sqlite_engine(f"sqlite:///{tmp_path / 'runtime.sqlite3'}")

    pool = engine.pool
    assert pool.size() >= 20
    assert pool._max_overflow >= 40  # local read-heavy UI + scanner poller headroom
