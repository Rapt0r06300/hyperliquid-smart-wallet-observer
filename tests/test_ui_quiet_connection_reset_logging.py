"""(a) The UI server silences benign Windows WinError 10054 asyncio noise,
without dropping legitimate asyncio log records."""

from __future__ import annotations

import logging

from hl_observer.ui.quiet_logging import (
    _ConnectionResetNoiseFilter,
    install_quiet_connection_reset_logging,
)


def _record(msg, exc=None):
    return logging.LogRecord(
        name="asyncio", level=logging.ERROR, pathname=__file__, lineno=1,
        msg=msg, args=(), exc_info=(type(exc), exc, None) if exc else None,
    )


def test_filter_drops_connection_reset_and_keeps_real_errors():
    f = _ConnectionResetNoiseFilter()
    assert f.filter(_record("boom", ConnectionResetError(10054, "forcibly closed"))) is False
    assert f.filter(_record("Exception in callback _ProactorBasePipeTransport._call_connection_lost()")) is False
    assert f.filter(_record("real application error")) is True  # legitimate noise NOT dropped


def test_install_is_idempotent():
    logger = logging.getLogger("asyncio")
    before = len(logger.filters)
    install_quiet_connection_reset_logging()
    install_quiet_connection_reset_logging()
    added = [x for x in logger.filters if isinstance(x, _ConnectionResetNoiseFilter)]
    assert len(added) == 1  # installed once, not duplicated
    logger.filters = logger.filters[:before]  # cleanup
