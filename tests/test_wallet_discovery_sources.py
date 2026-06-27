from pathlib import Path

from hl_observer.storage.database import create_session_factory, create_sqlite_engine, init_db
from hl_observer.storage.models import Wallet
from hl_observer.wallets.discovery_sources import ConfigWalletSource, LocalDbWalletSource

VALID_WALLET = "0x" + "7" * 40


def test_discovery_local_db_source_returns_wallets(tmp_path: Path):
    db_url = f"sqlite:///{tmp_path / 'sources.sqlite3'}"
    init_db(db_url)
    session_factory = create_session_factory(create_sqlite_engine(db_url))
    with session_factory() as session:
        session.add(Wallet(address=VALID_WALLET, label="test", status="observed"))
        session.commit()
        result = LocalDbWalletSource().fetch_candidates(session=session)

    assert result.status == "ok"
    assert result.candidates[0].address == VALID_WALLET


def test_discovery_config_source_returns_wallets(tmp_path: Path):
    path = tmp_path / "wallets.yaml"
    path.write_text(
        f"wallets:\n  watchlist:\n    - address: {VALID_WALLET}\n      label: local\n",
        encoding="utf-8",
    )

    result = ConfigWalletSource(path).fetch_candidates()

    assert result.status == "ok"
    assert result.candidates[0].address == VALID_WALLET
