"""Suppress benign Windows asyncio ConnectionResetError noise in the UI server.

On Windows the asyncio Proactor event loop logs an "Exception in callback
_ProactorBasePipeTransport._call_connection_lost()" with WinError 10054 every
time a browser closes its polling/SSE connection. It is purely cosmetic: the
uvicorn server keeps serving. This filter drops only those specific records.
Read-only dashboard, no runtime behavior change. No-op on non-Windows.
"""

from __future__ import annotations

import logging


class _ConnectionResetNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        exc = record.exc_info[1] if record.exc_info else None
        if isinstance(exc, ConnectionResetError):
            return False
        message = record.getMessage()
        if "_call_connection_lost" in message or "WinError 10054" in message:
            return False
        return True


_FILTER = _ConnectionResetNoiseFilter()


def install_quiet_connection_reset_logging() -> None:
    """Attach the noise filter to the asyncio logger (idempotent)."""
    logger = logging.getLogger("asyncio")
    if not any(isinstance(f, _ConnectionResetNoiseFilter) for f in logger.filters):
        logger.addFilter(_FILTER)
